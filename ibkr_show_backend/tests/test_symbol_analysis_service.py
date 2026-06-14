from app.services.symbol_analysis_service import SymbolAnalysisService


def _period(year: int, quarter: int, fields: list[dict]) -> dict:
    return {"ff_year": year, "ff_period": quarter, "fields": fields}


class StubLongbridgeFinancialClient:
    def __init__(self) -> None:
        self.financial_report_calls: list[str] = []

    def _symbol_to_counter_id(self, symbol: str) -> str:
        code, market = symbol.rsplit(".", 1)
        return f"ST/{market}/{code}"

    def get_quote_snapshot(self, symbol: str) -> dict:
        return {"last": "180.50", "change_percentage": "1.25"}

    def get_static_info(self, symbol: str) -> dict:
        return {"name": "Apple", "currency": "USD", "eps_ttm": "6.4", "bps": "4.5", "total_shares": "15000000000"}

    def get_calc_indexes(self, symbol: str) -> dict:
        return {"mktcap": "2700000000000", "pe": "28.2", "pb": "7.3", "dps_rate": "0.52", "turnover_rate": "0.8"}

    def get_valuation_detail(self, symbol: str) -> dict:
        return {
            "overview": {
                "date": "2026 年 5 月 12 日",
                "ai_summary": "当前市盈率 <strong>28.20</strong>，处于合理区间。",
                "metrics": {"pe": {"industry_median": "21.4", "metric": "28.20x", "part": "6.4"}},
            },
            "history": {"metrics": {"pe": {"median": "24.6"}}},
            "stocks": {"ST/US/AAPL": {"market_cap": "2700000000000", "name": "Apple"}},
        }

    def get_forecast_eps(self, symbol: str) -> dict:
        return {
            "items": [
                {"forecast_end_date": "1767139200", "forecast_eps_mean": "8.7"},
                {"forecast_end_date": "0", "forecast_eps_mean": "9.0", "forecast_eps_median": "8.8"},
            ]
        }

    def get_financial_report(self, symbol: str, kind: str = "ALL", report: str = "qf") -> dict:
        self.financial_report_calls.append(symbol)
        value = {"fp_end": "1774670400", "period": "Q1 2026", "year": 2026}
        accounts = [
            {"field": "Revenue", "name": "营业收入", "values": [{**value, "value": "1000"}]},
            {"field": "GrossProfit", "name": "毛利润", "values": [{**value, "value": "500"}]},
            {"field": "OperatingIncome", "name": "营业利润", "values": [{**value, "value": "300"}]},
            {"field": "NetIncome", "name": "净利润", "values": [{**value, "value": "200"}]},
            {"field": "EPS", "name": "每股收益", "values": [{**value, "value": "2.5"}]},
            {"field": "OperatingCashFlow", "name": "经营现金流", "values": [{**value, "value": "260"}]},
            {"field": "FreeCashFlow", "name": "自由现金流", "values": [{**value, "value": "200"}]},
            {"field": "CashSTInvest", "name": "现金及短期投资", "values": [{**value, "value": "400"}]},
            {"field": "NetDebt", "name": "净债务", "values": [{**value, "value": "-300"}]},
            {"field": "TotalAssets", "name": "总资产", "values": [{**value, "value": "900"}]},
            {"field": "TotalLiability", "name": "总负债", "values": [{**value, "value": "100"}]},
            {"field": "ROE", "name": "ROE", "percent": True, "values": [{**value, "value": "25"}]},
        ]
        return {"list": {"IS": {"indicators": [{"currency": "USD", "title": "核心指标", "accounts": accounts}]}}, "report": report}

    def get_financial_statement(self, symbol: str, kind: str, report: str = "qf") -> dict:
        payloads = {
            "IS": [
                _period(
                    2026,
                    1,
                    [
                        {"id": "revenue", "name": "Revenue", "value": "1000", "yoy": "0.2", "value_type": "bignumber", "level": 2},
                        {"id": "gross_profit", "name": "Gross Profit", "value": "500", "value_type": "bignumber", "level": 2},
                        {"id": "operating_income", "name": "Operating Income", "value": "300", "value_type": "bignumber", "level": 2},
                        {"id": "net_income", "name": "Net Income", "value": "200", "value_type": "bignumber", "level": 2},
                        {"id": "eps", "name": "Basic EPS", "value": "2.5", "value_type": "number", "level": 2},
                    ],
                )
            ],
            "BS": [
                _period(
                    2026,
                    1,
                    [
                        {"id": "cash", "name": "Cash And Cash Equivalents", "value": "400", "value_type": "bignumber", "level": 2},
                        {"id": "total_debt", "name": "Total Debt", "value": "100", "value_type": "bignumber", "level": 2},
                        {"id": "shareholders_equity", "name": "Shareholders Equity", "value": "800", "value_type": "bignumber", "level": 2},
                    ],
                )
            ],
            "CF": [
                _period(
                    2026,
                    1,
                    [
                        {"id": "operating_cash_flow", "name": "Operating Cash Flow", "value": "260", "value_type": "bignumber", "level": 2},
                        {"id": "capital_expenditure", "name": "Capital Expenditure", "value": "-60", "value_type": "bignumber", "level": 2},
                    ],
                )
            ],
        }
        return {"currency": "USD", "list": payloads[kind]}


class StubLLMService:
    def chat(self, *args, **kwargs) -> str:
        return '{"recommendation":"left","confidence":"medium","summary":"A 更好","key_reasons":["增长更好"],"risks":["估值偏高"],"add_conditions":["回撤后"],"data_limitations":[]}'


