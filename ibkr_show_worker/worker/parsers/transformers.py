from dataclasses import dataclass
from pathlib import Path
import re

from worker.es.index_definitions import (
    ACCOUNT_INDEX,
    CASH_FLOW_INDEX,
    POSITION_INDEX,
    PRICE_HISTORY_INDEX,
    TRADE_INDEX,
)
from worker.parsers.flex_csv_parser import FlexSection, FlexStatement
from worker.utils.dates import parse_date_value, to_iso_date, to_iso_datetime, utc_now_iso
from worker.utils.numbers import clean_string, to_bool, to_float


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _safe_id_component(value: object) -> str:
    cleaned = clean_string(value) or "unknown"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)


def _row_lookup(row: dict[str, str | None]) -> dict[str, str | None]:
    return {_normalize_key(key): value for key, value in row.items()}


def _get_value(row: dict[str, str | None], *aliases: str) -> str | None:
    lookup = _row_lookup(row)
    for alias in aliases:
        normalized_alias = _normalize_key(alias)
        value = lookup.get(normalized_alias)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _get_number(row: dict[str, str | None], *aliases: str) -> float | None:
    return to_float(_get_value(row, *aliases))


def _first_row(section: FlexSection | None) -> dict[str, str | None]:
    if section and section.rows:
        return section.rows[0]
    return {}


def _latest_row(section: FlexSection | None, *date_aliases: str) -> dict[str, str | None]:
    if section is None or not section.rows:
        return {}

    best_row = section.rows[-1]
    best_date = None
    for row in section.rows:
        for alias in date_aliases:
            parsed = parse_date_value(_get_value(row, alias))
            if parsed and (best_date is None or parsed >= best_date):
                best_date = parsed
                best_row = row
    return best_row


def build_account_snapshot_id(account_id: str, report_date: str) -> str:
    return f"{_safe_id_component(account_id)}_{_safe_id_component(report_date)}"


def build_position_snapshot_id(
    account_id: str,
    report_date: str,
    asset_class: str | None,
    symbol_or_conid: str | None,
) -> str:
    return "_".join(
        [
            _safe_id_component(account_id),
            _safe_id_component(report_date),
            _safe_id_component(asset_class),
            _safe_id_component(symbol_or_conid),
        ]
    )


def build_trade_record_id(
    account_id: str,
    trade_date: str | None,
    symbol: str | None,
    trade_id: str | None,
    buy_sell: str | None,
    quantity: object,
    transaction_id: str | None,
) -> str:
    if transaction_id:
        return _safe_id_component(transaction_id)

    return "_".join(
        [
            _safe_id_component(account_id),
            _safe_id_component(trade_date),
            _safe_id_component(symbol),
            _safe_id_component(trade_id),
            _safe_id_component(buy_sell),
            _safe_id_component(quantity),
        ]
    )


def build_cash_flow_record_id(
    account_id: str,
    date_time: str | None,
    amount: object,
    transaction_id: str | None,
) -> str:
    if transaction_id:
        return _safe_id_component(transaction_id)

    return "_".join(
        [
            _safe_id_component(account_id),
            _safe_id_component(date_time),
            _safe_id_component(amount),
        ]
    )


def build_price_history_record_id(
    account_id: str,
    report_date: str | None,
    asset_class: str | None,
    symbol_or_conid: str | None,
) -> str:
    return "_".join(
        [
            _safe_id_component(account_id),
            _safe_id_component(report_date),
            _safe_id_component(asset_class),
            _safe_id_component(symbol_or_conid),
        ]
    )


def _build_security_lookup(section: FlexSection | None) -> dict[str, dict[str, str | None]]:
    if section is None:
        return {}

    lookup: dict[str, dict[str, str | None]] = {}
    for row in section.rows:
        conid = _get_value(row, "Conid", "ConID")
        symbol = _get_value(row, "Symbol")
        asset_class = _get_value(row, "AssetClass", "Asset Category")

        if conid:
            lookup[f"conid:{conid}"] = row
        if symbol and asset_class:
            lookup[f"symbol:{asset_class}:{symbol}"] = row
    return lookup


def _build_position_merge_key(
    row: dict[str, str | None],
    report_date: str | None,
) -> str:
    conid = _get_value(row, "Conid", "ConID")
    if conid:
        return f"conid:{conid}"

    symbol = _get_value(row, "Symbol")
    asset_class = _get_value(row, "AssetClass", "Asset Category")
    return f"symbol:{asset_class or 'UNKNOWN'}:{symbol or 'UNKNOWN'}:{report_date or 'UNKNOWN'}"


def _build_security_merge_key(row: dict[str, str | None]) -> str:
    conid = _get_value(row, "Conid", "ConID")
    if conid:
        return f"conid:{conid}"

    symbol = _get_value(row, "Symbol")
    asset_class = _get_value(row, "AssetClass", "Asset Category")
    return f"symbol:{asset_class or 'UNKNOWN'}:{symbol or 'UNKNOWN'}"


