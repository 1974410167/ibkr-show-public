from pydantic import BaseModel

from app.schemas.common import PaginationInfo


class PositionItem(BaseModel):
    account_id: str
    report_date: str
    symbol: str | None = None
    description: str | None = None
    asset_class: str | None = None
    quantity: float | None = None
    mark_price: float | None = None
    position_value: float | None = None
    percent_of_nav: float | None = None
    average_cost_price: float | None = None
    cost_basis_money: float | None = None
    diluted_cost_amount: float | None = None
    diluted_cost_price: float | None = None
    diluted_cost_status: str | None = None
    total_realized_pnl: float | None = None
    realized_pnl_percent: float | None = None
    total_unrealized_pnl: float | None = None
    unrealized_pnl_percent: float | None = None
    total_fifo_pnl: float | None = None
    previous_day_change_percent: float | None = None


class PositionDetailBar(BaseModel):
    report_date: str
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    quantity: float | None = None


class PositionDetailTradeMarker(BaseModel):
    trade_date: str | None = None
    date_time: str | None = None
    buy_sell: str | None = None
    quantity: float | None = None
    trade_price: float | None = None
    fifo_pnl_realized: float | None = None


class PositionDetailResponse(BaseModel):
    symbol: str | None = None
    description: str | None = None
    asset_class: str | None = None
    bars: list[PositionDetailBar]
    trades: list[PositionDetailTradeMarker]


class PositionConcentrationItem(BaseModel):
    symbol: str | None = None
    description: str | None = None
    asset_class: str | None = None
    position_value: float = 0.0
    percent_of_nav: float | None = None


class PositionAssetDistributionItem(BaseModel):
    asset_class: str | None = None
    position_value: float = 0.0
    positions_count: int = 0


class PositionSummaryResponse(BaseModel):
    report_date: str | None = None
    total_positions: int = 0
    total_position_value: float = 0.0
    total_cost_basis_money: float = 0.0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_fifo_pnl: float = 0.0
    top_positions: list[PositionConcentrationItem]
    asset_distribution: list[PositionAssetDistributionItem]


class PositionListResponse(BaseModel):
    items: list[PositionItem]
    pagination: PaginationInfo
    summary: PositionSummaryResponse | None = None
