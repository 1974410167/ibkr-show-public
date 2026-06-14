from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import threading
from typing import Any

from app.schemas.symbol_analysis import (
    FinancialField,
    FinancialPeriod,
    MetricComparisonItem,
    SymbolAiAdviceResponse,
    SymbolComparisonResponse,
    SymbolFinancialsResponse,
    SymbolMarketSnapshot,
)
from app.services.llm_service import LLMService
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, normalize_longbridge_symbol

STATEMENT_KINDS = ("IS", "BS", "CF")
CORE_METRICS = [
    ("revenue", "营收", True),
    ("gross_profit", "毛利润", True),
    ("gross_margin", "毛利率", True),
    ("operating_income", "营业利润", True),
    ("operating_margin", "营业利润率", True),
    ("net_income", "净利润", True),
    ("net_margin", "净利率", True),
    ("eps", "EPS", True),
    ("operating_cash_flow", "经营现金流", True),
    ("free_cash_flow", "自由现金流", True),
    ("cash_and_equivalents", "现金及短投", True),
    ("total_debt", "总债务", False),
    ("shareholders_equity", "股东权益", True),
    ("roe", "ROE", True),
]

METRIC_ALIASES = {
    "revenue": ("revenue", "total revenue", "operating revenue", "sales", "营业收入", "总营收", "总营业收入", "主营业务收入"),
    "gross_profit": ("gross profit", "毛利", "毛利润"),
    "operating_income": ("operating income", "operating profit", "income from operations", "营业利润"),
    "net_income": ("net income", "net profit", "net income attributable", "归母净利润", "净利润", "归属公司的净利润", "归属母公司净利润"),
    "eps": ("basic eps", "diluted eps", "earnings per share", "eps", "每股收益"),
    "operating_cash_flow": ("operating cash flow", "net cash provided by operating", "cash flow from operating", "经营活动现金流"),
    "free_cash_flow": ("free cash flow", "自由现金流"),
    "capital_expenditure": ("capital expenditure", "capital expenditures", "purchase of property", "资本开支", "资本支出"),
    "cash_and_equivalents": ("cash and cash equivalents", "cash equivalents", "货币资金", "现金及等价物", "现金及现金等价物"),
    "total_debt": ("total debt", "short term debt", "long term debt", "总债务", "有息负债"),
    "shareholders_equity": ("total equity", "shareholders equity", "stockholders equity", "股东权益", "所有者权益", "普通股权益总计"),
}

REPORT_FIELD_METRICS = {
    "revenue": "revenue",
    "operatingrevenue": "revenue",
    "totalrevenue": "revenue",
    "grossprofit": "gross_profit",
    "grossmargin": "gross_margin",
    "grossprofitmargin": "gross_margin",
    "operatingincome": "operating_income",
    "operatingprofit": "operating_income",
    "operatingmargin": "operating_margin",
    "operatingprofitmargin": "operating_margin",
    "netincome": "net_income",
    "netprofit": "net_income",
    "netmargin": "net_margin",
    "netprofitmargin": "net_margin",
    "eps": "eps",
    "operatingcashflow": "operating_cash_flow",
    "freecashflow": "free_cash_flow",
    "cashandcashequivalents": "cash_and_equivalents",
    "cashequivalents": "cash_and_equivalents",
    "cashstinvest": "cash_and_equivalents",
    "totaldebt": "total_debt",
    "netdebt": "net_debt",
    "totalassets": "total_assets",
    "totalliability": "total_liability",
    "shareholdersequity": "shareholders_equity",
    "stockholdersequity": "shareholders_equity",
    "totalequity": "shareholders_equity",
    "roe": "roe",
}

