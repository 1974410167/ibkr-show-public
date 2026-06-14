"""
AccountFactBuilder - builds AccountFactSnapshot from IBKR data only.

Does NOT call MCP, does NOT call Longbridge.
Replaces the account/position/trade/review context logic from the old evidence builder.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.agents.trade_decision_cards import AccountFactSnapshot
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.services.trade_decision_metrics import TradeDecisionMetricsCalculator, to_float
from app.services.trade_decision_evidence import TradeDecisionEvidenceBuilder, normalize_ibkr_symbol
from app.services.trade_review_evidence import DEFAULT_BENCHMARKS, build_stable_trade_id, normalize_longbridge_symbol as review_normalize_lb
from app.utils.dates import parse_date


CASH_EQUIVALENT_SYMBOLS = {"SGOV", "STRC", "BIL", "SHV", "USFR", "TFLO", "BOXX"}


def _is_cash_equivalent(symbol: str) -> bool:
    normalized = str(symbol or "").upper().split(".", 1)[0]
    return normalized in CASH_EQUIVALENT_SYMBOLS


def _nav_percent_to_ratio(value: object) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return round(number / 100.0 if abs(number) > 1 else number, 6)


class TradeDecisionAccountFactsBuilder:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        metrics_calculator: TradeDecisionMetricsCalculator | None = None,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.metrics = metrics_calculator or TradeDecisionMetricsCalculator()

    def build(self, decision_type: str, symbol: str, user_question: str | None = None) -> AccountFactSnapshot:
        """
        Build a complete AccountFactSnapshot from IBKR data.
        decision_type: "trade_decision" | "entry_decision" | "holding_decision"
        symbol: normalized symbol like "AAPL.US"
        """
        ibkr_symbol = normalize_ibkr_symbol(symbol)
        normalized_symbol = normalize_longbridge_symbol_for_account(symbol)

        # Fetch all data in parallel where possible
        position = self._fetch_current_position(ibkr_symbol)
        trade_limit = 50 if decision_type in {"trade_decision", "holding_decision"} else 20
        trades = self._fetch_symbol_trades(ibkr_symbol, limit=trade_limit)
        account_context = self._build_account_context()
        position_context = self._build_position_context(position)
        trade_history_context = self._build_trade_history_context(trades)
        review_context = self._build_review_context(normalized_symbol)

        return AccountFactSnapshot(
            decision_type=decision_type,
            symbol=normalized_symbol,
            normalized_symbol=normalized_symbol,
            user_question=user_question,
            # Account
            net_liquidation=account_context.get("net_liquidation"),
            cash=account_context.get("cash"),
            deployable_liquidity=account_context.get("deployable_liquidity"),
            deployable_liquidity_ratio=account_context.get("deployable_liquidity_ratio"),
            total_position_value=account_context.get("total_position_value"),
            top_positions=account_context.get("top_positions", []),
            position_concentration=account_context.get("position_concentration"),
            risk_concentration=account_context.get("risk_position_concentration_ex_cash_equivalents"),
            margin_info=account_context.get("margin_info"),
            # Position
            is_holding=position_context.get("is_holding", False),
            quantity=position_context.get("quantity"),
            avg_cost=position_context.get("avg_cost"),
            current_price=position_context.get("current_price"),
            market_value=position_context.get("market_value"),
            position_pct=position_context.get("position_pct"),
            unrealized_pnl=position_context.get("unrealized_pnl"),
            unrealized_pnl_pct=position_context.get("unrealized_pnl_pct"),
            realized_pnl=position_context.get("realized_pnl"),
            # Trade history
            recent_trades=trade_history_context.get("recent_trades", []),
            first_buy_date=trade_history_context.get("first_buy_date"),
            last_trade_date=trade_history_context.get("last_trade_date"),
            holding_days=trade_history_context.get("holding_days"),
            # Review
            latest_review=review_context.get("symbol_latest_review"),
            global_mistake_tags=review_context.get("global_mistake_summary", []),
            data_quality={"warnings": [], "missing_fields": []},
        )

    def _build_account_context(self) -> dict:
        account = self._latest_account_snapshot()
        positions = self._latest_positions(limit=20)
        net_liquidation = to_float(account.get("total_equity")) if account else None
        cash = to_float(account.get("cash")) if account else None
        total_position_value = sum(abs(to_float(item.get("position_value")) or 0.0) for item in positions)
        cash_equivalent_positions = [item for item in positions if _is_cash_equivalent(item.get("symbol"))]
        cash_equivalents_value = round(sum(abs(item.get("position_value") or 0.0) for item in cash_equivalent_positions), 4)
        deployable_liquidity = round((cash or 0.0) + cash_equivalents_value, 4)
        top_positions = [
            {
                "symbol": item.get("symbol"),
                "position_value": to_float(item.get("position_value")),
                "position_pct": _nav_percent_to_ratio(item.get("percent_of_nav")),
            }
            for item in positions[:5]
        ]
        concentration = sum(item.get("position_pct") or 0.0 for item in top_positions[:3])
        risk_positions = [item for item in positions if not _is_cash_equivalent(item.get("symbol"))]
        risk_concentration = sum(_nav_percent_to_ratio(item.get("percent_of_nav")) or 0.0 for item in risk_positions[:3])
        return {
            "net_liquidation": net_liquidation,
            "cash": cash,
            "deployable_liquidity": deployable_liquidity,
            "deployable_liquidity_ratio": self.metrics.calculate_cash_ratio(deployable_liquidity, net_liquidation) if net_liquidation else None,
            "total_position_value": round(total_position_value, 4),
            "top_positions": top_positions,
            "position_concentration": round(concentration, 6),
            "risk_position_concentration_ex_cash_equivalents": round(risk_concentration, 6),
            "margin_info": None,
        }

    def _build_position_context(self, position: dict | None) -> dict:
        if not position:
            return {
                "is_holding": False,
                "quantity": 0.0,
                "avg_cost": None,
                "current_price": None,
                "market_value": 0.0,
                "position_pct": 0.0,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": None,
                "realized_pnl": None,
            }
        position_pct = _nav_percent_to_ratio(position.get("percent_of_nav"))
        unrealized = to_float(position.get("total_unrealized_pnl"))
        cost_basis = to_float(position.get("cost_basis_money"))
        return {
            "is_holding": abs(to_float(position.get("quantity")) or 0.0) > 0,
            "quantity": to_float(position.get("quantity")),
            "avg_cost": to_float(position.get("average_cost_price")),
            "current_price": to_float(position.get("mark_price")),
            "market_value": to_float(position.get("position_value")),
            "position_pct": position_pct,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": self._ratio_from_percent_or_cost(position) or self.metrics.calculate_unrealized_pnl_pct(unrealized, cost_basis),
            "realized_pnl": to_float(position.get("total_realized_pnl")),
        }

    def _build_trade_history_context(self, trades: list[dict]) -> dict:
        normalized = [self._normalize_trade(item) for item in trades]
        dates = [item.get("date") for item in normalized if item.get("date")]
        first_buy = next((item.get("date") for item in normalized if item.get("side") == "BUY" and item.get("date")), None)
        last_trade = dates[-1] if dates else None
        holding_days = None
        if first_buy and last_trade:
            first_date = parse_date(first_buy)
            last_date = parse_date(last_trade)
            holding_days = (last_date - first_date).days if first_date and last_date else None
        return {
            "recent_trades": normalized[-20:],
            "first_buy_date": first_buy,
            "last_trade_date": last_trade,
            "holding_days": holding_days,
        }

    def _build_review_context(self, symbol: str) -> dict:
        latest_review = self._latest_symbol_review(symbol)
        return {
            "symbol_latest_review": latest_review,
            "symbol_mistake_tags": latest_review.get("mistake_tags", []) if latest_review else [],
            "global_mistake_summary": self._global_mistake_summary(),
        }

    def _latest_account_snapshot(self) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_account_index,
                body={
                    "size": 1,
                    "sort": [{"report_date": {"order": "desc"}}],
                    "_source": ["account_id", "report_date", "currency", "total_equity", "cash"],
                },
            )
            hits = response.get("hits", {}).get("hits", [])
            return hits[0].get("_source", {}) if hits else None
        except ESIndexNotFoundError:
            return None

    def _latest_account_date(self) -> str | None:
        account = self._latest_account_snapshot()
        return account.get("report_date") if account else None

    def _latest_positions(self, limit: int = 500) -> list[dict]:
        latest = self._latest_account_date()
        if not latest:
            return []
        try:
            response = self.es_client.search(
                index=self.settings.es_position_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                    "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                    "size": limit,
                    "_source": ["symbol", "position_value", "percent_of_nav"],
                },
            )
            return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        except ESIndexNotFoundError:
            return []

    def _fetch_current_position(self, symbol: str) -> dict | None:
        latest = self._latest_account_date()
        if not latest:
            return None
        try:
            response = self.es_client.search(
                index=self.settings.es_position_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"report_date": latest}}, {"terms": {"symbol": self._symbol_variants(symbol)}}]}},
                    "size": 1,
                    "_source": True,
                },
            )
            hits = response.get("hits", {}).get("hits", [])
            return hits[0].get("_source", {}) if hits else None
        except ESIndexNotFoundError:
            return None

    def _fetch_symbol_trades(self, symbol: str, limit: int) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_index,
                body={
                    "query": {"bool": {"filter": [{"terms": {"symbol": self._symbol_variants(symbol)}}]}},
                    "sort": [{"trade_date": {"order": "asc"}}, {"date_time": {"order": "asc", "missing": "_last"}}],
                    "size": limit,
                    "_source": True,
                },
            )
            return [self._with_id(hit) for hit in response.get("hits", {}).get("hits", [])]
        except ESIndexNotFoundError:
            return []

    def _latest_symbol_review(self, symbol: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_review_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"symbol": normalize_longbridge_symbol_for_account(symbol)}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": 1,
                    "_source": ["id", "overall_score", "rating", "summary", "mistake_tags", "created_at"],
                },
            )
        except ESIndexNotFoundError:
            return None
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _latest_symbol_decision(self, symbol: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"symbol": normalize_longbridge_symbol_for_account(symbol)}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": 1,
                    "_source": ["id", "action", "overall_score", "created_at"],
                },
            )
        except ESIndexNotFoundError:
            return None
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _latest_symbol_reviews(self, symbols: list[str]) -> dict[str, dict]:
        normalized_symbols = list(dict.fromkeys(normalize_longbridge_symbol_for_account(symbol) for symbol in symbols if symbol))
        if not normalized_symbols:
            return {}
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_review_index,
                body={
                    "size": 0,
                    "query": {"bool": {"filter": [{"terms": {"symbol": normalized_symbols}}]}},
                    "aggs": {
                        "by_symbol": {
                            "terms": {"field": "symbol", "size": len(normalized_symbols)},
                            "aggs": {
                                "latest": {
                                    "top_hits": {
                                        "sort": [{"created_at": {"order": "desc"}}],
                                        "size": 1,
                                        "_source": ["id", "overall_score", "rating", "summary", "mistake_tags", "created_at"],
                                    }
                                }
                            },
                        }
                    },
                },
            )
        except ESIndexNotFoundError:
            return {}
        buckets = response.get("aggregations", {}).get("by_symbol", {}).get("buckets", [])
        results: dict[str, dict] = {}
        for bucket in buckets:
            hits = bucket.get("latest", {}).get("hits", {}).get("hits", [])
            if hits:
                results[str(bucket.get("key"))] = hits[0].get("_source", {})
        return results

    def _latest_symbol_decisions(self, symbols: list[str]) -> dict[str, dict]:
        normalized_symbols = list(dict.fromkeys(normalize_longbridge_symbol_for_account(symbol) for symbol in symbols if symbol))
        if not normalized_symbols:
            return {}
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "size": 0,
                    "query": {"bool": {"filter": [{"terms": {"symbol": normalized_symbols}}]}},
                    "aggs": {
                        "by_symbol": {
                            "terms": {"field": "symbol", "size": len(normalized_symbols)},
                            "aggs": {
                                "latest": {
                                    "top_hits": {
                                        "sort": [{"created_at": {"order": "desc"}}],
                                        "size": 1,
                                        "_source": ["id", "action", "overall_score", "created_at"],
                                    }
                                }
                            },
                        }
                    },
                },
            )
        except ESIndexNotFoundError:
            return {}
        buckets = response.get("aggregations", {}).get("by_symbol", {}).get("buckets", [])
        results: dict[str, dict] = {}
        for bucket in buckets:
            hits = bucket.get("latest", {}).get("hits", {}).get("hits", [])
            if hits:
                results[str(bucket.get("key"))] = hits[0].get("_source", {})
        return results

    def _global_mistake_summary(self) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_review_index,
                body={"size": 0, "aggs": {"mistakes": {"terms": {"field": "mistake_tags", "size": 20}}}},
            )
        except ESIndexNotFoundError:
            return []
        return [
            {"tag": bucket.get("key"), "count": bucket.get("doc_count", 0)}
            for bucket in response.get("aggregations", {}).get("mistakes", {}).get("buckets", [])
        ]

    def _normalize_trade(self, trade: dict) -> dict:
        side = str(trade.get("buy_sell") or "").upper()
        return {
            "trade_id": build_stable_trade_id(trade),
            "date": trade.get("trade_date") or (str(trade.get("date_time"))[:10] if trade.get("date_time") else None),
            "side": side,
            "quantity": abs(to_float(trade.get("quantity")) or 0.0),
            "price": to_float(trade.get("trade_price")),
            "amount": abs(to_float(trade.get("proceeds")) or 0.0),
            "commission": abs(to_float(trade.get("ib_commission")) or 0.0),
            "currency": trade.get("currency"),
            "realized_pnl": to_float(trade.get("fifo_pnl_realized")),
        }

    def _with_id(self, hit: dict) -> dict:
        source = dict(hit.get("_source", {}))
        source["_id"] = hit.get("_id")
        return source

    def _symbol_variants(self, symbol: str) -> list[str]:
        base = normalize_ibkr_symbol(symbol)
        return list(dict.fromkeys([base, f"{base}.US", f"US.{base}"]))

    def _ratio_from_percent_or_cost(self, source: dict) -> float | None:
        percent = to_float(source.get("unrealized_pnl_percent"))
        if percent is not None:
            return round(percent / 100.0 if abs(percent) > 1 else percent, 6)
        return self.metrics.calculate_unrealized_pnl_pct(
            to_float(source.get("total_unrealized_pnl")),
            to_float(source.get("cost_basis_money"))
        )

    def list_current_holdings(self) -> list[dict]:
        """Return current holdings for the /holdings endpoint."""
        latest = self._latest_account_date()
        if not latest:
            return []
        try:
            response = self.es_client.search(
                index=self.settings.es_position_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                    "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                    "size": 500,
                    "_source": [
                        "symbol", "quantity", "mark_price", "position_value",
                        "percent_of_nav", "average_cost_price", "cost_basis_money",
                        "total_unrealized_pnl", "unrealized_pnl_percent",
                    ],
                },
            )
        except ESIndexNotFoundError:
            return []

        position_hits = response.get("hits", {}).get("hits", [])
        normalized_by_symbol: dict[str, str] = {}
        for hit in position_hits:
            source = hit.get("_source", {})
            symbol = source.get("symbol")
            if symbol:
                normalized_by_symbol[str(symbol)] = normalize_longbridge_symbol_for_account(symbol)

        latest_reviews = self._latest_symbol_reviews(list(normalized_by_symbol.values()))
        latest_decisions = self._latest_symbol_decisions(list(normalized_by_symbol.values()))

        holdings = []
        for hit in position_hits:
            source = hit.get("_source", {})
            symbol = source.get("symbol")
            if not symbol:
                continue
            normalized = normalized_by_symbol.get(str(symbol)) or normalize_longbridge_symbol_for_account(symbol)
            latest_review = latest_reviews.get(normalized)
            latest_decision = latest_decisions.get(normalized)
            position_pct = _nav_percent_to_ratio(source.get("percent_of_nav"))
            holdings.append({
                "symbol": symbol,
                "normalized_symbol": normalized,
                "quantity": to_float(source.get("quantity")),
                "avg_cost": to_float(source.get("average_cost_price")),
                "current_price": to_float(source.get("mark_price")),
                "market_value": to_float(source.get("position_value")),
                "position_pct": position_pct,
                "unrealized_pnl": to_float(source.get("total_unrealized_pnl")),
                "unrealized_pnl_pct": self._ratio_from_percent_or_cost(source),
                "latest_review_score": latest_review.get("overall_score") if latest_review else None,
                "latest_decision": latest_decision.get("action") if latest_decision else None,
                "data_source": "IBKR",
            })
        return holdings


def normalize_longbridge_symbol_for_account(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if "." not in normalized:
        normalized = f"{normalized}.US"
    return normalized
