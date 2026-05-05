from pydantic import BaseModel

from app.schemas.common import PaginationInfo


class DividendItem(BaseModel):
    account_id: str
    currency: str | None = None
    symbol: str | None = None
    description: str | None = None
    date_time: str | None = None
    settle_date: str | None = None
    amount: float | None = None
    flow_type: str | None = None
    dividend_type: str | None = None
    transaction_id: str | None = None
    report_date: str | None = None
    ex_date: str | None = None


class DividendListResponse(BaseModel):
    items: list[DividendItem]
    pagination: PaginationInfo


class DividendCurrencySummaryItem(BaseModel):
    currency: str | None = None
    record_count: int
    dividend_count: int
    withholding_tax_count: int
    gross_dividend_amount: float
    withholding_tax_amount: float
    net_amount: float


class DividendSummaryResponse(BaseModel):
    record_count: int
    dividend_count: int
    withholding_tax_count: int
    gross_dividend_amount: float | None = None
    withholding_tax_amount: float | None = None
    net_amount: float | None = None
    by_currency: list[DividendCurrencySummaryItem]