REPORT_METRIC_ALIASES = {
    "revenue": ("revenue", "operatingrevenue", "营业收入", "总营业收入"),
    "gross_margin": ("grossmargin", "grossprofitmargin", "毛利率"),
    "gross_profit": ("grossprofit", "毛利润"),
    "operating_margin": ("operatingmargin", "operatingprofitmargin", "营业利润率"),
    "operating_income": ("operatingincome", "operatingprofit", "营业利润"),
    "net_margin": ("netmargin", "netprofitmargin", "净利率"),
    "net_income": ("netincome", "netprofit", "归属公司的净利润", "归母净利润", "净利润"),
    "eps": ("eps", "每股收益"),
    "operating_cash_flow": ("operatingcashflow", "cashflowfromoperating", "经营活动现金流", "经营现金流"),
    "free_cash_flow": ("freecashflow", "自由现金流"),
    "cash_and_equivalents": ("cashandcashequivalents", "cashequivalents", "cashstinvest", "现金及现金等价物", "现金及等价物", "现金及短期投资"),
    "total_debt": ("totaldebt", "总债务", "有息负债"),
    "net_debt": ("netdebt", "净债务"),
    "total_assets": ("totalassets", "总资产"),
    "total_liability": ("totalliability", "总负债"),
    "shareholders_equity": ("shareholdersequity", "stockholdersequity", "totalequity", "所有者权益", "股东权益"),
    "roe": ("roe", "净资产收益率"),
}

PERCENT_REPORT_METRICS = {"gross_margin", "operating_margin", "net_margin", "roe"}

METRIC_FIELD_IDS = {
    "revenue": {"1", "1100"},
    "gross_profit": {"2"},
    "operating_income": {"5"},
    "net_income": {"43", "44"},
    "operating_cash_flow": {"159"},
    "capital_expenditure": {"160"},
    "cash_and_equivalents": {"51"},
    "shareholders_equity": {"128", "126"},
}


