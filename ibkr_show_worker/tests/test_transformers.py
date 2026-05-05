from pathlib import Path

from worker.parsers.flex_csv_parser import FlexSection, FlexStatement, FlexStatementMetadata
from worker.parsers.flex_csv_parser import parse_flex_csv
from worker.parsers.transformers import (
    transform_daily_statement,
)


def test_transform_daily_statement_generates_account_position_trade_and_cash_flow_documents() -> None:
    statement = parse_flex_csv(
        Path("worker/fixtures/daily_sample.csv")
    )
    transformed = transform_daily_statement(statement)

    assert len(transformed.account_documents) == 1
    assert transformed.account_documents[0]["account_id"] == "U1234567"
    assert transformed.account_documents[0]["report_date"] == "2026-04-18"

    assert len(transformed.position_documents) == 2
    first_position = transformed.position_documents[0]
    assert first_position["symbol"] == "AAPL"
    assert first_position["isin"] == "US0378331005"
    assert first_position["average_cost_price"] == 175.0
    assert first_position["total_realized_pnl"] == 120.5
    assert first_position["realized_pnl_percent"] == 120.5 / 17500 * 100
    assert first_position["total_unrealized_pnl"] == 80.25
    assert first_position["unrealized_pnl_percent"] == 80.25 / 17500 * 100
    assert first_position["total_fifo_pnl"] == 200.75
    assert first_position["previous_day_change_percent"] == (190 - 185) / 185 * 100

    assert len(transformed.trade_documents) == 1
    assert transformed.trade_documents[0]["unbc_total_commission"] == 1.2
    assert len(transformed.cash_flow_documents) == 2
    assert transformed.cash_flow_documents[0]["transaction_id"] == "CF1"
    assert transformed.cash_flow_documents[0]["flow_type"] == "Deposits/Withdrawals"
    assert transformed.cash_flow_documents[0]["amount"] == 5000.0
    assert transformed.cash_flow_documents[1]["transaction_id"] == "CF2"
    assert transformed.cash_flow_documents[1]["flow_type"] == "Ordinary Dividend"
    assert transformed.cash_flow_documents[1]["amount"] == 12.5
    assert len(transformed.price_history_documents) == 4
    assert transformed.price_history_documents[0]["symbol"] == "AAPL"
    assert transformed.price_history_documents[0]["close_price"] == 185.0
    assert transformed.price_history_documents[1]["previous_close_price"] == 185.0


def test_transform_daily_statement_supports_real_ibkr_fifo_headers() -> None:
    statement = parse_flex_csv(
        Path("worker/fixtures/daily_sample.csv")
    )
    fifo_row = statement.get_section("FIFO").rows[0]
    fifo_row.pop("RealizedPNL", None)
    fifo_row.pop("UnrealizedPNL", None)
    fifo_row.pop("TotalPNL", None)
    fifo_row["TotalRealizedPnl"] = "12.3"
    fifo_row["TotalUnrealizedPnl"] = "45.6"
    fifo_row["TotalFifoPnl"] = "57.9"

    transformed = transform_daily_statement(statement)

    assert transformed.position_documents[0]["total_realized_pnl"] == 12.3
    assert transformed.position_documents[0]["total_unrealized_pnl"] == 45.6
    assert transformed.position_documents[0]["total_fifo_pnl"] == 57.9


def test_transform_daily_statement_falls_back_to_mytd_realized_pnl_ytd_when_fifo_realized_is_zero() -> None:
    statement = parse_flex_csv(
        Path("worker/fixtures/daily_sample.csv")
    )
    fifo_row = statement.get_section("FIFO").rows[0]
    fifo_row["RealizedPNL"] = "0"
    fifo_row["TotalRealizedPnl"] = "0"

    transformed = transform_daily_statement(statement)

    assert transformed.position_documents[0]["total_realized_pnl"] == 800.0
    assert transformed.position_documents[0]["realized_pnl_ytd"] == 800.0
    assert transformed.position_documents[0]["realized_pnl_percent"] == 800.0 / 17500 * 100


def test_transform_daily_statement_generates_historical_account_documents_from_equt_rows() -> None:
    statement = FlexStatement(
        source_file=Path("/tmp/daily_history.csv"),
        metadata=FlexStatementMetadata(
            query_name="MyDailyData",
            from_date="2026-04-16",
            to_date="2026-04-17",
            account_ids=["U1234567"],
        ),
        sections={
            "EQUT": FlexSection(
                name="EQUT",
                headers=["ClientAccountID", "CurrencyPrimary", "ReportDate", "Cash", "Stock", "Total"],
                rows=[
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "ReportDate": "20260416",
                        "Cash": "10",
                        "Stock": "90",
                        "Total": "100",
                    },
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "ReportDate": "20260417",
                        "Cash": "20",
                        "Stock": "100",
                        "Total": "120",
                    },
                ],
            ),
            "FIFO": FlexSection(
                name="FIFO",
                headers=["ReportDate", "TotalRealizedPnl", "TotalUnrealizedPnl", "TotalFifoPnl"],
                rows=[
                    {
                        "ReportDate": "20260417",
                        "TotalRealizedPnl": "12",
                        "TotalUnrealizedPnl": "8",
                        "TotalFifoPnl": "20",
                    }
                ],
            ),
            "CNAV": FlexSection(
                name="CNAV",
                headers=["ToDate", "TWR"],
                rows=[{"ToDate": "20260417", "TWR": "1.2"}],
            ),
        },
        record_counts={},
    )

    transformed = transform_daily_statement(statement)

    assert len(transformed.account_documents) == 2
    assert transformed.account_documents[0]["report_date"] == "2026-04-16"
    assert transformed.account_documents[0]["total_equity"] == 100.0
    assert transformed.account_documents[1]["report_date"] == "2026-04-17"
    assert transformed.account_documents[1]["stock_value"] == 100.0
    assert "fifo_total_pnl" not in transformed.account_documents[1]