class SymbolRecommendationLLMService:
    def chat(self, *args, **kwargs) -> str:
        return '{"recommendation":"AAPL.US","confidence":"very sure","summary":"A 更好"}'


class CapturingLLMService:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs) -> str:
        self.prompts.append(str(messages[-1]["content"]))
        return '{"recommendation":"left","confidence":"medium","summary":"A 更适合","key_reasons":[],"risks":[],"add_conditions":["等待回调"],"data_limitations":[]}'


def test_symbol_financials_extracts_core_metrics() -> None:
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), StubLLMService())

    response = service.get_financials("AAPL", periods=8)

    assert response.symbol == "AAPL.US"
    assert response.currency == "USD"
    assert response.periods[0].label == "Q1 2026"
    assert response.periods[0].metrics["revenue"] == 1000
    assert response.periods[0].metrics["gross_margin"] == 0.5
    assert response.periods[0].metrics["free_cash_flow"] == 200
    assert response.periods[0].metrics["cash_and_equivalents"] == 400
    assert response.periods[0].metrics["total_debt"] == 100
    assert response.periods[0].metrics["shareholders_equity"] == 800
    assert response.periods[0].metrics["eps"] == 2.5
    assert response.periods[0].metrics["roe"] == 0.25
    assert response.market_snapshot is not None
    assert response.market_snapshot.market_cap == 2700000000000
    assert response.market_snapshot.pe_ttm == 28.2
    assert response.market_snapshot.forward_pe == 20.0556
    assert response.market_snapshot.forward_eps == 9.0
    assert response.market_snapshot.pe_3y_median == 24.6
    assert response.market_snapshot.pe_industry_median == 21.4


def test_symbol_financials_extracts_longbridge_numeric_statement_ids() -> None:
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), StubLLMService())

    metrics = service._build_core_metrics(
        {
            "IS": service._normalize_fields(
                [
                    {"id": "1", "name": "总营业收入", "value": "10253000000.00"},
                    {"id": "2", "name": "毛利润", "value": "5677000000.00"},
                    {"id": "5", "name": "营业利润", "value": "1476000000.00"},
                    {"id": "43", "name": "归属公司的净利润", "value": "1383000000.00"},
                ]
            ),
            "BS": service._normalize_fields(
                [
                    {"id": "51", "name": "现金及现金等价物", "value": "5585000000.00"},
                    {"id": "88", "name": "长期债务/资本租赁的流动部分", "value": "874000000.00"},
                    {"id": "99", "name": "长期债务", "value": "2350000000.00"},
                    {"id": "100", "name": "资本租赁", "value": "647000000.00"},
                    {"id": "128", "name": "所有者权益", "value": "64462000000.00"},
                ]
            ),
            "CF": service._normalize_fields(
                [
                    {"id": "159", "name": "经营活动现金流量", "value": "2955000000.00"},
                    {"id": "160", "name": "资本支出", "value": "-389000000.00"},
                ]
            ),
        }
    )

    assert metrics["cash_and_equivalents"] == 5585000000
    assert metrics["total_debt"] == 3871000000
    assert metrics["shareholders_equity"] == 64462000000
    assert metrics["free_cash_flow"] == 2566000000


def test_symbol_comparison_and_ai_advice() -> None:
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), StubLLMService())

    comparison = service.compare("AAPL", "MSFT")
    advice = service.generate_ai_advice("AAPL", "MSFT")

    assert comparison.latest_metric_comparison[0].key == "revenue"
    assert comparison.latest_metric_comparison[0].winner == "tie"
    assert advice.recommendation == "left"
    assert advice.key_reasons == ["增长更好"]


def test_symbol_ai_payload_uses_actual_period_count_and_computed_trends() -> None:
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), StubLLMService())

    comparison = service.compare("AAPL", "MSFT")
    payload = service._build_ai_payload(comparison)

    assert payload["left"]["period_count"] == 1
    assert payload["left"]["market_snapshot"]["pe_ttm"] == 28.2
    assert payload["left"]["market_snapshot"]["forward_pe"] == 20.0556
    assert payload["left"]["trend_summary"]["revenue"]["direction"] == "flat"
    assert payload["left"]["trend_summary"]["revenue"]["latest_value"] == 1000


def test_symbol_ai_recommendation_normalizes_symbol_and_confidence() -> None:
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), SymbolRecommendationLLMService())

    advice = service.generate_ai_advice("AAPL", "MSFT")

    assert advice.recommendation == "left"
    assert advice.confidence == "low"


def test_symbol_ai_advice_prompt_covers_add_or_entry_decision() -> None:
    llm_service = CapturingLLMService()
    service = SymbolAnalysisService(StubLongbridgeFinancialClient(), llm_service)

    advice = service.generate_ai_advice("AAPL", "MSFT")

    assert advice.add_conditions == ["等待回调"]
    assert "更适合加仓/建仓" in llm_service.prompts[0]


def test_symbol_ai_advice_reuses_existing_comparison() -> None:
    client = StubLongbridgeFinancialClient()
    service = SymbolAnalysisService(client, StubLLMService())

    comparison = service.compare("AAPL", "MSFT")
    calls_after_compare = list(client.financial_report_calls)
    advice = service.generate_ai_advice("AAPL", "MSFT", comparison=comparison)

    assert advice.recommendation == "left"
    assert sorted(calls_after_compare) == ["AAPL.US", "MSFT.US"]
    assert client.financial_report_calls == calls_after_compare