def _build_trade_merge_key(row: dict[str, str | None]) -> str:
    trade_id = _get_value(row, "TradeID", "TradeId")
    if trade_id:
        return f"trade_id:{trade_id}"

    return ":".join(
        [
            "fallback",
            _get_value(row, "Symbol") or "UNKNOWN",
            _get_value(row, "Buy/Sell", "BuySell") or "UNKNOWN",
            _get_value(row, "Quantity") or "UNKNOWN",
            _get_value(row, "Date/Time", "DateTime", "TradeDate") or "UNKNOWN",
        ]
    )


def _build_lookup(section: FlexSection | None, key_builder) -> dict[str, dict[str, str | None]]:
    if section is None:
        return {}
    return {key_builder(row): row for row in section.rows}


def _calculate_percentage(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(abs(denominator)) * 100.0


def _build_price_history_lookup(
    section: FlexSection | None,
) -> dict[str, list[tuple[str, float, float | None]]]:
    if section is None:
        return {}

    lookup: dict[str, list[tuple[str, float, float | None]]] = {}
    for row in section.rows:
        history_date = to_iso_date(_get_value(row, "Date"))
        price = _get_number(row, "Price")
        prior_mtm_pnl = _get_number(row, "PriorMtmPnl", "PriorMtmPNL")
        if history_date is None or price is None:
            continue
        lookup.setdefault(_build_security_merge_key(row), []).append((history_date, float(price), prior_mtm_pnl))

    for rows in lookup.values():
        rows.sort(key=lambda item: item[0])

    return lookup


def _build_previous_day_change_percent(
    price_history: list[tuple[str, float, float | None]],
    report_date: str,
    mark_price: float | None,
    quantity: float | None,
) -> float | None:
    if mark_price is None:
        return None

    previous_price = None
    prior_mtm_pnl = None
    for index, item in enumerate(price_history):
        history_date, price, current_prior_mtm = item
        if history_date == report_date:
            prior_mtm_pnl = current_prior_mtm
            if index > 0:
                previous_price = price_history[index - 1][1]
            break
        if history_date < report_date:
            previous_price = price

    if previous_price is None and prior_mtm_pnl is not None and quantity not in (None, 0):
        previous_price = float(mark_price) - (float(prior_mtm_pnl) / float(quantity))

    if previous_price in (None, 0):
        return None

    return (float(mark_price) - float(previous_price)) / float(previous_price) * 100.0


def _get_account_id(statement: FlexStatement) -> str | None:
    if statement.metadata.account_ids:
        return statement.metadata.account_ids[0]

    for section_name in ("ACCT", "EQUT", "POST", "TRNT"):
        section = statement.get_section(section_name)
        if not section:
            continue
        for row in section.rows:
            account_id = _get_value(row, "AccountId", "Account", "ClientAccountID", "Account ID")
            if account_id:
                return account_id
    return None


def _get_report_date(statement: FlexStatement) -> str | None:
    if statement.metadata.to_date or statement.metadata.from_date:
        return statement.metadata.to_date or statement.metadata.from_date

    for section_name, aliases in (
        ("EQUT", ("ReportDate",)),
        ("POST", ("ReportDate",)),
        ("TRNT", ("ReportDate", "TradeDate")),
        ("FIFO", ("ReportDate",)),
        ("CNAV", ("ToDate", "ReportDate")),
        ("CRTT", ("ToDate", "ReportDate")),
    ):
        section = statement.get_section(section_name)
        if not section:
            continue
        row = _latest_row(section, *aliases)
        for alias in aliases:
            value = to_iso_date(_get_value(row, alias))
            if value:
                return value

    return None


def _find_metric_by_label(
    section: FlexSection | None,
    labels: tuple[str, ...],
    value_aliases: tuple[str, ...],
) -> float | None:
    if section is None:
        return None

    normalized_labels = {_normalize_key(label) for label in labels}
    for row in section.rows:
        for value in row.values():
            if value and _normalize_key(value) in normalized_labels:
                for alias in value_aliases:
                    candidate = _get_number(row, alias)
                    if candidate is not None:
                        return candidate
    return None


def _coerce_source_file_name(source_file: Path) -> str:
    return source_file.name


def _clean_document(document: dict) -> dict:
    cleaned: dict = {}
    for key, value in document.items():
        if key == "_id":
            cleaned[key] = value
            continue
        if value == "":
            cleaned[key] = None
            continue
        cleaned[key] = value
    return cleaned


def _compact_document(document: dict) -> dict:
    cleaned: dict = {}
    for key, value in document.items():
        if key == "_id":
            cleaned[key] = value
            continue
        if value in ("", None):
            continue
        cleaned[key] = value
    return cleaned


@dataclass
class TransformResult:
    account_documents: list[dict]
    position_documents: list[dict]
    trade_documents: list[dict]
    cash_flow_documents: list[dict] | None = None
    price_history_documents: list[dict] | None = None

    def documents_by_index(self) -> dict[str, list[dict]]:
        return {
            ACCOUNT_INDEX: self.account_documents,
            POSITION_INDEX: self.position_documents,
            TRADE_INDEX: self.trade_documents,
            CASH_FLOW_INDEX: self.cash_flow_documents or [],
            PRICE_HISTORY_INDEX: self.price_history_documents or [],
        }


def transform_daily_statement(statement: FlexStatement) -> TransformResult:
    account_documents_by_id = {
        document["_id"]: document for document in transform_account_history_statement(statement, "daily_snapshot")
    }
    latest_account_document = _transform_account_daily_snapshot(statement) if _is_single_day_statement(statement) else None
    if latest_account_document:
        account_documents_by_id[latest_account_document["_id"]] = latest_account_document

    position_documents = _transform_position_daily_snapshots(statement, "daily_snapshot")
    trade_documents = _transform_trade_records(statement, "daily_snapshot")
    cash_flow_documents = _transform_daily_cash_flows(statement, "daily_snapshot")
    price_history_documents = _transform_price_history(statement, "daily_snapshot")

    return TransformResult(
        account_documents=[
            account_documents_by_id[document_id]
            for document_id in sorted(account_documents_by_id, key=lambda item: account_documents_by_id[item]["report_date"])
        ],
        position_documents=position_documents,
        trade_documents=trade_documents,
        cash_flow_documents=cash_flow_documents,
        price_history_documents=price_history_documents,
    )


def _is_single_day_statement(statement: FlexStatement) -> bool:
    from_date = statement.metadata.from_date
    to_date = statement.metadata.to_date
    if from_date and to_date and from_date == to_date:
        return True

    equt_section = statement.get_section("EQUT")
    if equt_section:
        report_dates = {
            to_iso_date(_get_value(row, "ReportDate"))
            for row in equt_section.rows
            if to_iso_date(_get_value(row, "ReportDate")) is not None
        }
        if len(report_dates) > 1:
            return False
        if len(report_dates) == 1 or len(equt_section.rows) <= 1:
            return True

    if from_date and to_date:
        return False

    return True


def _transform_price_history(statement: FlexStatement, source_query_type: str) -> list[dict]:
    pppo_section = statement.get_section("PPPO")
    if pppo_section is None:
        return []

    account_id = _get_account_id(statement) or "unknown"
    security_lookup = _build_security_lookup(statement.get_section("SECU"))

    grouped_rows: dict[str, list[dict[str, str | None]]] = {}
    for row in pppo_section.rows:
        report_date = to_iso_date(_get_value(row, "Date"))
        price = _get_number(row, "Price")
        if report_date is None or price is None:
            continue
        grouped_rows.setdefault(_build_security_merge_key(row), []).append(row)

    documents: list[dict] = []
    for rows in grouped_rows.values():
        rows.sort(key=lambda row: to_iso_date(_get_value(row, "Date")) or "")
        previous_close_price: float | None = None

        for row in rows:
            report_date = to_iso_date(_get_value(row, "Date"))
            close_price = _get_number(row, "Price")
            if report_date is None or close_price is None:
                continue

            conid = _get_value(row, "Conid", "ConID")
            asset_class = _get_value(row, "AssetClass", "Asset Category")
            symbol = _get_value(row, "Symbol")
            security_row = security_lookup.get(f"conid:{conid}") or security_lookup.get(
                f"symbol:{asset_class}:{symbol}"
            ) or {}
            open_price = previous_close_price if previous_close_price is not None else close_price
            high_price = max(open_price, close_price)
            low_price = min(open_price, close_price)

            document = {
                "_id": build_price_history_record_id(
                    account_id=account_id,
                    report_date=report_date,
                    asset_class=asset_class,
                    symbol_or_conid=conid or symbol,
                ),
                "account_id": account_id,
                "report_date": report_date,
                "currency": _get_value(row, "CurrencyPrimary", "Currency"),
                "asset_class": asset_class,
                "sub_category": _get_value(row, "SubCategory", "Sub Category"),
                "symbol": symbol,
                "description": _get_value(row, "Description") or _get_value(security_row, "Description"),
                "conid": conid,
                "security_id": _get_value(row, "SecurityID", "Security Id")
                or _get_value(security_row, "SecurityID", "Security Id"),
                "security_id_type": _get_value(row, "SecurityIDType", "Security Id Type")
                or _get_value(security_row, "SecurityIDType", "Security Id Type"),
                "isin": _get_value(row, "ISIN") or _get_value(security_row, "ISIN"),
                "figi": _get_value(row, "FIGI") or _get_value(security_row, "FIGI"),
                "listing_exchange": _get_value(row, "ListingExchange", "Listing Exchange")
                or _get_value(security_row, "ListingExchange", "Listing Exchange"),
                "issuer": _get_value(security_row, "Issuer"),
                "issuer_country_code": _get_value(
                    security_row,
                    "IssuerCountryCode",
                    "Issuer Country Code",
                ),
                "close_price": close_price,
                "previous_close_price": previous_close_price,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "prior_mtm_pnl": _get_number(row, "PriorMtmPnl", "PriorMtmPNL"),
                "fx_rate_to_base": _get_number(row, "FXRateToBase"),
                "source_file_name": _coerce_source_file_name(statement.source_file),
                "source_query_type": source_query_type,
                "ingested_at": utc_now_iso(),
            }
            documents.append(_clean_document(document))
            previous_close_price = close_price

    return documents


def _transform_cash_flow_rows(
    rows: list[dict[str, str | None]],
    source_file: Path,
    source_query_type: str,
) -> list[dict]:
    documents: list[dict] = []

    for row in rows:
        account_id = _get_value(row, "ClientAccountID", "AccountId") or "unknown"
        date_time = to_iso_datetime(_get_value(row, "Date/Time", "DateTime"))
        amount = _get_number(row, "Amount")
        fx_rate_to_base = _get_number(row, "FXRateToBase")
        amount_in_base = amount * fx_rate_to_base if amount is not None and fx_rate_to_base is not None else amount
        description = _get_value(row, "Description")
        transaction_id = _get_value(row, "TransactionID", "TransactionId")
        flow_type = _get_value(row, "Type") or "Deposits/Withdrawals"

        flow_direction = "deposit"
        if amount is not None and amount < 0:
            flow_direction = "withdrawal"
        elif description and "DISBURSEMENT" in description.upper():
            flow_direction = "withdrawal"

        document = {
            "_id": build_cash_flow_record_id(
                account_id=account_id,
                date_time=date_time,
                amount=amount,
                transaction_id=transaction_id,
            ),
            "account_id": account_id,
            "currency": _get_value(row, "CurrencyPrimary", "Currency"),
            "asset_class": _get_value(row, "AssetClass"),
            "sub_category": _get_value(row, "SubCategory"),
            "symbol": _get_value(row, "Symbol"),
            "description": description,
            "date_time": date_time,
            "settle_date": to_iso_date(_get_value(row, "SettleDate")),
            "available_for_trading_date": to_iso_date(_get_value(row, "AvailableForTradingDate")),
            "amount": amount,
            "fx_rate_to_base": fx_rate_to_base,
            "amount_in_base": amount_in_base,
            "flow_direction": flow_direction,
            "flow_type": flow_type,
            "dividend_type": _get_value(row, "DividendType"),
            "transaction_id": transaction_id,
            "trade_id": _get_value(row, "TradeID", "TradeId"),
            "code": _get_value(row, "Code"),
            "report_date": to_iso_date(_get_value(row, "ReportDate")),
            "ex_date": to_iso_date(_get_value(row, "ExDate")),
            "client_reference": _get_value(row, "ClientReference"),
            "action_id": _get_value(row, "ActionID", "ActionId"),
            "level_of_detail": _get_value(row, "LevelOfDetail", "Level Of Detail"),
            "source_file_name": _coerce_source_file_name(source_file),
            "source_query_type": source_query_type,
            "ingested_at": utc_now_iso(),
        }
        documents.append(_clean_document(document))

    return documents


def _is_dividend_related_flow_type(flow_type: str) -> bool:
    normalized = flow_type.strip()
    if normalized == "Withholding Tax":
        return True
    if "Payment In Lieu" in normalized:
        return True
    return "Dividend" in normalized


def _is_supported_cash_flow_type(flow_type: str | None) -> bool:
    normalized = (flow_type or "").strip()
    if normalized == "Deposits/Withdrawals":
        return True
    return _is_dividend_related_flow_type(normalized)


def _transform_daily_cash_flows(statement: FlexStatement, source_query_type: str) -> list[dict]:
    section = statement.get_section("CTRN")
    if section is None:
        return []

    relevant_rows = [row for row in section.rows if _is_supported_cash_flow_type(_get_value(row, "Type"))]
    return _transform_cash_flow_rows(relevant_rows, statement.source_file, source_query_type)


def transform_account_history_statement(statement: FlexStatement, source_query_type: str) -> list[dict]:
    account_id = _get_account_id(statement)
    equt_section = statement.get_section("EQUT")
    if not account_id or equt_section is None:
        return []

    documents_by_date: dict[str, dict] = {}
    for row in equt_section.rows:
        report_date = to_iso_date(_get_value(row, "ReportDate"))
        if report_date is None:
            continue

        documents_by_date[report_date] = _compact_document(
            {
                "_id": build_account_snapshot_id(account_id, report_date),
                "account_id": account_id,
                "report_date": report_date,
                "currency": _get_value(row, "Currency", "CurrencyPrimary", "BaseCurrency"),
                "total_equity": _get_number(row, "TotalEquity", "Total", "EndingSettledValue", "NetLiquidationValue"),
                "cash": _get_number(row, "Cash"),
                "stock_value": _get_number(row, "StockValue", "Stock", "Stocks"),
                "options_value": _get_number(row, "OptionsValue", "Options"),
                "funds_value": _get_number(row, "FundsValue", "Funds"),
                "crypto_value": _get_number(row, "CryptoValue", "Crypto"),
                "interest_accruals": _get_number(row, "InterestAccruals"),
                "dividend_accruals": _get_number(row, "DividendAccruals"),
                "margin_financing_charge_accruals": _get_number(row, "MarginFinancingChargeAccruals"),
                "source_file_name": _coerce_source_file_name(statement.source_file),
                "source_query_type": source_query_type,
                "ingested_at": utc_now_iso(),
            }
        )

    return [documents_by_date[report_date] for report_date in sorted(documents_by_date)]


def _transform_account_daily_snapshot(statement: FlexStatement) -> dict | None:
    account_id = _get_account_id(statement)
    report_date = _get_report_date(statement)
    if not account_id or not report_date:
        return None

    equt = _latest_row(statement.get_section("EQUT"), "ReportDate")
    cnav = _first_row(statement.get_section("CNAV"))
    crtt = _first_row(statement.get_section("CRTT"))
    fifo_section = statement.get_section("FIFO")

    fifo_total_realized = 0.0
    fifo_total_unrealized = 0.0
    fifo_total = 0.0
    if fifo_section:
        for row in fifo_section.rows:
            fifo_total_realized += _get_number(
                row,
                "TotalRealizedPnl",
                "RealizedPNL",
                "Realized P/L",
                "Realized",
            ) or 0.0
            fifo_total_unrealized += _get_number(
                row,
                "TotalUnrealizedPnl",
                "UnrealizedPNL",
                "Unrealized P/L",
                "Unrealized",
            ) or 0.0
            fifo_total += _get_number(
                row,
                "TotalFifoPnl",
                "TotalPNL",
                "Total P/L",
                "Total",
            ) or 0.0

    document = {
        "_id": build_account_snapshot_id(account_id, report_date),
        "account_id": account_id,
        "report_date": report_date,
        "currency": _get_value(equt, "Currency", "CurrencyPrimary", "BaseCurrency")
        or _get_value(_first_row(statement.get_section("ACCT")), "BaseCurrency", "Currency", "CurrencyPrimary"),
        "total_equity": _get_number(equt, "TotalEquity", "Total", "EndingSettledValue", "NetLiquidationValue"),
        "cash": _get_number(equt, "Cash"),
        "stock_value": _get_number(equt, "StockValue", "Stock", "Stocks"),
        "options_value": _get_number(equt, "OptionsValue", "Options"),
        "funds_value": _get_number(equt, "FundsValue", "Funds"),
        "crypto_value": _get_number(equt, "CryptoValue", "Crypto"),
        "interest_accruals": _get_number(equt, "InterestAccruals"),
        "dividend_accruals": _get_number(equt, "DividendAccruals"),
        "margin_financing_charge_accruals": _get_number(equt, "MarginFinancingChargeAccruals"),
        "cnav_starting_value": _get_number(cnav, "StartingValue", "BeginningValue"),
        "cnav_ending_value": _get_number(cnav, "EndingValue", "EndingNAV"),
        "cnav_mtm": _get_number(cnav, "MTM", "MarkToMarket"),
        "cnav_realized": _get_number(cnav, "Realized"),
        "cnav_change_in_unrealized": _get_number(cnav, "ChangeInUnrealized", "ChangeInUnrealizedPNL"),
        "cnav_dividends": _get_number(cnav, "Dividends"),
        "cnav_interest": _get_number(cnav, "Interest"),
        "cnav_commissions": _get_number(cnav, "Commissions"),
        "cnav_broker_fees": _get_number(cnav, "BrokerFees", "BrokerFee"),
        "cnav_net_fx_trading": _get_number(cnav, "NetFXTrading"),
        "cnav_twr": _get_number(cnav, "TWR", "TimeWeightedReturn"),
        "crtt_dividends_mtd": _get_number(crtt, "DividendsMTD"),
        "crtt_dividends_ytd": _get_number(crtt, "DividendsYTD"),
        "crtt_broker_interest_mtd": _get_number(crtt, "BrokerInterestMTD"),
        "crtt_broker_interest_ytd": _get_number(crtt, "BrokerInterestYTD"),
        "crtt_commissions_mtd": _get_number(crtt, "CommissionsMTD"),
        "crtt_commissions_ytd": _get_number(crtt, "CommissionsYTD"),
        "crtt_starting_cash": _get_number(crtt, "StartingCash"),
        "crtt_ending_cash": _get_number(crtt, "EndingCash"),
        "fifo_total_realized_pnl": fifo_total_realized,
        "fifo_total_unrealized_pnl": fifo_total_unrealized,
        "fifo_total_pnl": fifo_total,
        "source_file_name": _coerce_source_file_name(statement.source_file),
        "source_query_type": "daily_snapshot",
        "ingested_at": utc_now_iso(),
    }

    return _clean_document(document)


def _transform_position_daily_snapshots(
    statement: FlexStatement,
    source_query_type: str,
) -> list[dict]:
    report_date = _get_report_date(statement)
    account_id = _get_account_id(statement)
    post_section = statement.get_section("POST")
    if not post_section or not account_id or not report_date:
        return []

    fifo_lookup = _build_lookup(
        statement.get_section("FIFO"),
        lambda row: _build_position_merge_key(row, report_date),
    )
    mytd_lookup = _build_lookup(
        statement.get_section("MYTD"),
        lambda row: _build_position_merge_key(row, report_date),
    )
    netp_lookup = _build_lookup(
        statement.get_section("NETP"),
        lambda row: _build_position_merge_key(row, report_date),
    )
    security_lookup = _build_security_lookup(statement.get_section("SECU"))
    price_history_lookup = _build_price_history_lookup(statement.get_section("PPPO"))

    documents: list[dict] = []
    for row in post_section.rows:
        merge_key = _build_position_merge_key(row, report_date)
        fifo_row = fifo_lookup.get(merge_key, {})
        mytd_row = mytd_lookup.get(merge_key, {})
        netp_row = netp_lookup.get(merge_key, {})

        conid = _get_value(row, "Conid", "ConID")
        asset_class = _get_value(row, "AssetClass", "Asset Category")
        symbol = _get_value(row, "Symbol")
        security_row = security_lookup.get(f"conid:{conid}") or security_lookup.get(
            f"symbol:{asset_class}:{symbol}"
        ) or {}

        quantity = _get_number(row, "Quantity", "Position")
        mark_price = _get_number(row, "MarkPrice", "Mark Price", "ClosePrice")
        cost_basis_price = _get_number(row, "CostBasisPrice", "Cost Basis Price")
        cost_basis_money = _get_number(row, "CostBasisMoney", "CostBasis", "Cost Basis")
        mytd_realized_pnl_ytd = _get_number(
            mytd_row,
            "RealizedPNLYTD",
            "RealizedPnlYTD",
            "RealizedPNL_YTD",
            "Realized YTD",
        )

        total_realized = _get_number(
            fifo_row,
            "TotalRealizedPnl",
            "RealizedPNL",
            "Realized P/L",
        )
        if total_realized in (None, 0, 0.0) and mytd_realized_pnl_ytd not in (None, 0, 0.0):
            total_realized = mytd_realized_pnl_ytd
        total_unrealized = _get_number(
            fifo_row,
            "TotalUnrealizedPnl",
            "UnrealizedPNL",
            "Unrealized P/L",
        )
        if total_unrealized is None:
            total_unrealized = _get_number(row, "FifoPnlUnrealized", "FIFO P/L Unrealized")

        total_fifo = _get_number(
            fifo_row,
            "TotalFifoPnl",
            "TotalPNL",
            "Total P/L",
        )
        if total_fifo is None and total_realized is not None and total_unrealized is not None:
            total_fifo = total_realized + total_unrealized
        if total_fifo is None and total_unrealized is not None:
            total_fifo = total_unrealized

        average_cost_price = cost_basis_price
        if average_cost_price is None and quantity not in (None, 0) and cost_basis_money is not None:
            average_cost_price = abs(float(cost_basis_money) / float(quantity))

        unrealized_pnl_percent = _calculate_percentage(total_unrealized, cost_basis_money)
        realized_pnl_percent = _calculate_percentage(total_realized, cost_basis_money)
        previous_day_change_percent = _build_previous_day_change_percent(
            price_history_lookup.get(_build_security_merge_key(row), []),
            report_date=report_date,
            mark_price=mark_price,
            quantity=quantity,
        )

        document = {
            "_id": build_position_snapshot_id(account_id, report_date, asset_class, conid or symbol),
            "account_id": account_id,
            "report_date": report_date,
            "currency": _get_value(row, "Currency", "BaseCurrency")
            or _get_value(security_row, "Currency", "BaseCurrency"),
            "asset_class": asset_class,
            "sub_category": _get_value(row, "SubCategory", "Sub Category"),
            "symbol": symbol,
            "description": _get_value(row, "Description") or _get_value(security_row, "Description"),
            "conid": conid,
            "security_id": _get_value(row, "SecurityID", "Security Id")
            or _get_value(security_row, "SecurityID", "Security Id"),
            "security_id_type": _get_value(row, "SecurityIDType", "Security Id Type")
            or _get_value(security_row, "SecurityIDType", "Security Id Type"),
            "isin": _get_value(row, "ISIN") or _get_value(security_row, "ISIN"),
            "figi": _get_value(row, "FIGI") or _get_value(security_row, "FIGI"),
            "listing_exchange": _get_value(row, "ListingExchange", "Listing Exchange")
            or _get_value(security_row, "ListingExchange", "Listing Exchange"),
            "issuer": _get_value(security_row, "Issuer"),
            "issuer_country_code": _get_value(
                security_row,
                "IssuerCountryCode",
                "Issuer Country Code",
            ),
            "quantity": quantity,
            "mark_price": mark_price,
            "position_value": _get_number(row, "PositionValue", "MarketValue", "Position Value"),
            "open_price": _get_number(row, "OpenPrice", "Open Price"),
            "cost_basis_price": cost_basis_price,
            "average_cost_price": average_cost_price,
            "cost_basis_money": cost_basis_money,
            "percent_of_nav": _get_number(row, "PercentOfNAV", "Percent of NAV"),
            "fifo_pnl_unrealized": total_unrealized,
            "side": _get_value(row, "Side")
            or ("LONG" if quantity is not None and quantity >= 0 else "SHORT"),
            "shares_at_ib": _get_number(netp_row, "SharesAtIB", "Shares At IB"),
            "shares_borrowed": _get_number(netp_row, "SharesBorrowed", "Shares Borrowed"),
            "shares_lent": _get_number(netp_row, "SharesLent", "Shares Lent"),
            "net_shares": _get_number(netp_row, "NetShares", "Net Shares") or quantity,
            "total_realized_pnl": total_realized,
            "realized_pnl_percent": realized_pnl_percent,
            "total_unrealized_pnl": total_unrealized,
            "unrealized_pnl_percent": unrealized_pnl_percent,
            "total_fifo_pnl": total_fifo,
            "previous_day_change_percent": previous_day_change_percent,
            "realized_pnl_mtd": _get_number(mytd_row, "RealizedPNLMTD", "RealizedPNL_MTD", "Realized MTD"),
            "realized_pnl_ytd": mytd_realized_pnl_ytd,
            "mark_to_market_mtd": _get_number(
                mytd_row,
                "MarkToMarketMTD",
                "MarkToMarket_MTD",
                "MTM MTD",
            ),
            "mark_to_market_ytd": _get_number(
                mytd_row,
                "MarkToMarketYTD",
                "MarkToMarket_YTD",
                "MTM YTD",
            ),
            "source_file_name": _coerce_source_file_name(statement.source_file),
            "source_query_type": source_query_type,
            "ingested_at": utc_now_iso(),
        }
        documents.append(_clean_document(document))

    return documents


def _transform_trade_records(statement: FlexStatement, source_query_type: str) -> list[dict]:
    trnt_section = statement.get_section("TRNT")
    if trnt_section is None:
        return []

    account_id = _get_account_id(statement) or "unknown"
    report_date = _get_report_date(statement)
    security_lookup = _build_security_lookup(statement.get_section("SECU"))
    unbc_lookup = _build_lookup(statement.get_section("UNBC"), _build_trade_merge_key)
    documents: list[dict] = []

    for row in trnt_section.rows:
        level_of_detail = _get_value(row, "LevelOfDetail", "Level Of Detail")
        if level_of_detail in {"SUMMARY", "SYMBOL_SUMMARY"}:
            continue

        trade_merge_key = _build_trade_merge_key(row)
        unbc_row = unbc_lookup.get(trade_merge_key, {})

        conid = _get_value(row, "Conid", "ConID")
        symbol = _get_value(row, "Symbol")
        asset_class = _get_value(row, "AssetClass", "Asset Category")
        security_row = security_lookup.get(f"conid:{conid}") or security_lookup.get(
            f"symbol:{asset_class}:{symbol}"
        ) or {}

        trade_date = to_iso_date(_get_value(row, "TradeDate", "Date"))
        date_time = to_iso_datetime(_get_value(row, "Date/Time", "DateTime"))
        transaction_id = _get_value(row, "TransactionID", "TransactionId")
        trade_id = _get_value(row, "TradeID", "TradeId")
        quantity = _get_number(row, "Quantity")
        buy_sell = _get_value(row, "Buy/Sell", "BuySell")

        document = {
            "_id": build_trade_record_id(
                account_id=account_id,
                trade_date=trade_date,
                symbol=symbol,
                trade_id=trade_id,
                buy_sell=buy_sell,
                quantity=quantity,
                transaction_id=transaction_id,
            ),
            "account_id": account_id,
            "currency": _get_value(row, "Currency", "BaseCurrency"),
            "asset_class": asset_class,
            "sub_category": _get_value(row, "SubCategory", "Sub Category"),
            "symbol": symbol,
            "description": _get_value(row, "Description") or _get_value(security_row, "Description"),
            "conid": conid,
            "security_id": _get_value(row, "SecurityID", "Security Id")
            or _get_value(security_row, "SecurityID", "Security Id"),
            "security_id_type": _get_value(row, "SecurityIDType", "Security Id Type")
            or _get_value(security_row, "SecurityIDType", "Security Id Type"),
            "isin": _get_value(row, "ISIN") or _get_value(security_row, "ISIN"),
            "figi": _get_value(row, "FIGI") or _get_value(security_row, "FIGI"),
            "listing_exchange": _get_value(row, "ListingExchange", "Listing Exchange")
            or _get_value(security_row, "ListingExchange", "Listing Exchange"),
            "trade_id": trade_id,
            "related_trade_id": _get_value(row, "RelatedTradeID", "RelatedTradeId"),
            "report_date": report_date,
            "trade_date": trade_date,
            "date_time": date_time,
            "settle_date_target": to_iso_date(_get_value(row, "SettleDateTarget", "Settle Date Target")),
            "transaction_type": _get_value(row, "TransactionType", "Type"),
            "exchange": _get_value(row, "Exchange"),
            "quantity": quantity,
            "trade_price": _get_number(row, "TradePrice", "Price"),
            "trade_money": _get_number(row, "TradeMoney", "Trade Money"),
            "proceeds": _get_number(row, "Proceeds"),
            "taxes": _get_number(row, "Taxes"),
            "ib_commission": _get_number(row, "IBCommission", "IB Commission", "Commission"),
            "ib_commission_currency": _get_value(
                row,
                "IBCommissionCurrency",
                "IB Commission Currency",
                "CommissionCurrency",
            ),
            "net_cash": _get_number(row, "NetCash"),
            "close_price": _get_number(row, "ClosePrice", "Close Price"),
            "open_close_indicator": _get_value(row, "OpenCloseIndicator", "Open/Close Indicator"),
            "notes_codes": _get_value(row, "NotesCodes", "Notes/Codes"),
            "cost_basis": _get_number(row, "CostBasis", "Cost Basis"),
            "fifo_pnl_realized": _get_number(row, "FIFOPNLRealized", "FifoPnlRealized", "FIFO Realized P/L"),
            "mtm_pnl": _get_number(row, "MTMPNL", "MtmPnl", "MTM P/L"),
            "orig_trade_price": _get_number(row, "OrigTradePrice", "OriginalTradePrice"),
            "orig_trade_date": to_iso_date(_get_value(row, "OrigTradeDate", "OriginalTradeDate")),
            "orig_trade_id": _get_value(row, "OrigTradeID", "OriginalTradeID"),
            "orig_order_id": _get_value(row, "OrigOrderID", "OriginalOrderID"),
            "orig_transaction_id": _get_value(row, "OrigTransactionID", "OriginalTransactionID"),
            "buy_sell": buy_sell,
            "ib_order_id": _get_value(row, "IBOrderID", "IB Order ID"),
            "transaction_id": transaction_id,
            "ib_exec_id": _get_value(row, "IBExecID", "IB Exec ID"),
            "related_transaction_id": _get_value(row, "RelatedTransactionID", "Related Transaction ID"),
            "brokerage_order_id": _get_value(row, "BrokerageOrderID", "Brokerage Order ID"),
            "order_reference": _get_value(row, "OrderReference", "Order Reference"),
            "exch_order_id": _get_value(row, "ExchOrderID", "Exchange Order ID"),
            "ext_exec_id": _get_value(row, "ExtExecID", "External Exec ID"),
            "order_time": to_iso_datetime(_get_value(row, "OrderTime")),
            "open_date_time": to_iso_datetime(_get_value(row, "OpenDateTime", "Open Date/Time")),
            "holding_period_date_time": to_iso_datetime(
                _get_value(row, "HoldingPeriodDateTime", "Holding Period Date/Time")
            ),
            "when_realized": to_iso_datetime(_get_value(row, "WhenRealized")),
            "when_reopened": to_iso_datetime(_get_value(row, "WhenReopened")),
            "order_type": _get_value(row, "OrderType"),
            "trader_id": _get_value(row, "TraderID", "Trader Id"),
            "is_api_order": to_bool(_get_value(row, "IsAPIOrder", "Is API Order")),
            "accrued_interest": _get_number(row, "AccruedInterest"),
            "initial_investment": _get_number(row, "InitialInvestment"),
            "unbc_total_commission": _get_number(unbc_row, "TotalCommission", "Total Commission"),
            "unbc_broker_execution_charge": _get_number(
                unbc_row,
                "BrokerExecutionCharge",
                "Broker Execution Charge",
            ),
            "unbc_broker_clearing_charge": _get_number(
                unbc_row,
                "BrokerClearingCharge",
                "Broker Clearing Charge",
            ),
            "unbc_third_party_execution_charge": _get_number(
                unbc_row,
                "ThirdPartyExecutionCharge",
                "Third Party Execution Charge",
            ),
            "unbc_third_party_clearing_charge": _get_number(
                unbc_row,
                "ThirdPartyClearingCharge",
                "Third Party Clearing Charge",
            ),
            "unbc_third_party_regulatory_charge": _get_number(
                unbc_row,
                "ThirdPartyRegulatoryCharge",
                "Third Party Regulatory Charge",
            ),
            "unbc_reg_finra_trading_activity_fee": _get_number(
                unbc_row,
                "RegFINRATradingActivityFee",
                "FINRA Trading Activity Fee",
            ),
            "unbc_reg_section31_transaction_fee": _get_number(
                unbc_row,
                "RegSection31TransactionFee",
                "Section31 Transaction Fee",
            ),
            "unbc_reg_other": _get_number(unbc_row, "RegOther", "Regulatory Other"),
            "unbc_other": _get_number(unbc_row, "Other"),
            "source_file_name": _coerce_source_file_name(statement.source_file),
            "source_query_type": source_query_type,
            "ingested_at": utc_now_iso(),
        }
        documents.append(_clean_document(document))

    return documents