def test_transform_daily_statement_keeps_dividend_related_cash_flows() -> None:
    statement = FlexStatement(
        source_file=Path("/tmp/dividend_history.csv"),
        metadata=FlexStatementMetadata(
            query_name="MyDailyData",
            from_date="2026-03-12",
            to_date="2026-03-13",
            account_ids=["U1234567"],
        ),
        sections={
            "CTRN": FlexSection(
                name="CTRN",
                headers=[
                    "ClientAccountID",
                    "CurrencyPrimary",
                    "Date/Time",
                    "SettleDate",
                    "Amount",
                    "Type",
                    "DividendType",
                    "TransactionID",
                    "ReportDate",
                    "ExDate",
                    "Symbol",
                    "Description",
                ],
                rows=[
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "Date/Time": "20260312;202000",
                        "SettleDate": "20260312",
                        "Amount": "14.56",
                        "Type": "Dividends",
                        "DividendType": "Ordinary Dividend",
                        "TransactionID": "DIV1",
                        "ReportDate": "20260312",
                        "ExDate": "20260219",
                        "Symbol": "MSFT",
                        "Description": "MSFT CASH DIVIDEND",
                    },
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "Date/Time": "20260312;202000",
                        "SettleDate": "20260312",
                        "Amount": "-1.46",
                        "Type": "Withholding Tax",
                        "TransactionID": "DIV2",
                        "ReportDate": "20260312",
                        "Symbol": "MSFT",
                        "Description": "MSFT CASH DIVIDEND - US TAX",
                    },
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "Date/Time": "20260313;202000",
                        "SettleDate": "20260313",
                        "Amount": "0.08",
                        "Type": "Payment In Lieu Of Dividends",
                        "DividendType": "Ordinary Dividend",
                        "TransactionID": "DIV3",
                        "ReportDate": "20260313",
                        "ExDate": "20260227",
                        "Symbol": "IBKR",
                        "Description": "IBKR PAYMENT IN LIEU OF DIVIDEND",
                    },
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "Date/Time": "20260313",
                        "SettleDate": "20260313",
                        "Amount": "1",
                        "Type": "Broker Interest Paid",
                        "TransactionID": "OTHER1",
                        "ReportDate": "20260313",
                        "Description": "should be ignored",
                    },
                ],
            )
        },
        record_counts={},
    )

    transformed = transform_daily_statement(statement)

    assert [item["transaction_id"] for item in transformed.cash_flow_documents] == ["DIV1", "DIV2", "DIV3"]
    assert [item["flow_type"] for item in transformed.cash_flow_documents] == [
        "Dividends",
        "Withholding Tax",
        "Payment In Lieu Of Dividends",
    ]


def test_transform_daily_statement_enriches_latest_account_snapshot_for_single_day_file() -> None:
    statement = FlexStatement(
        source_file=Path("/tmp/daily_single.csv"),
        metadata=FlexStatementMetadata(
            query_name="MyDailyData",
            from_date="2026-04-17",
            to_date="2026-04-17",
            account_ids=["U1234567"],
        ),
        sections={
            "EQUT": FlexSection(
                name="EQUT",
                headers=["ClientAccountID", "CurrencyPrimary", "ReportDate", "Cash", "Stock", "Total"],
                rows=[
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "ReportDate": "20260417",
                        "Cash": "20",
                        "Stock": "100",
                        "Total": "120",
                    }
                ],
            ),
            "FIFO": FlexSection(
                name="FIFO",
                headers=["ReportDate", "TotalRealizedPnl", "TotalUnrealizedPnl", "TotalFifoPnl"],
                rows=[
                    {
                        "ReportDate": "20260417",
                        "TotalRealizedPnl": "12",
                        "TotalUnrealizedPnl": "8",
                        "TotalFifoPnl": "20",
                    }
                ],
            ),
            "CNAV": FlexSection(
                name="CNAV",
                headers=["StartingValue", "EndingValue", "TWR"],
                rows=[{"StartingValue": "100", "EndingValue": "120", "TWR": "1.2"}],
            ),
        },
        record_counts={},
    )

    transformed = transform_daily_statement(statement)

    assert len(transformed.account_documents) == 1
    assert transformed.account_documents[0]["report_date"] == "2026-04-17"
    assert transformed.account_documents[0]["fifo_total_pnl"] == 20.0
    assert transformed.account_documents[0]["cnav_ending_value"] == 120.0


