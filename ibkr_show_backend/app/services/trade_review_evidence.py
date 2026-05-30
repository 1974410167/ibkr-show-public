from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from hashlib import sha1
import threading
from typing import Any

from app.agents.evidence_schema import build_trade_review_evidence_pack
from app.clients.es_client import ESClientError, ElasticsearchClient
from app.core.config import Settings
from app.schemas.longbridge import LongbridgeCandleItem, LongbridgeNewsItem
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, LongbridgeUnavailableError, normalize_longbridge_symbol
from app.services.trade_review_scoring import TradeReviewMetricsCalculator
from app.utils.dates import parse_date

TARGET_ANNUAL_RETURN = 0.30
DEFAULT_BENCHMARKS = ["SPY.US", "QQQ.US", "SMH.US"]
BUY_SIDE_ALIASES = {"BUY", "BOT", "BOUGHT"}
SELL_SIDE_ALIASES = {"SELL", "SLD", "SOLD", "SELL_SHORT", "SSHORT"}


def normalize_ibkr_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.startswith("US."):
        return value[3:]
    if value.endswith(".US"):
        return value[:-3]
    return value


def build_stable_trade_id(trade: dict) -> str:
    existing = trade.get("trade_id") or trade.get("transaction_id") or trade.get("_id")
    if existing:
        return str(existing)
    raw = "|".join(
        str(trade.get(key) or "")
        for key in ("symbol", "trade_date", "date_time", "buy_sell", "quantity", "trade_price", "proceeds")
    )
    return sha1(raw.encode("utf-8")).hexdigest()


def normalize_trade_side(value: Any) -> str:
    side = str(value or "").strip().upper().replace(" ", "_")
    if side in BUY_SIDE_ALIASES:
        return "BUY"
    if side in SELL_SIDE_ALIASES:
        return "SELL"
    return side


