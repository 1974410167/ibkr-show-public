from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.cash_flows import (
    CashFlowCurrencySummaryItem,
    CashFlowItem,
    CashFlowListResponse,
    CashFlowSummaryResponse,
)
from app.utils.dates import parse_date
from app.utils.es_query_builder import (
    build_date_range_filter,
    build_search_body,
    build_sort_clause,
    build_term_filter,
)
from app.utils.pagination import build_pagination_info

CASH_FLOW_SORT_FIELDS = {
    "date_time": "date_time",
    "settle_date": "settle_date",
    "amount": "amount",
    "currency": "currency",
    "flow_direction": "flow_direction",
}
DEPOSIT_WITHDRAWAL_FLOW_TYPE = "Deposits/Withdrawals"


class CashFlowService:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def list_cash_flows(
        self,
        start_date: str | None,
        end_date: str | None,
        currency: str | None,
        flow_direction: str | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> CashFlowListResponse:
        effective_start = parse_date(start_date)
        effective_end = parse_date(end_date)
        filters = [
            build_date_range_filter(
                "date_time",
                effective_start.isoformat() if effective_start else None,
                effective_end.isoformat() if effective_end else None,
            ),
            {"term": {"flow_type": DEPOSIT_WITHDRAWAL_FLOW_TYPE}},
            build_term_filter("currency", currency),
            build_term_filter("flow_direction", flow_direction),
        ]
        body = build_search_body(
            filters=[item for item in filters if item],
            sort=build_sort_clause(sort_by, sort_order, CASH_FLOW_SORT_FIELDS),
            page=page,
            page_size=page_size,
            source_fields=[
                "account_id",
                "currency",
                "description",
                "date_time",
                "settle_date",
                "available_for_trading_date",
                "amount",
                "flow_direction",
                "flow_type",
                "transaction_id",
                "report_date",
                "client_reference",
            ],
        )
        response = self.es_client.search(index=self.settings.es_cash_flow_index, body=body)
        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        items = [CashFlowItem(**hit["_source"]) for hit in hits.get("hits", [])]
        return CashFlowListResponse(
            items=items,
            pagination=build_pagination_info(page, min(page_size, 200), total),
        )

    def summarize_cash_flows(
        self,
        start_date: str | None,
        end_date: str | None,
        currency: str | None,
        flow_direction: str | None,
    ) -> CashFlowSummaryResponse:
        effective_start = parse_date(start_date)
        effective_end = parse_date(end_date)
        filters = [
            build_date_range_filter(
                "date_time",
                effective_start.isoformat() if effective_start else None,
                effective_end.isoformat() if effective_end else None,
            ),
            {"term": {"flow_type": DEPOSIT_WITHDRAWAL_FLOW_TYPE}},
            build_term_filter("currency", currency),
            build_term_filter("flow_direction", flow_direction),
        ]
        response = self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "size": 0,
                "query": {"bool": {"filter": [item for item in filters if item] or [{"match_all": {}}]}},
                "aggs": {
                    "deposit_count": {"filter": {"term": {"flow_direction": "deposit"}}},
                    "withdrawal_count": {"filter": {"term": {"flow_direction": "withdrawal"}}},
                    "total_deposit_amount": {"sum": {"field": "amount"}},
                    "deposit_only_amount": {
                        "filter": {"term": {"flow_direction": "deposit"}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "withdrawal_only_amount": {
                        "filter": {"term": {"flow_direction": "withdrawal"}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "by_currency": {
                        "terms": {"field": "currency", "size": 20},
                        "aggs": {
                            "deposit_count": {"filter": {"term": {"flow_direction": "deposit"}}},
                            "withdrawal_count": {"filter": {"term": {"flow_direction": "withdrawal"}}},
                            "deposit_only_amount": {
                                "filter": {"term": {"flow_direction": "deposit"}},
                                "aggs": {"amount": {"sum": {"field": "amount"}}},
                            },
                            "withdrawal_only_amount": {
                                "filter": {"term": {"flow_direction": "withdrawal"}},
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

        total_deposit_amount = float(
            aggs.get("deposit_only_amount", {}).get("amount", {}).get("value") or 0.0
        )
        total_withdrawal_amount = float(
            aggs.get("withdrawal_only_amount", {}).get("amount", {}).get("value") or 0.0
        )
        net_amount = total_deposit_amount + total_withdrawal_amount

        mixed_currency_totals = len(by_currency) > 1 and currency is None
        return CashFlowSummaryResponse(
            record_count=hits.get("total", {}).get("value", 0),
            deposit_count=aggs.get("deposit_count", {}).get("doc_count", 0),
            withdrawal_count=aggs.get("withdrawal_count", {}).get("doc_count", 0),
            total_deposit_amount=None if mixed_currency_totals else total_deposit_amount,
            total_withdrawal_amount=None if mixed_currency_totals else total_withdrawal_amount,
            net_amount=None if mixed_currency_totals else net_amount,
            by_currency=by_currency,
        )

    def _build_currency_summaries(self, buckets: list[dict]) -> list[CashFlowCurrencySummaryItem]:
        items: list[CashFlowCurrencySummaryItem] = []
        for bucket in buckets:
            deposit_amount = float(bucket.get("deposit_only_amount", {}).get("amount", {}).get("value") or 0.0)
            withdrawal_amount = float(
                bucket.get("withdrawal_only_amount", {}).get("amount", {}).get("value") or 0.0
            )
            items.append(
                CashFlowCurrencySummaryItem(
                    currency=bucket.get("key"),
                    record_count=int(bucket.get("doc_count") or 0),
                    deposit_count=int(bucket.get("deposit_count", {}).get("doc_count") or 0),
                    withdrawal_count=int(bucket.get("withdrawal_count", {}).get("doc_count") or 0),
                    total_deposit_amount=deposit_amount,
                    total_withdrawal_amount=withdrawal_amount,
                    net_amount=deposit_amount + withdrawal_amount,
                )
            )

        return sorted(items, key=lambda item: item.currency or "")
