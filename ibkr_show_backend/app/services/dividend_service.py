from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.dividends import (
    DividendCurrencySummaryItem,
    DividendItem,
    DividendListResponse,
    DividendSummaryResponse,
)
from app.utils.dates import parse_date
from app.utils.es_query_builder import build_date_range_filter, build_search_body, build_sort_clause, build_term_filter
from app.utils.pagination import build_pagination_info

DIVIDEND_FLOW_TYPES = (
    "Dividends",
    "Ordinary Dividend",
    "Withholding Tax",
    "Payment In Lieu Of Dividends",
    "Payment In Lieu Of Dividend",
)
GROSS_DIVIDEND_FLOW_TYPES = (
    "Dividends",
    "Ordinary Dividend",
    "Payment In Lieu Of Dividends",
    "Payment In Lieu Of Dividend",
)
WITHHOLDING_TAX_FLOW_TYPE = "Withholding Tax"

DIVIDEND_SORT_FIELDS = {
    "date_time": "date_time",
    "ex_date": "ex_date",
    "amount": "amount",
    "symbol": "symbol",
}


class DividendService:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def list_dividends(
        self,
        start_date: str | None,
        end_date: str | None,
        currency: str | None,
        symbol: str | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> DividendListResponse:
        effective_start = parse_date(start_date)
        effective_end = parse_date(end_date)
        filters = self._build_filters(
            start_date=effective_start.isoformat() if effective_start else None,
            end_date=effective_end.isoformat() if effective_end else None,
            currency=currency,
            symbol=symbol,
        )
        body = build_search_body(
            filters=filters,
            sort=build_sort_clause(sort_by, sort_order, DIVIDEND_SORT_FIELDS),
            page=page,
            page_size=page_size,
            source_fields=[
                "account_id",
                "currency",
                "symbol",
                "description",
                "date_time",
                "settle_date",
                "amount",
                "flow_type",
                "dividend_type",
                "transaction_id",
                "report_date",
                "ex_date",
            ],
        )
        response = self.es_client.search(index=self.settings.es_cash_flow_index, body=body)
        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        items = [DividendItem(**hit["_source"]) for hit in hits.get("hits", [])]
        return DividendListResponse(
            items=items,
            pagination=build_pagination_info(page, min(page_size, 200), total),
        )

    def summarize_dividends(
        self,
        start_date: str | None,
        end_date: str | None,
        currency: str | None,
        symbol: str | None,
    ) -> DividendSummaryResponse:
        effective_start = parse_date(start_date)
        effective_end = parse_date(end_date)
        filters = self._build_filters(
            start_date=effective_start.isoformat() if effective_start else None,
            end_date=effective_end.isoformat() if effective_end else None,
            currency=currency,
            symbol=symbol,
        )
        response = self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "size": 0,
                "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                "aggs": {
                    "dividend_count": {"filter": {"terms": {"flow_type": list(GROSS_DIVIDEND_FLOW_TYPES)}}},
                    "withholding_tax_count": {"filter": {"term": {"flow_type": WITHHOLDING_TAX_FLOW_TYPE}}},
                    "gross_dividend_amount": {
                        "filter": {"terms": {"flow_type": list(GROSS_DIVIDEND_FLOW_TYPES)}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "withholding_tax_amount": {
                        "filter": {"term": {"flow_type": WITHHOLDING_TAX_FLOW_TYPE}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "by_currency": {
                        "terms": {"field": "currency", "size": 20},
                        "aggs": {
                            "dividend_count": {"filter": {"terms": {"flow_type": list(GROSS_DIVIDEND_FLOW_TYPES)}}},
                            "withholding_tax_count": {"filter": {"term": {"flow_type": WITHHOLDING_TAX_FLOW_TYPE}}},
                            "gross_dividend_amount": {
                                "filter": {"terms": {"flow_type": list(GROSS_DIVIDEND_FLOW_TYPES)}},
                                "aggs": {"amount": {"sum": {"field": "amount"}}},
                            },
                            "withholding_tax_amount": {
                                "filter": {"term": {"flow_type": WITHHOLDING_TAX_FLOW_TYPE}},
                                "aggs": {"amount": {"sum": {"field": "amount"}}},
                            },
                        },
                    },
                },
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        aggs = response.get("aggregations", {})
        by_currency = self._build_currency_summaries(aggs.get("by_currency", {}).get("buckets", []))

        gross_dividend_amount = float(aggs.get("gross_dividend_amount", {}).get("amount", {}).get("value") or 0.0)
        withholding_tax_amount = float(
            aggs.get("withholding_tax_amount", {}).get("amount", {}).get("value") or 0.0
        )
        net_amount = gross_dividend_amount + withholding_tax_amount

        mixed_currency_totals = len(by_currency) > 1 and currency is None
        return DividendSummaryResponse(
            record_count=hits.get("total", {}).get("value", 0),
            dividend_count=aggs.get("dividend_count", {}).get("doc_count", 0),
            withholding_tax_count=aggs.get("withholding_tax_count", {}).get("doc_count", 0),
            gross_dividend_amount=None if mixed_currency_totals else gross_dividend_amount,
            withholding_tax_amount=None if mixed_currency_totals else withholding_tax_amount,
            net_amount=None if mixed_currency_totals else net_amount,
            by_currency=by_currency,
        )

    def _build_filters(
        self,
        start_date: str | None,
        end_date: str | None,
        currency: str | None,
        symbol: str | None,
    ) -> list[dict]:
        return [
            item
            for item in [
            build_date_range_filter("date_time", start_date, end_date),
            {"terms": {"flow_type": list(DIVIDEND_FLOW_TYPES)}},
            build_term_filter("currency", currency.upper() if currency else None),
            build_term_filter("symbol", symbol.upper() if symbol else None),
        ]
            if item
        ]

    def _build_currency_summaries(self, buckets: list[dict]) -> list[DividendCurrencySummaryItem]:
        items: list[DividendCurrencySummaryItem] = []
        for bucket in buckets:
            gross_dividend_amount = float(
                bucket.get("gross_dividend_amount", {}).get("amount", {}).get("value") or 0.0
            )
            withholding_tax_amount = float(
                bucket.get("withholding_tax_amount", {}).get("amount", {}).get("value") or 0.0
            )
            items.append(
                DividendCurrencySummaryItem(
                    currency=bucket.get("key"),
                    record_count=int(bucket.get("doc_count") or 0),
                    dividend_count=int(bucket.get("dividend_count", {}).get("doc_count") or 0),
                    withholding_tax_count=int(bucket.get("withholding_tax_count", {}).get("doc_count") or 0),
                    gross_dividend_amount=gross_dividend_amount,
                    withholding_tax_amount=withholding_tax_amount,
                    net_amount=gross_dividend_amount + withholding_tax_amount,
                )
            )

        return sorted(items, key=lambda item: item.currency or "")