class TradeReviewEvidenceBuilder:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        longbridge_client: LongbridgeExternalDataClient,
        metrics_calculator: TradeReviewMetricsCalculator | None = None,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.longbridge_client = longbridge_client
        self.metrics = metrics_calculator or TradeReviewMetricsCalculator()
        self._data_quality_lock = threading.Lock()

    def build_symbol_review_evidence(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        longbridge_symbol = normalize_longbridge_symbol(symbol)
        ibkr_symbol = normalize_ibkr_symbol(symbol)
        data_quality = {"missing_fields": [], "warnings": []}
        trades = self._fetch_symbol_trades(ibkr_symbol, start_date, end_date)
        if not trades:
            data_quality["warnings"].append("No IBKR trade records found for symbol")
        normalized_trades = [self._normalize_trade(trade) for trade in trades]
        if any(trade.get("realized_pnl") is None for trade in normalized_trades):
            data_quality["warnings"].append("Some IBKR trades do not include realized_pnl; unavailable values are kept as null")
        first_buy_date = self._first_trade_date(normalized_trades, side="BUY") or self._first_trade_date(normalized_trades)
        last_trade_date = self._last_trade_date(normalized_trades)
        current_position = self._fetch_current_position(ibkr_symbol)
        is_currently_holding = bool(current_position and abs(float(current_position.get("quantity") or 0.0)) > 0)

        today = date.today().isoformat()
        review_start = (parse_date(first_buy_date) - timedelta(days=90)).isoformat() if first_buy_date else (parse_date(start_date) or date.today() - timedelta(days=90)).isoformat()
        if end_date:
            review_end = end_date
        elif is_currently_holding:
            review_end = today
        elif last_trade_date:
            review_end = (parse_date(last_trade_date) + timedelta(days=90)).isoformat()
        else:
            review_end = today

        account_context = self._build_account_context(first_buy_date, last_trade_date or review_end)
        symbol_candles = self._fetch_candles(longbridge_symbol, review_start, review_end, data_quality)
        benchmark_context = self._build_benchmark_context(review_start, review_end, data_quality)
        latest_price = symbol_candles[-1]["close"] if symbol_candles else None
        summary = self.metrics.calculate_symbol_trade_summary(normalized_trades, current_position, latest_price)
        lifecycle_facts = self._build_trade_lifecycle_facts(normalized_trades, current_position)
        post_exit = self.metrics.calculate_post_trade_returns(symbol_candles, last_trade_date) if last_trade_date else {}
        max_move = self.metrics.calculate_max_profit_and_drawdown(
            symbol_candles,
            summary.get("avg_buy_price"),
            first_buy_date or review_start,
            last_trade_date or review_end,
        )
        news = self._fetch_news(longbridge_symbol, data_quality)

        return build_trade_review_evidence_pack({
            "review_type": "symbol_level_review",
            "objective": self._objective(),
            "symbol": longbridge_symbol,
            "account_context": account_context,
            "trade_facts": {
                "trades": normalized_trades,
                "first_buy_date": first_buy_date,
                "last_trade_date": last_trade_date,
                "current_position": current_position or {},
                **lifecycle_facts,
            },
            "performance_metrics": {
                **summary,
                "buy_count": lifecycle_facts["buy_count"],
                "sell_count": lifecycle_facts["sell_count"],
                **max_move,
                "post_exit_return_7d": post_exit.get("7d"),
                "post_exit_return_30d": post_exit.get("30d"),
                "post_exit_return_90d": post_exit.get("90d"),
            },
            "price_context": self._build_price_context(symbol_candles, summary, first_buy_date, last_trade_date),
            "benchmark_context": benchmark_context,
            "external_events": {
                "pre_entry_events": news[:10],
                "pre_exit_events": [],
                "during_holding_events": news[:10],
                "post_exit_events": [],
            },
            "data_quality": data_quality,
        })

    def build_single_trade_review_evidence(self, trade_id: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        trade = self._fetch_trade_by_id(trade_id)
        if trade is None:
            raise ValueError("Trade not found")
        normalized_trade = self._normalize_trade(trade)
        if normalized_trade.get("realized_pnl") is None:
            data_quality["warnings"].append("IBKR trade does not include realized_pnl; value is kept as null")
        symbol = str(trade.get("symbol") or "")
        longbridge_symbol = normalize_longbridge_symbol(symbol)
        trade_date = normalized_trade.get("date")
        if not trade_date:
            raise ValueError("Trade date is required for single trade review")

        trade_day = parse_date(trade_date)
        review_start = (trade_day - timedelta(days=90)).isoformat()
        review_end = min(trade_day + timedelta(days=90), date.today()).isoformat()
        related_trades = [
            self._normalize_trade(item)
            for item in self._fetch_symbol_trades(normalize_ibkr_symbol(symbol), review_start, review_end)
        ]
        current_position = self._fetch_current_position(normalize_ibkr_symbol(symbol))
        account_context = self._build_account_context(trade_date, review_end)
        symbol_candles = self._fetch_candles(longbridge_symbol, review_start, review_end, data_quality)
        benchmark_context = self._build_benchmark_context(review_start, review_end, data_quality)
        latest_price = symbol_candles[-1]["close"] if symbol_candles else None
        single_trade_summary = self.metrics.calculate_symbol_trade_summary([normalized_trade], current_position, latest_price)
        related_trade_summary = self.metrics.calculate_symbol_trade_summary(related_trades, current_position, latest_price)
        post_trade = self.metrics.calculate_post_trade_returns(symbol_candles, trade_date)
        max_move = self.metrics.calculate_max_profit_and_drawdown(
            symbol_candles,
            normalized_trade.get("price") if normalized_trade.get("side") == "BUY" else None,
            trade_date,
            review_end,
        )
        position_size = self.metrics.classify_position_size(normalized_trade.get("amount"), account_context.get("account_value_at_start"))
        news = self._fetch_news(longbridge_symbol, data_quality)
        side = str(normalized_trade.get("side") or "").upper()
        is_currently_holding = bool(current_position and abs(float(current_position.get("quantity") or 0.0)) > 0)
        subsequent_sells = [
            item
            for item in related_trades
            if item.get("side") == "SELL" and item.get("date") and str(item["date"]) >= str(trade_date)
        ]
        lifecycle_stage = self._single_trade_lifecycle_stage(side, is_currently_holding, subsequent_sells)

        return build_trade_review_evidence_pack({
            "review_type": "single_trade_review",
            "objective": self._objective(),
            "symbol": longbridge_symbol,
            "account_context": account_context,
            "trade_facts": {
                "trades": [normalized_trade],
                "related_symbol_trades": related_trades,
                "reviewed_trade_id": normalized_trade["trade_id"],
                "first_buy_date": trade_date if normalized_trade.get("side") == "BUY" else None,
                "last_trade_date": subsequent_sells[-1].get("date") if subsequent_sells else trade_date,
                "is_currently_holding": is_currently_holding,
                "lifecycle_stage": lifecycle_stage,
                "has_exit_trade_after_reviewed_trade": bool(subsequent_sells),
                "current_position": current_position or {},
                "position_size_class": position_size,
            },
            "performance_metrics": {
                "single_trade_summary": single_trade_summary,
                "related_symbol_trade_summary": related_trade_summary,
                "post_trade_return_7d": post_trade.get("7d"),
                "post_trade_return_30d": post_trade.get("30d"),
                "post_trade_return_90d": post_trade.get("90d"),
                **max_move,
            },
            "price_context": self._build_price_context(
                symbol_candles,
                {
                    "avg_buy_price": normalized_trade.get("price") if side == "BUY" else None,
                    "avg_sell_price": normalized_trade.get("price") if side == "SELL" else None,
                },
                trade_date,
                trade_date,
            ),
            "benchmark_context": benchmark_context,
            "external_events": {
                "pre_entry_events": news[:10] if normalized_trade.get("side") == "BUY" else [],
                "pre_exit_events": news[:10] if normalized_trade.get("side") == "SELL" else [],
                "during_holding_events": [],
                "post_exit_events": [],
            },
            "data_quality": data_quality,
        })

    def tool_get_symbol_trades(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> dict:
        ibkr_symbol = normalize_ibkr_symbol(symbol)
        trades = [self._normalize_trade(trade) for trade in self._fetch_symbol_trades(ibkr_symbol, start_date, end_date)]
        return {
            "source": "IBKR",
            "symbol": normalize_longbridge_symbol(symbol),
            "trades": trades,
            **self._build_trade_lifecycle_facts(trades, None),
        }

    def tool_get_single_trade(self, trade_id: str) -> dict:
        trade = self._fetch_trade_by_id(trade_id)
        if trade is None:
            raise ValueError("Trade not found")
        return {"source": "IBKR", "trade": self._normalize_trade(trade), "symbol": normalize_longbridge_symbol(str(trade.get("symbol") or ""))}

    def tool_get_single_trade_review_context(self, trade_id: str) -> dict:
        context = self.build_single_trade_review_evidence(trade_id)
        return {
            "source": "IBKR + Longbridge",
            "trade_id": trade_id,
            "review_context": context,
        }

    def tool_get_current_position(self, symbol: str) -> dict:
        return {"source": "IBKR", "symbol": normalize_longbridge_symbol(symbol), "position": self._fetch_current_position(normalize_ibkr_symbol(symbol)) or {}}

    def tool_get_account_context(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        return {"source": "IBKR", **self._build_account_context(start_date, end_date)}

    def tool_get_price_context(self, symbol: str, start: str, end: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        candles = self._fetch_candles(normalize_longbridge_symbol(symbol), start, end, data_quality)
        return {
            "source": "Longbridge public market data",
            "symbol": normalize_longbridge_symbol(symbol),
            "start": start,
            "end": end,
            "price_context": self._build_price_context(candles, {}, None, None),
            "data_quality": data_quality,
        }

    def tool_get_benchmark_context(self, start: str, end: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        return {
            "source": "Longbridge public benchmark data",
            "start": start,
            "end": end,
            "benchmark_context": self._build_benchmark_context(start, end, data_quality),
            "data_quality": data_quality,
        }

    def tool_get_symbol_news(self, symbol: str, limit: int = 10) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        news = self._fetch_news(normalize_longbridge_symbol(symbol), data_quality)[: max(1, min(int(limit), 20))]
        return {"source": "Longbridge public news", "symbol": normalize_longbridge_symbol(symbol), "news": news, "data_quality": data_quality}

    def tool_get_macro_news(self, keyword: str = "macro economy", limit: int = 10) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        try:
            response = self.longbridge_client.search_macro_news(keyword=keyword, limit=max(1, min(int(limit), 20)))
            return {"source": "Longbridge macro news search", "keyword": response.keyword, "news": [item.model_dump() for item in response.items], "data_quality": data_quality}
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            data_quality["warnings"].append(f"Longbridge macro news unavailable: {exc}")
            return {"source": "Longbridge macro news search", "keyword": keyword, "news": [], "data_quality": data_quality}

    def _objective(self) -> dict:
        return {
            "target_annual_return": TARGET_ANNUAL_RETURN,
            "style": "aggressive_growth",
            "goal": "maximize_long_term_account_return",
        }

    def _fetch_symbol_trades(self, symbol: str, start_date: str | None, end_date: str | None) -> list[dict]:
        should_terms = [{"term": {"symbol": value}} for value in self._symbol_variants(symbol)]
        filters: list[dict] = [{"bool": {"should": should_terms, "minimum_should_match": 1}}]
        if start_date or end_date:
            range_query = {}
            if start_date:
                range_query["gte"] = start_date
            if end_date:
                range_query["lte"] = end_date
            filters.append({"range": {"trade_date": range_query}})
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {"bool": {"filter": filters}},
                "sort": [{"trade_date": {"order": "asc"}}, {"date_time": {"order": "asc", "missing": "_last"}}],
                "size": 1000,
                "_source": True,
            },
        )
        return [self._with_id(hit) for hit in response.get("hits", {}).get("hits", [])]

    def _fetch_trade_by_id(self, trade_id: str) -> dict | None:
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"trade_id": trade_id}},
                            {"term": {"transaction_id": trade_id}},
                            {"ids": {"values": [trade_id]}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "size": 1,
                "_source": True,
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return self._with_id(hits[0]) if hits else None

    def _fetch_current_position(self, symbol: str) -> dict | None:
        latest = self._latest_account_date()
        if not latest:
            return None
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}, {"terms": {"symbol": self._symbol_variants(symbol)}}]}},
                "size": 1,
                "_source": [
                    "account_id",
                    "report_date",
                    "symbol",
                    "quantity",
                    "mark_price",
                    "position_value",
                    "percent_of_nav",
                    "average_cost_price",
                    "cost_basis_money",
                    "total_realized_pnl",
                    "total_unrealized_pnl",
                ],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _build_account_context(self, start_date: str | None, end_date: str | None) -> dict:
        return {
            "account_value_at_start": self._account_value_near(start_date, direction="after"),
            "account_value_at_end": self._account_value_near(end_date, direction="before"),
            "cash_ratio_at_start": self._cash_ratio_near(start_date),
            "margin_info": None,
        }

    def _fetch_candles(self, symbol: str, start: str, end: str, data_quality: dict) -> list[dict]:
        try:
            response = self.longbridge_client.get_candles(symbol=symbol, start=start, end=end, period="day", adjust_type="forward")
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge candles unavailable for {symbol}: {exc}")
            return []

    def _build_benchmark_context(self, start: str, end: str, data_quality: dict) -> dict:
        results: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(DEFAULT_BENCHMARKS)) as executor:
            futures = {executor.submit(self._fetch_candles, b, start, end, data_quality): b for b in DEFAULT_BENCHMARKS}
            for future in as_completed(futures):
                benchmark = futures[future]
                try:
                    results[benchmark] = future.result()
                except Exception:
                    results[benchmark] = []
        context = {benchmark: {"period_return": self.metrics.calculate_benchmark_return(results.get(benchmark, []), start, end)} for benchmark in DEFAULT_BENCHMARKS}
        return context

    def _fetch_news(self, symbol: str, data_quality: dict) -> list[dict]:
        try:
            response = self.longbridge_client.get_news(symbol=symbol, limit=20)
            with self._data_quality_lock:
                data_quality["warnings"].append("Longbridge news API may not provide complete historical news range")
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge news unavailable for {symbol}: {exc}")
            return []

    def _build_price_context(self, candles: list[dict], summary: dict, first_buy_date: str | None, last_sell_date: str | None) -> dict:
        highs = [item.get("high") for item in candles if item.get("high") is not None]
        lows = [item.get("low") for item in candles if item.get("low") is not None]
        return {
            "symbol_candles": candles,
            "price_at_first_buy": summary.get("avg_buy_price"),
            "price_at_last_sell": summary.get("avg_sell_price"),
            "period_high": max(highs) if highs else None,
            "period_low": min(lows) if lows else None,
        }

    def _account_value_near(self, raw_date: str | None, direction: str) -> float | None:
        if not raw_date:
            return None
        operator = "gte" if direction == "after" else "lte"
        order = "asc" if direction == "after" else "desc"
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [{"range": {"report_date": {operator: raw_date}}}]}},
                "sort": [{"report_date": {"order": order}}],
                "size": 1,
                "_source": ["total_equity"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        value = hits[0].get("_source", {}).get("total_equity")
        return float(value) if value is not None else None

    def _cash_ratio_near(self, raw_date: str | None) -> float | None:
        if not raw_date:
            return None
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [{"range": {"report_date": {"gte": raw_date}}}]}},
                "sort": [{"report_date": {"order": "asc"}}],
                "size": 1,
                "_source": ["cash", "total_equity"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        source = hits[0].get("_source", {})
        cash = source.get("cash")
        total_equity = source.get("total_equity")
        return float(cash) / float(total_equity) if cash is not None and total_equity else None

    def _latest_account_date(self) -> str | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={"size": 1, "sort": [{"report_date": {"order": "desc"}}], "_source": ["report_date"]},
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}).get("report_date") if hits else None

    def _first_trade_date(self, trades: list[dict], side: str | None = None) -> str | None:
        for trade in trades:
            if side is None or trade.get("side") == side:
                return trade.get("date")
        return None

    def _last_trade_date(self, trades: list[dict]) -> str | None:
        return trades[-1].get("date") if trades else None

    def _normalize_trade(self, trade: dict) -> dict:
        side = normalize_trade_side(trade.get("buy_sell"))
        quantity = trade.get("quantity")
        price = trade.get("trade_price")
        proceeds = trade.get("proceeds")
        amount = abs(float(proceeds)) if proceeds is not None else (abs(float(quantity or 0.0)) * float(price or 0.0))
        realized_pnl = trade.get("fifo_pnl_realized")
        if realized_pnl is None:
            realized_pnl = None
        return {
            "trade_id": build_stable_trade_id(trade),
            "date": trade.get("trade_date") or (str(trade.get("date_time"))[:10] if trade.get("date_time") else None),
            "side": side,
            "quantity": abs(float(quantity)) if quantity is not None else None,
            "price": float(price) if price is not None else None,
            "amount": amount,
            "commission": abs(float(trade.get("ib_commission") or 0.0)),
            "currency": trade.get("currency"),
            "realized_pnl": float(realized_pnl) if realized_pnl is not None else None,
        }

    def _build_trade_lifecycle_facts(self, trades: list[dict], current_position: dict | None) -> dict:
        buy_count = sum(1 for trade in trades if normalize_trade_side(trade.get("side")) == "BUY")
        sell_count = sum(1 for trade in trades if normalize_trade_side(trade.get("side")) == "SELL")
        latest_trade = trades[-1] if trades else {}
        latest_trade_side = normalize_trade_side(latest_trade.get("side")) if latest_trade else None
        latest_trade_date = latest_trade.get("date") if latest_trade else None
        is_currently_holding = bool(current_position and abs(float(current_position.get("quantity") or 0.0)) > 0)

        seen_sell = False
        has_reopened_position_after_sell = False
        for trade in trades:
            side = normalize_trade_side(trade.get("side"))
            if side == "SELL":
                seen_sell = True
            elif side == "BUY" and seen_sell:
                has_reopened_position_after_sell = True
                break

        return {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "has_buy_trades": buy_count > 0,
            "has_sell_trades": sell_count > 0,
            "is_round_trip": buy_count > 0 and sell_count > 0,
            "is_currently_holding": is_currently_holding,
            "has_reopened_position_after_sell": has_reopened_position_after_sell,
            "latest_trade_side": latest_trade_side,
            "latest_trade_date": latest_trade_date,
        }

    def _single_trade_lifecycle_stage(
        self,
        side: str,
        is_currently_holding: bool,
        subsequent_sells: list[dict],
    ) -> str:
        if side == "BUY" and is_currently_holding and not subsequent_sells:
            return "entry_only_open_position"
        if side == "BUY" and subsequent_sells:
            return "entry_with_later_exit"
        if side == "BUY":
            return "entry_without_detected_position"
        if side == "SELL":
            return "exit_trade"
        return "unknown"

    def _with_id(self, hit: dict) -> dict:
        source = dict(hit.get("_source", {}))
        source["_id"] = hit.get("_id")
        return source

    def _symbol_variants(self, symbol: str) -> list[str]:
        base = normalize_ibkr_symbol(symbol)
        variants = [base, f"{base}.US", f"US.{base}"]
        return list(dict.fromkeys(variants))