class SymbolAnalysisService:
    def __init__(self, longbridge_client: LongbridgeExternalDataClient, llm_service: LLMService) -> None:
        self.longbridge_client = longbridge_client
        self.llm_service = llm_service
        self._data_quality_lock = threading.Lock()

    def get_financials(self, symbol: str, periods: int = 8, report: str = "qf") -> SymbolFinancialsResponse:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        market_snapshot = self.get_market_snapshot(normalized_symbol)
        try:
            report_payload = self.longbridge_client.get_financial_report(normalized_symbol, kind="ALL", report=report)
            financials = self._build_financials_from_report(normalized_symbol, report_payload, periods=periods, report=report)
            if financials.periods:
                financials.market_snapshot = market_snapshot
                return financials
        except (AttributeError, LongbridgeExternalDataError):
            pass

        statement_payloads: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=len(STATEMENT_KINDS)) as executor:
            futures = {
                executor.submit(self.longbridge_client.get_financial_statement, normalized_symbol, kind=kind, report=report): kind
                for kind in STATEMENT_KINDS
            }
            for future in as_completed(futures):
                kind = futures[future]
                try:
                    statement_payloads[kind] = future.result()
                except (AttributeError, LongbridgeExternalDataError):
                    statement_payloads[kind] = {}
        currency = next((str(payload.get("currency")) for payload in statement_payloads.values() if payload.get("currency")), None)
        period_map: dict[str, FinancialPeriod] = {}

        for kind, payload in statement_payloads.items():
            for raw_period in list(payload.get("list") or [])[:periods]:
                if not isinstance(raw_period, dict):
                    continue
                key = self._period_key(raw_period, report)
                period = period_map.get(key)
                if period is None:
                    period = FinancialPeriod(
                        label=self._period_label(raw_period, report),
                        fiscal_year=self._to_int(raw_period.get("ff_year")),
                        fiscal_period=self._period_value(raw_period),
                        report_type=report,
                    )
                    period_map[key] = period
                period.statements[kind] = self._normalize_fields(raw_period.get("fields") or [])

        ordered_periods = list(period_map.values())[:periods]
        for period in ordered_periods:
            period.metrics = self._build_core_metrics(period.statements)

        return SymbolFinancialsResponse(
            symbol=normalized_symbol,
            currency=currency,
            report_type=report,
            period_count=len(ordered_periods),
            periods=ordered_periods,
            market_snapshot=market_snapshot,
        )

    def get_market_snapshot(self, symbol: str) -> SymbolMarketSnapshot | None:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self.longbridge_client.get_quote_snapshot, normalized_symbol): "quote",
                executor.submit(self.longbridge_client.get_static_info, normalized_symbol): "static",
                executor.submit(self.longbridge_client.get_calc_indexes, normalized_symbol): "calc",
                executor.submit(self.longbridge_client.get_valuation_detail, normalized_symbol): "valuation",
                executor.submit(self.longbridge_client.get_forecast_eps, normalized_symbol): "forecast_eps",
            }
            for future in as_completed(futures):
                label = futures[future]
                try:
                    results[label] = future.result()
                except (AttributeError, LongbridgeExternalDataError):
                    results[label] = {} if label in ("valuation", "forecast_eps") else {}

        quote = results.get("quote", {})
        static = results.get("static", {})
        calc = results.get("calc", {})
        valuation = results.get("valuation", {})
        forecast_eps_payload = results.get("forecast_eps", {})

        valuation_overview = valuation.get("overview") if isinstance(valuation.get("overview"), dict) else {}
        valuation_pe = {}
        if isinstance(valuation_overview.get("metrics"), dict):
            raw_pe = valuation_overview["metrics"].get("pe")
            if isinstance(raw_pe, dict):
                valuation_pe = raw_pe
        history_metrics = (valuation.get("history") or {}).get("metrics") if isinstance(valuation.get("history"), dict) else {}
        history_pe = history_metrics.get("pe") if isinstance(history_metrics, dict) and isinstance(history_metrics.get("pe"), dict) else {}
        valuation_stock = self._valuation_stock(valuation, normalized_symbol)
        last_price = self._first_number(quote, "last", "last_done", "price") or self._number_from_metric(valuation_pe.get("circle"))
        prev_close = self._first_number(quote, "prev_close")
        change_percent = self._first_number(quote, "change_percentage", "change_rate", "change_percent")
        if change_percent is None and last_price is not None and prev_close:
            change_percent = round((last_price - prev_close) / abs(prev_close) * 100, 6)
        forward_eps = self._latest_forecast_eps(forecast_eps_payload)
        forward_pe = round(last_price / forward_eps, 4) if last_price is not None and forward_eps and forward_eps > 0 else None

        return SymbolMarketSnapshot(
            symbol=normalized_symbol,
            name=self._first_text(static, valuation_stock, "name", "stock_name"),
            currency=self._first_text(static, "currency"),
            last_price=last_price,
            change_percent=change_percent,
            market_cap=self._first_number(calc, "mktcap", "total_market_value", "market_cap")
            or self._first_number(valuation_stock, "market_cap"),
            pe_ttm=self._first_number(calc, "pe", "pe_ttm_ratio", "pe_ttm") or self._number_from_metric(valuation_pe.get("metric")),
            forward_pe=forward_pe,
            pe_3y_median=self._first_number(history_pe, "median"),
            pe_industry_median=self._first_number(valuation_pe, "industry_median")
            or self._number_from_metric(((valuation.get("peers") or {}).get("pe") or {}).get("industry_median") if isinstance(valuation.get("peers"), dict) else None),
            pb=self._first_number(calc, "pb", "pb_ratio"),
            dividend_yield=self._first_number(calc, "dps_rate", "dividend_ratio_ttm"),
            turnover_rate=self._first_number(calc, "turnover_rate"),
            eps_ttm=self._first_number(static, "eps_ttm") or self._number_from_metric(valuation_pe.get("part")),
            forward_eps=forward_eps,
            bps=self._first_number(static, "bps"),
            total_shares=self._first_number(static, "total_shares"),
            valuation_date=self._first_text(valuation_overview, "date"),
            valuation_summary=self._strip_html(self._first_text(valuation_overview, "ai_summary") or self._first_text(valuation_pe, "desc")),
        )

    def _build_financials_from_report(self, symbol: str, payload: dict, periods: int, report: str) -> SymbolFinancialsResponse:
        period_map: dict[str, FinancialPeriod] = {}
        currency = None

        raw_list = payload.get("list") or {}
        if not isinstance(raw_list, dict):
            raw_list = {}

        for statement in raw_list.values():
            if not isinstance(statement, dict):
                continue
            for indicator in statement.get("indicators") or []:
                if not isinstance(indicator, dict):
                    continue
                currency = currency or indicator.get("currency")
                for account in indicator.get("accounts") or []:
                    if not isinstance(account, dict):
                        continue
                    metric_key = self._report_metric_key(account, indicator)
                    if metric_key is None:
                        continue
                    for item in account.get("values") or []:
                        if not isinstance(item, dict):
                            continue
                        value = self._to_number(item.get("value"))
                        if value is None:
                            continue
                        if metric_key in PERCENT_REPORT_METRICS or account.get("percent") is True:
                            value = value / 100
                        period_key = self._report_period_key(item, report)
                        period = period_map.get(period_key)
                        if period is None:
                            period = FinancialPeriod(
                                label=str(item.get("period") or period_key),
                                fiscal_year=self._to_int(item.get("year")),
                                fiscal_period=str(item.get("period") or ""),
                                report_type=report,
                            )
                            period_map[period_key] = period
                        if period.metrics.get(metric_key) is None:
                            period.metrics[metric_key] = value

        ordered_periods = list(period_map.values())[:periods]
        for period in ordered_periods:
            period.metrics = self._complete_report_metrics(period.metrics)

        return SymbolFinancialsResponse(
            symbol=symbol,
            currency=str(currency) if currency else None,
            report_type=report,
            period_count=len(ordered_periods),
            periods=ordered_periods,
        )

    def compare(self, left_symbol: str, right_symbol: str, periods: int = 8, report: str = "qf") -> SymbolComparisonResponse:
        with ThreadPoolExecutor(max_workers=2) as executor:
            left_future = executor.submit(self.get_financials, left_symbol, periods=periods, report=report)
            right_future = executor.submit(self.get_financials, right_symbol, periods=periods, report=report)
            left = left_future.result()
            right = right_future.result()
        return SymbolComparisonResponse(
            left=left,
            right=right,
            latest_metric_comparison=self._compare_latest_metrics(left, right),
        )

    def generate_ai_advice(
        self,
        left_symbol: str,
        right_symbol: str,
        question: str | None = None,
        comparison: SymbolComparisonResponse | None = None,
    ) -> SymbolAiAdviceResponse:
        comparison = comparison or self.compare(left_symbol, right_symbol)
        prompt_payload = self._build_ai_payload(comparison)
        min_period_count = min(comparison.left.period_count, comparison.right.period_count)
        prompt = (
            "你是一个偏 aggressive growth 的股票基本面分析助手。"
            f"请只基于下面两只股票当前行情估值数据、最近{min_period_count}个季度财报核心指标、程序已计算的趋势和对比结果，判断哪一只更适合加仓/建仓。"
            "必须输出 JSON，不要输出 Markdown。字段包括 recommendation、confidence、summary、key_reasons、risks、add_conditions、data_limitations。"
            "recommendation 只能是 left、right、neutral。confidence 只能是 high、medium、low。"
            "不得自行编造季度数量、不得把数值上升描述成下降、不得把数值下降描述成上升。"
            "涉及趋势方向时必须以 trend_summary.direction 为准；涉及左右优劣时必须以 latest_metric_comparison.winner 为准。"
            "如果数据不足或 period_count 少于 8，请降低 confidence 并写入 data_limitations。"
            f"用户问题：{question or '哪只更适合加仓/建仓？'}\n"
            f"财报数据：{json.dumps(prompt_payload, ensure_ascii=False)}"
        )
        raw_response = self.llm_service.chat(
            [
                {"role": "system", "content": "You are a disciplined financial analysis assistant. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1600,
            response_format={"type": "json_object"},
        )
        payload = self._extract_json(raw_response)
        recommendation = self._normalize_recommendation(payload.get("recommendation"), comparison)
        return SymbolAiAdviceResponse(
            left_symbol=comparison.left.symbol,
            right_symbol=comparison.right.symbol,
            recommendation=recommendation,
            confidence=self._normalize_confidence(payload.get("confidence")),
            summary=str(payload.get("summary") or ""),
            key_reasons=self._string_list(payload.get("key_reasons")),
            risks=self._string_list(payload.get("risks")),
            add_conditions=self._string_list(payload.get("add_conditions")),
            data_limitations=self._string_list(payload.get("data_limitations")),
            raw_response=raw_response,
        )

    def _build_ai_payload(self, comparison: SymbolComparisonResponse) -> dict:
        return {
            "left": self._compact_financials_for_ai(comparison.left),
            "right": self._compact_financials_for_ai(comparison.right),
            "latest_metric_comparison": [item.model_dump() for item in comparison.latest_metric_comparison],
        }

    def _compact_financials_for_ai(self, financials: SymbolFinancialsResponse) -> dict:
        return {
            "symbol": financials.symbol,
            "currency": financials.currency,
            "report_type": financials.report_type,
            "period_count": financials.period_count,
            "market_snapshot": financials.market_snapshot.model_dump() if financials.market_snapshot else None,
            "period_labels": [period.label for period in financials.periods],
            "latest_metrics": financials.periods[0].metrics if financials.periods else {},
            "trend_summary": self._build_trend_summary(financials),
        }

    def _build_trend_summary(self, financials: SymbolFinancialsResponse) -> dict[str, dict]:
        if not financials.periods:
            return {}
        latest = financials.periods[0]
        oldest = financials.periods[-1]
        summary = {}
        for key, label, _higher_is_better in CORE_METRICS:
            latest_value = latest.metrics.get(key)
            oldest_value = oldest.metrics.get(key)
            change = None
            change_pct = None
            direction = "unknown"
            if latest_value is not None and oldest_value is not None:
                change = round(latest_value - oldest_value, 6)
                if oldest_value:
                    change_pct = round(change / abs(oldest_value), 6)
                if abs(change) <= max(abs(latest_value), abs(oldest_value), 1.0) * 0.02:
                    direction = "flat"
                elif change > 0:
                    direction = "up"
                else:
                    direction = "down"
            summary[key] = {
                "label": label,
                "latest_period": latest.label,
                "oldest_period": oldest.label,
                "latest_value": latest_value,
                "oldest_value": oldest_value,
                "change": change,
                "change_pct": change_pct,
                "direction": direction,
            }
        return summary

    def _report_metric_key(self, account: dict, indicator: dict) -> str | None:
        field = str(account.get("field") or "")
        ranking_code = str(account.get("ranking_code") or "")
        exact_key = REPORT_FIELD_METRICS.get(self._normalize_report_text(field)) or REPORT_FIELD_METRICS.get(
            self._normalize_report_text(ranking_code)
        )
        if exact_key is not None:
            return exact_key

        name = str(account.get("name") or "")
        title = str(indicator.get("title") or "")
        haystack = self._normalize_report_text(f"{field} {ranking_code} {name} {title}")
        for key, aliases in REPORT_METRIC_ALIASES.items():
            if any(alias in haystack for alias in aliases):
                return key
        return None

    def _normalize_report_text(self, value: str) -> str:
        return value.lower().replace("_", "").replace(" ", "").replace("-", "")

    def _valuation_stock(self, valuation: dict, symbol: str) -> dict:
        stocks = valuation.get("stocks")
        if not isinstance(stocks, dict):
            return {}
        counter_id = ""
        try:
            counter_id = self.longbridge_client._symbol_to_counter_id(symbol)
        except AttributeError:
            counter_id = ""
        if counter_id and isinstance(stocks.get(counter_id), dict):
            return stocks[counter_id]

        code = symbol.rsplit(".", 1)[0].upper()
        for key, value in stocks.items():
            if isinstance(value, dict) and str(key).upper().endswith(f"/{code}"):
                return value
        return {}

    def _first_text(self, *items: Any) -> str | None:
        sources = [item for item in items if isinstance(item, dict)]
        names = [item for item in items if isinstance(item, str)]
        for source in sources:
            for name in names:
                value = source.get(name)
                if value not in (None, ""):
                    return str(value)
        return None

    def _first_number(self, *items: Any) -> float | None:
        sources = [item for item in items if isinstance(item, dict)]
        names = [item for item in items if isinstance(item, str)]
        for source in sources:
            for name in names:
                value = self._number_from_metric(source.get(name))
                if value is not None:
                    return value
        return None

    def _number_from_metric(self, value: Any) -> float | None:
        if value in (None, "", "-"):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = re.sub(r"[^0-9.\-]", "", str(value))
        if cleaned in {"", "-", "."}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _latest_forecast_eps(self, payload: dict) -> float | None:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return None
        items = [item for item in raw_items if isinstance(item, dict)]
        if not items:
            return None
        current_item = next((item for item in reversed(items) if str(item.get("forecast_end_date") or "") == "0"), None)
        item = current_item or items[-1]
        return self._first_number(item, "forecast_eps_mean", "forecast_eps_median", "forecast_eps")

    def _strip_html(self, value: str | None) -> str | None:
        if not value:
            return None
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()

    def _report_period_key(self, item: dict, report: str) -> str:
        fp_end = item.get("fp_end")
        if fp_end not in (None, ""):
            return f"{fp_end}:{report}"
        return f"{item.get('year') or ''}:{item.get('period') or ''}:{report}"

    def _complete_report_metrics(self, metrics: dict[str, float | None]) -> dict[str, float | None]:
        completed = dict(metrics)
        revenue = completed.get("revenue")
        gross_profit = completed.get("gross_profit")
        gross_margin = completed.get("gross_margin")
        operating_income = completed.get("operating_income")
        operating_margin = completed.get("operating_margin")
        net_income = completed.get("net_income")
        net_margin = completed.get("net_margin")
        operating_cash_flow = completed.get("operating_cash_flow")
        free_cash_flow = completed.get("free_cash_flow")
        cash = completed.get("cash_and_equivalents")
        net_debt = completed.get("net_debt")
        total_assets = completed.get("total_assets")
        total_liability = completed.get("total_liability")
        if completed.get("gross_profit") is None and gross_margin is not None and revenue is not None:
            completed["gross_profit"] = round(gross_margin * revenue, 6)
            gross_profit = completed["gross_profit"]
        if completed.get("operating_income") is None and operating_margin is not None and revenue is not None:
            completed["operating_income"] = round(operating_margin * revenue, 6)
            operating_income = completed["operating_income"]
        if completed.get("net_income") is None and net_margin is not None and revenue is not None:
            completed["net_income"] = round(net_margin * revenue, 6)
            net_income = completed["net_income"]
        if completed.get("gross_margin") is None:
            completed["gross_margin"] = self._ratio(gross_profit, revenue)
        if completed.get("operating_margin") is None:
            completed["operating_margin"] = self._ratio(operating_income, revenue)
        if completed.get("net_margin") is None:
            completed["net_margin"] = self._ratio(net_income, revenue)
        if completed.get("free_cash_flow") is None and free_cash_flow is not None:
            completed["free_cash_flow"] = free_cash_flow
        if completed.get("free_cash_flow") is None and operating_cash_flow is not None:
            completed["free_cash_flow"] = operating_cash_flow
        if completed.get("total_debt") is None and net_debt is not None and cash is not None:
            completed["total_debt"] = round(net_debt + cash, 6)
        if completed.get("shareholders_equity") is None and total_assets is not None and total_liability is not None:
            completed["shareholders_equity"] = round(total_assets - total_liability, 6)
        return {key: completed.get(key) for key, _label, _higher_is_better in CORE_METRICS}

    def _normalize_fields(self, raw_fields: list[Any]) -> list[FinancialField]:
        fields = []
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            raw_value = item.get("value")
            fields.append(
                FinancialField(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    value=self._to_number(raw_value) if self._to_number(raw_value) is not None else raw_value,
                    raw_value=str(raw_value) if raw_value is not None else None,
                    yoy=self._to_number(item.get("yoy")),
                    value_type=str(item.get("value_type") or "") or None,
                    level=self._to_int(item.get("level")),
                )
            )
        return fields

    def _build_core_metrics(self, statements: dict[str, list[FinancialField]]) -> dict[str, float | None]:
        income_fields = statements.get("IS", [])
        balance_fields = statements.get("BS", [])
        cash_flow_fields = statements.get("CF", [])
        revenue = self._find_metric(income_fields, "revenue")
        gross_profit = self._find_metric(income_fields, "gross_profit")
        operating_income = self._find_metric(income_fields, "operating_income")
        net_income = self._find_metric(income_fields, "net_income")
        eps = self._find_metric(income_fields, "eps")
        operating_cash_flow = self._find_metric(cash_flow_fields, "operating_cash_flow")
        free_cash_flow = self._find_metric(cash_flow_fields, "free_cash_flow")
        capex = self._find_metric(cash_flow_fields, "capital_expenditure")
        if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
            free_cash_flow = operating_cash_flow - abs(capex)
        cash = self._find_metric(balance_fields, "cash_and_equivalents")
        total_debt = self._calculate_total_debt(balance_fields)
        equity = self._find_metric(balance_fields, "shareholders_equity")
        return {
            "revenue": revenue,
            "gross_profit": gross_profit,
            "gross_margin": self._ratio(gross_profit, revenue),
            "operating_income": operating_income,
            "operating_margin": self._ratio(operating_income, revenue),
            "net_income": net_income,
            "net_margin": self._ratio(net_income, revenue),
            "eps": eps,
            "operating_cash_flow": operating_cash_flow,
            "free_cash_flow": free_cash_flow,
            "cash_and_equivalents": cash,
            "total_debt": total_debt,
            "shareholders_equity": equity,
            "roe": self._ratio(net_income, equity),
        }

    def _find_metric(self, fields: list[FinancialField], metric_key: str) -> float | None:
        id_match = self._first_value_by_ids(fields, METRIC_FIELD_IDS.get(metric_key, set()))
        if id_match is not None:
            return id_match
        aliases = METRIC_ALIASES[metric_key]
        for field in fields:
            haystack = f"{field.id} {field.name}".lower().replace("_", " ")
            if any(alias.lower() in haystack for alias in aliases):
                return self._to_number(field.raw_value)
        return None

    def _calculate_total_debt(self, fields: list[FinancialField]) -> float | None:
        direct = self._find_metric(fields, "total_debt")
        if direct is not None:
            return direct
        current_debt = self._first_value_by_ids(fields, {"88", "89"})
        long_term_debt = self._first_value_by_ids(fields, {"99"})
        capital_lease = self._first_value_by_ids(fields, {"100"})
        values = [item for item in (current_debt, long_term_debt, capital_lease) if item is not None]
        return sum(values) if values else None

    def _first_value_by_ids(self, fields: list[FinancialField], ids: set[str]) -> float | None:
        for field in fields:
            if field.id in ids:
                return self._to_number(field.raw_value)
        return None

    def _compare_latest_metrics(self, left: SymbolFinancialsResponse, right: SymbolFinancialsResponse) -> list[MetricComparisonItem]:
        left_metrics = left.periods[0].metrics if left.periods else {}
        right_metrics = right.periods[0].metrics if right.periods else {}
        items = []
        for key, label, higher_is_better in CORE_METRICS:
            left_value = left_metrics.get(key)
            right_value = right_metrics.get(key)
            winner = self._winner(left_value, right_value, higher_is_better)
            items.append(MetricComparisonItem(key=key, label=label, left_value=left_value, right_value=right_value, winner=winner))
        return items

    def _winner(self, left: float | None, right: float | None, higher_is_better: bool) -> str:
        if left is None or right is None:
            return "unknown"
        if abs(left - right) <= max(abs(left), abs(right), 1.0) * 0.02:
            return "tie"
        if higher_is_better:
            return "left" if left > right else "right"
        return "left" if left < right else "right"

    def _period_key(self, raw_period: dict, report: str) -> str:
        return f"{raw_period.get('ff_year') or ''}:{self._period_value(raw_period)}:{report}"

    def _period_label(self, raw_period: dict, report: str) -> str:
        year = self._to_int(raw_period.get("ff_year"))
        period = self._period_value(raw_period)
        if report == "af":
            return f"FY{year or '--'}"
        return f"Q{period} {year or '--'}"

    def _period_value(self, raw_period: dict) -> str:
        value = raw_period.get("ff_period")
        return str(value) if value is not None else ""

    def _ratio(self, numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or not denominator:
            return None
        return round(numerator / denominator, 6)

    def _to_number(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_json(self, raw_response: str) -> dict:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            start = raw_response.find("{")
            end = raw_response.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return {}
            try:
                payload = json.loads(raw_response[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return payload if isinstance(payload, dict) else {}

    def _normalize_recommendation(self, value: Any, comparison: SymbolComparisonResponse) -> str:
        raw_value = str(value or "").strip().lower()
        if raw_value in {"left", "right", "neutral"}:
            return raw_value
        if raw_value in {comparison.left.symbol.lower(), comparison.left.symbol.lower().replace(".us", "")}:
            return "left"
        if raw_value in {comparison.right.symbol.lower(), comparison.right.symbol.lower().replace(".us", "")}:
            return "right"
        return "neutral"

    def _normalize_confidence(self, value: Any) -> str:
        raw_value = str(value or "").strip().lower()
        return raw_value if raw_value in {"high", "medium", "low"} else "low"

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]