def test_transform_daily_statement_enriches_latest_snapshot_when_daily_file_contains_previous_equt_row() -> None:
    statement = FlexStatement(
        source_file=Path("/tmp/daily_with_previous_equt.csv"),
        metadata=FlexStatementMetadata(
            query_name="MyDailyData",
            from_date="2026-04-29",
            to_date="2026-04-29",
            account_ids=["U1234567"],
        ),
        sections={
            "EQUT": FlexSection(
                name="EQUT",
                headers=["ClientAccountID", "CurrencyPrimary", "ReportDate", "Cash", "Stock", "Total"],
                rows=[
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "ReportDate": "20260428",
                        "Cash": "10",
                        "Stock": "90",
                        "Total": "100",
                    },
                    {
                        "ClientAccountID": "U1234567",
                        "CurrencyPrimary": "USD",
                        "ReportDate": "20260429",
                        "Cash": "20",
                        "Stock": "100",
                        "Total": "120",
                    },
                ],
            ),
            "FIFO": FlexSection(
                name="FIFO",
                headers=["ReportDate", "TotalRealizedPnl", "TotalUnrealizedPnl", "TotalFifoPnl"],
                rows=[
                    {
                        "ReportDate": "20260429",
                        "TotalRealizedPnl": "12",
                        "TotalUnrealizedPnl": "8",
                        "TotalFifoPnl": "20",
                    }
                ],
            ),
            "CNAV": FlexSection(
                name="CNAV",
                headers=["FromDate", "ToDate", "StartingValue", "EndingValue", "TWR"],
                rows=[{"FromDate": "20260429", "ToDate": "20260429", "StartingValue": "100", "EndingValue": "120", "TWR": "1.2"}],
            ),
            "CRTT": FlexSection(
                name="CRTT",
                headers=["CurrencyPrimary", "DividendsYTD", "BrokerInterestYTD", "CommissionsYTD"],
                rows=[{"CurrencyPrimary": "BASE_SUMMARY", "DividendsYTD": "10", "BrokerInterestYTD": "1", "CommissionsYTD": "-2"}],
            ),
        },
        record_counts={},
    )

    transformed = transform_daily_statement(statement)

    assert len(transformed.account_documents) == 2
    latest_document = transformed.account_documents[-1]
    assert latest_document["report_date"] == "2026-04-29"
    assert latest_document["fifo_total_pnl"] == 20.0
    assert latest_document["cnav_ending_value"] == 120.0
    assert latest_document["crtt_dividends_ytd"] == 10.0


def test_transform_daily_statement_parsed_daily_file_with_previous_equt_row_keeps_latest_overview_metrics(
    tmp_path,
) -> None:
    statement_file = tmp_path / "daily_with_previous_equt.csv"
    statement_file.write_text(
        "\n".join(
            [
                "BOF",
                "BOA,QueryName,MyDailyData,FromDate,2026-04-29,ToDate,2026-04-29",
                "BOS,ACCT",
                "HEADER,AccountId,FromDate,ToDate,BaseCurrency",
                "DATA,U1234567,2026-04-29,2026-04-29,USD",
                "EOS",
                "BOS,EQUT",
                "HEADER,ClientAccountID,CurrencyPrimary,ReportDate,Cash,Stock,Total",
                "DATA,U1234567,USD,20260428,10,90,100",
                "DATA,U1234567,USD,20260429,20,100,120",
                "EOS",
                "BOS,CNAV",
                "HEADER,ClientAccountID,CurrencyPrimary,FromDate,ToDate,StartingValue,EndingValue,MTM,TWR",
                "DATA,U1234567,USD,20260429,20260429,100,120,20,1.2",
                "EOS",
                "BOS,CRTT",
                "HEADER,ClientAccountID,CurrencyPrimary,DividendsYTD,BrokerInterestYTD,CommissionsYTD",
                "DATA,U1234567,BASE_SUMMARY,10,1,-2",
                "EOS",
                "BOS,FIFO",
                "HEADER,ReportDate,TotalRealizedPnl,TotalUnrealizedPnl,TotalFifoPnl",
                "DATA,20260429,12,8,20",
                "EOS",
            ]
        ),
        encoding="utf-8",
    )

    transformed = transform_daily_statement(parse_flex_csv(statement_file))

    assert len(transformed.account_documents) == 2
    latest_document = transformed.account_documents[-1]
    assert latest_document["report_date"] == "2026-04-29"
    assert latest_document["cnav_mtm"] == 20.0
    assert latest_document["cnav_twr"] == 1.2
    assert latest_document["crtt_dividends_ytd"] == 10.0
    assert latest_document["fifo_total_pnl"] == 20.0
