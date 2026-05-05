from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.trades import TradeItem, TradeListResponse, TradeSummaryResponse
from app.utils.dates import parse_date
from app.utils.es_query_builder import (
    build_date_range_filter,
    build_search_body,
    build_sort_clause,
    build_term_filter,
)
from app.utils.pagination import build_pagination_info

TRADE_SORT_FIELDS = {
    "date_time": "date_time",
    "trade_date": "trade_date",
    "symbol": "symbol",
    "quantity": "quantity",
    "trade_price": "trade_price",
    "proceeds": "proceeds",
    "ib_commission": "ib_commission",
    "fifo_pnl_realized": "fifo_pnl_realized",
}


class TradeService:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def list_trades(
        self,
        start_date: str | None,
        end_date: str | None,
        symbol: str | None,
        asset_class: str | None,
        buy_sell: str | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> TradeListResponse:
        effective_start, effective_end = self._resolve_date_window(start_date, end_date)
        filters = self._build_filters(effective_start, effective_end, symbol, asset_class, buy_sell)
        body = build_search_body(
            filters=filters,
            sort=build_sort_clause(sort_by, sort_order, TRADE_SORT_FIELDS),
            page=page,
            page_size=page_size,
            source_fields=[
                "account_id",
                "trade_date",
                "date_time",
                "currency",
                "symbol",
                "description",
                "asset_class",
                "buy_sell",
                "quantity",
                "trade_price",
                "proceeds",
                "ib_commission",
                "net_cash",
                "fifo_pnl_realized",
                "exchange",
                "order_type",
                "transaction_id",
                "trade_id",
            ],
        )
        response = self.es_client.search(index=self.settings.es_trade_index, body=body)
        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        items = [TradeItem(**hit["_source"]) for hit in hits.get("hits", [])]
        return TradeListResponse(
            items=items,
            pagination=build_pagination_info(page, min(page_size, 200), total),
        )

    def summarize_trades(
        self,
        start_date: str | None,
        end_date: str | None,
        symbol: str | None,
        asset_class: str | None,
        buy_sell: str | None,
    ) -> TradeSummaryResponse:
        effective_start, effective_end = self._resolve_date_window(start_date, end_date)
        filters = self._build_filters(effective_start, effective_end, symbol, asset_class, buy_sell)
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "size": 0,
                "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                "aggs": {
                    "buy_count": {"filter": {"term": {"buy_sell": "BUY"}}},
                    "sell_count": {"filter": {"term": {"buy_sell": "SELL"}}},
                    "total_commission": {"sum": {"field": "ib_commission"}},
                    "total_realized_pnl": {"sum": {"field": "fifo_pnl_realized"}},
                    "total_proceeds": {"sum": {"field": "proceeds"}},
                    "symbols_count": {"cardinality": {"field": "symbol"}},
                },
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        aggs = response.get("aggregations", {})
        return TradeSummaryResponse(
            trade_count=hits.get("total", {}).get("value", 0),
            buy_count=aggs.get("buy_count", {}).get("doc_count", 0),
            sell_count=aggs.get("sell_count", {}).get("doc_count", 0),
            total_commission=float(aggs.get("total_commission", {}).get("value") or 0.0),
            total_realized_pnl=float(aggs.get("total_realized_pnl", {}).get("value") or 0.0),
            total_proceeds=float(aggs.get("total_proceeds", {}).get("value") or 0.0),
            symbols_count=int(aggs.get("symbols_count", {}).get("value") or 0),
        )

    def _resolve_date_window(self, start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
        parsed_start = parse_date(start_date)
        parsed_end = parse_date(end_date)

        # Default to full history so newly imported historical trades are visible immediately.
        if parsed_start is None and parsed_end is None:
            return None, None

        effective_end = parsed_end
        if effective_end is None:
            effective_end = self._get_latest_trade_date()

        return (
            parsed_start.isoformat() if parsed_start else None,
            effective_end.isoformat() if effective_end else None,
        )

    def _build_filters(
        self,
        start_date: str | None,
        end_date: str | None,
        symbol: str | None,
        asset_class: str | None,
        buy_sell: str | None,
    ) -> list[dict]:
        filters = [
            build_date_range_filter("trade_date", start_date, end_date),
            build_term_filter("symbol", symbol),
            build_term_filter("asset_class", asset_class),
            build_term_filter("buy_sell", buy_sell),
        ]
        return [item for item in filters if item]

    def _get_latest_trade_date(self):
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={"size": 1, "sort": [{"trade_date": {"order": "desc"}}], "_source": ["trade_date"]},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return parse_date(hits[0]["_source"]["trade_date"])
