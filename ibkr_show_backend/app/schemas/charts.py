from pydantic import BaseModel


class EquityCurvePoint(BaseModel):
    report_date: str
    total_equity: float | None = None
    total_pnl: float | None = None
    net_cost: float | None = None
    realized_pnl: float | None = None
    daily_mtm: float | None = None
    daily_twr: float | None = None


class EquityCurveResponse(BaseModel):
    items: list[EquityCurvePoint]


class PerformanceCalendarItem(BaseModel):
    period_key: str
    label: str
    period_start: str
    period_end: str | None = None
    pnl: float | None = None
    twr: float | None = None
    has_data: bool = False


class PerformanceCalendarSummary(BaseModel):
    positive_periods: int = 0
    negative_periods: int = 0
    total_pnl: float | None = None
    periods_with_data: int = 0


class PerformanceCalendarResponse(BaseModel):
    view: str
    anchor: str
    latest_anchor: str
    earliest_anchor: str | None = None
    previous_anchor: str | None = None
    next_anchor: str | None = None
    items: list[PerformanceCalendarItem]
    summary: PerformanceCalendarSummary
