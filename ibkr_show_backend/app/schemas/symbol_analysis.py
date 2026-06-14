from pydantic import BaseModel, Field


class FinancialField(BaseModel):
    id: str
    name: str
    value: float | str | None = None
    raw_value: str | None = None
    yoy: float | None = None
    value_type: str | None = None
    level: int | None = None


class FinancialPeriod(BaseModel):
    label: str
    fiscal_year: int | None = None
    fiscal_period: str
    report_type: str
    metrics: dict[str, float | None] = Field(default_factory=dict)
    statements: dict[str, list[FinancialField]] = Field(default_factory=dict)


class SymbolMarketSnapshot(BaseModel):
    symbol: str
    name: str | None = None
    currency: str | None = None
    last_price: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    forward_pe: float | None = None
    pe_3y_median: float | None = None
    pe_industry_median: float | None = None
    pb: float | None = None
    dividend_yield: float | None = None
    turnover_rate: float | None = None
    eps_ttm: float | None = None
    forward_eps: float | None = None
    bps: float | None = None
    total_shares: float | None = None
    valuation_date: str | None = None
    valuation_summary: str | None = None


class SymbolFinancialsResponse(BaseModel):
    symbol: str
    currency: str | None = None
    report_type: str
    period_count: int
    periods: list[FinancialPeriod]
    market_snapshot: SymbolMarketSnapshot | None = None
    source: str = "longbridge"


class MetricComparisonItem(BaseModel):
    key: str
    label: str
    left_value: float | None = None
    right_value: float | None = None
    winner: str


class SymbolComparisonResponse(BaseModel):
    left: SymbolFinancialsResponse
    right: SymbolFinancialsResponse
    latest_metric_comparison: list[MetricComparisonItem]


class SymbolAiAdviceRequest(BaseModel):
    left_symbol: str
    right_symbol: str
    question: str | None = None
    comparison: SymbolComparisonResponse | None = None


class SymbolAiAdviceResponse(BaseModel):
    left_symbol: str
    right_symbol: str
    recommendation: str
    confidence: str
    summary: str
    key_reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    add_conditions: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    raw_response: str | None = None
