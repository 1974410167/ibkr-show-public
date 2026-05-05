from app.schemas.account import AccountOverviewResponse, LatestReportDateResponse
from app.schemas.cash_flows import (
    CashFlowCurrencySummaryItem,
    CashFlowItem,
    CashFlowListResponse,
    CashFlowSummaryResponse,
)
from app.schemas.charts import EquityCurvePoint, EquityCurveResponse
from app.schemas.common import PaginationInfo
from app.schemas.dividends import (
    DividendCurrencySummaryItem,
    DividendItem,
    DividendListResponse,
    DividendSummaryResponse,
)
from app.schemas.positions import PositionItem, PositionListResponse, PositionSummaryResponse
from app.schemas.trades import TradeItem, TradeListResponse, TradeSummaryResponse


def test_account_overview_schema_instantiates() -> None:
    overview = AccountOverviewResponse(account_id="U1", report_date="2026-04-17", ytd_twr=4.2)
    latest = LatestReportDateResponse(report_date="2026-04-17")

    assert overview.account_id == "U1"
    assert overview.ytd_twr == 4.2
    assert latest.report_date == "2026-04-17"


def test_position_and_trade_response_schemas_instantiates() -> None:
    pagination = PaginationInfo(page=1, page_size=20, total=1, total_pages=1)
    positions = PositionListResponse(
        items=[
            PositionItem(
                account_id="U1",
                report_date="2026-04-17",
                symbol="AAPL",
                average_cost_price=175.0,
                realized_pnl_percent=2.5,
                unrealized_pnl_percent=4.5,
                previous_day_change_percent=1.2,
            )
        ],
        pagination=pagination,
    )
    trades = TradeListResponse(
        items=[TradeItem(account_id="U1", trade_date="2026-04-17", symbol="AAPL")],
        pagination=pagination,
    )
    summary = TradeSummaryResponse(
        trade_count=1,
        buy_count=1,
        sell_count=0,
        total_commission=1.2,
        total_realized_pnl=10.0,
        total_proceeds=100.0,
        symbols_count=1,
    )

    assert positions.items[0].symbol == "AAPL"
    assert positions.items[0].average_cost_price == 175.0
    assert trades.items[0].symbol == "AAPL"
    assert summary.trade_count == 1


def test_position_summary_schema_instantiates() -> None:
    summary = PositionSummaryResponse(
        report_date="2026-04-17",
        total_positions=2,
        total_position_value=1000.0,
        total_cost_basis_money=800.0,
        total_realized_pnl=20.0,
        total_unrealized_pnl=50.0,
        total_fifo_pnl=70.0,
        top_positions=[],
        asset_distribution=[],
    )

    assert summary.total_fifo_pnl == 70.0


def test_chart_response_schema_instantiates() -> None:
    response = EquityCurveResponse(
        items=[
            EquityCurvePoint(
                report_date="2026-04-17",
                total_equity=100.0,
                total_pnl=5.0,
                net_cost=95.0,
                daily_mtm=3.0,
                daily_twr=0.5,
            )
        ]
    )
    assert response.items[0].total_equity == 100.0
    assert response.items[0].total_pnl == 5.0
    assert response.items[0].daily_mtm == 3.0


def test_cash_flow_response_schema_instantiates() -> None:
    pagination = PaginationInfo(page=1, page_size=20, total=1, total_pages=1)
    response = CashFlowListResponse(
        items=[CashFlowItem(account_id="U1", currency="USD", amount=100.0, flow_direction="deposit")],
        pagination=pagination,
    )
    summary = CashFlowSummaryResponse(
        record_count=1,
        deposit_count=1,
        withdrawal_count=0,
        total_deposit_amount=100.0,
        total_withdrawal_amount=0.0,
        net_amount=100.0,
        by_currency=[
            CashFlowCurrencySummaryItem(
                currency="USD",
                record_count=1,
                deposit_count=1,
                withdrawal_count=0,
                total_deposit_amount=100.0,
                total_withdrawal_amount=0.0,
                net_amount=100.0,
            )
        ],
    )

    assert response.items[0].flow_direction == "deposit"
    assert summary.net_amount == 100.0
    assert summary.by_currency[0].currency == "USD"


def test_dividend_response_schema_instantiates() -> None:
    pagination = PaginationInfo(page=1, page_size=20, total=1, total_pages=1)
    response = DividendListResponse(
        items=[DividendItem(account_id="U1", currency="USD", symbol="MSFT", amount=14.56, flow_type="Dividends")],
        pagination=pagination,
    )
    summary = DividendSummaryResponse(
        record_count=2,
        dividend_count=1,
        withholding_tax_count=1,
        gross_dividend_amount=14.56,
        withholding_tax_amount=-1.46,
        net_amount=13.1,
        by_currency=[
            DividendCurrencySummaryItem(
                currency="USD",
                record_count=2,
                dividend_count=1,
                withholding_tax_count=1,
                gross_dividend_amount=14.56,
                withholding_tax_amount=-1.46,
                net_amount=13.1,
            )
        ],
    )

    assert response.items[0].symbol == "MSFT"
    assert response.items[0].flow_type == "Dividends"
    assert summary.net_amount == 13.1
    assert summary.by_currency[0].withholding_tax_count == 1
