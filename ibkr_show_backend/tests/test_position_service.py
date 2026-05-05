from dataclasses import dataclass

from app.services.position_service import PositionService


@dataclass
class DummySettings:
    es_position_index: str = "position-index"
    es_trade_index: str = "trade-index"
    es_price_history_index: str = "price-index"


class StubESClient:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.multi_calls: list[list[dict]] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        return self._responses.pop(0)

    def multi_search(self, searches: list[tuple[str, dict]]) -> list[dict]:
        batch = [{"index": index, "body": body} for index, body in searches]
        self.multi_calls.append(batch)
        size = len(searches)
        responses = self._responses[:size]
        self._responses = self._responses[size:]
        return responses


class StubCacheClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, dict]] = []

    def build_key(self, *parts: str) -> str:
        return ":".join(parts)

    def get_json(self, key: str) -> dict | None:
        self.get_calls.append(key)
        return self.payload

    def set_json(self, key: str, value: dict) -> None:
        self.set_calls.append((key, value))


def test_list_positions_returns_new_detail_fields_and_supports_new_sort_key() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-17"}}]}},
            {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-17",
                                "symbol": "AAPL",
                                "asset_class": "STK",
                                "average_cost_price": 175.0,
                                "cost_basis_money": 17500.0,
                                "total_realized_pnl": 120.5,
                                "realized_pnl_percent": 0.69,
                                "total_unrealized_pnl": 80.25,
                                "unrealized_pnl_percent": 0.46,
                                "previous_day_change_percent": 2.7,
                            }
                        }
                    ],
                }
            },
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.list_positions(
        report_date=None,
        symbol=None,
        asset_class=None,
        sort_by="previous_day_change_percent",
        sort_order="desc",
        page=1,
        page_size=20,
    )

    assert response.items[0].symbol == "AAPL"
    assert response.items[0].average_cost_price == 175.0
    assert response.items[0].total_realized_pnl == 120.5
    assert response.items[0].realized_pnl_percent == 0.69
    assert response.items[0].unrealized_pnl_percent == 0.46
    assert response.items[0].previous_day_change_percent == 2.7

    positions_call = es_client.calls[1]
    assert positions_call["index"] == "position-index"
    assert positions_call["body"]["sort"] == [{"previous_day_change_percent": {"order": "desc", "missing": "_last"}}]
    assert len(es_client.calls) == 2


def test_get_position_detail_returns_synthetic_bars_and_trade_markers() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "symbol": "AMD",
                                "description": "ADVANCED MICRO DEVICES",
                                "asset_class": "STK",
                                "report_date": "2026-04-16",
                                "open_price": 149.0,
                                "high_price": 155.0,
                                "low_price": 149.0,
                                "close_price": 155.0,
                            }
                        },
                        {
                            "_source": {
                                "symbol": "AMD",
                                "description": "ADVANCED MICRO DEVICES",
                                "asset_class": "STK",
                                "report_date": "2026-04-16",
                                "open_price": 150.0,
                                "high_price": 156.0,
                                "low_price": 151.0,
                                "close_price": 151.0,
                            }
                        },
                    ]
                }
            },
            {"hits": {"hits": []}},
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "symbol": "AMD",
                                "description": "ADVANCED MICRO DEVICES",
                                "asset_class": "STK",
                                "trade_date": "2026-04-17",
                                "date_time": "2026-04-17T20:00:00Z",
                                "buy_sell": "BUY",
                                "quantity": 6.0,
                                "trade_price": 156.0,
                                "fifo_pnl_realized": 0.0,
                            }
                        }
                    ]
                }
            },
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.get_position_detail(symbol="AMD", asset_class="STK")

    assert response.symbol == "AMD"
    assert len(response.bars) == 2
    assert response.bars[1].high_price == 156.0
    assert response.bars[1].low_price == 151.0
    assert response.trades[0].buy_sell == "BUY"
    assert es_client.multi_calls[0][0]["index"] == "price-index"
    assert es_client.multi_calls[0][1]["index"] == "position-index"
    assert es_client.multi_calls[0][2]["index"] == "trade-index"


def test_get_positions_summary_uses_snapshot_aggregations() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-17"}}]}},
            {
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {
                            "_source": {
                                "report_date": "2026-04-17",
                                "symbol": "AAPL",
                                "description": "Apple",
                                "asset_class": "STK",
                                "position_value": 1200.0,
                                "percent_of_nav": 12.0,
                            }
                        },
                        {
                            "_source": {
                                "report_date": "2026-04-17",
                                "symbol": "MSFT",
                                "description": "Microsoft",
                                "asset_class": "STK",
                                "position_value": 900.0,
                                "percent_of_nav": 9.0,
                            }
                        },
                    ]
                },
                "aggregations": {
                    "total_position_value": {"value": 2100.0},
                    "total_cost_basis_money": {"value": 1700.0},
                    "total_realized_pnl": {"value": 280.0},
                    "total_unrealized_pnl": {"value": 120.0},
                    "total_fifo_pnl": {"value": 400.0},
                    "asset_distribution": {
                        "buckets": [
                            {
                                "key": "STK",
                                "doc_count": 2,
                                "position_value": {"value": 2100.0},
                            },
                        ]
                    }
                }
            },
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.get_positions_summary(report_date=None, symbol=None, asset_class=None)

    assert response.total_realized_pnl == 280.0
    assert response.total_unrealized_pnl == 120.0
    assert response.total_positions == 2


def test_list_positions_backfills_realized_pnl_only_when_snapshot_field_missing() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-17",
                                "symbol": "AAPL",
                                "asset_class": "STK",
                                "cost_basis_money": 17500.0,
                                "total_realized_pnl": None,
                                "realized_pnl_percent": None,
                            }
                        }
                    ],
                }
            },
            {
                "aggregations": {
                    "by_position": {
                        "buckets": [
                            {
                                "key": {
                                    "account_id": "U1",
                                    "asset_class": "STK",
                                    "symbol": "AAPL",
                                },
                                "total_realized_pnl": {"value": 456.78},
                            }
                        ]
                    }
                }
            },
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.list_positions(
        report_date="2026-04-17",
        symbol=None,
        asset_class=None,
        sort_by="position_value",
        sort_order="desc",
        page=1,
        page_size=20,
    )

    assert response.items[0].total_realized_pnl == 456.78
    assert response.items[0].realized_pnl_percent == 456.78 / 17500 * 100
    assert es_client.calls[1]["index"] == "trade-index"


def test_list_positions_can_embed_summary_without_second_position_query() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-17",
                                "symbol": "AAPL",
                                "description": "Apple",
                                "asset_class": "STK",
                                "position_value": 1200.0,
                                "percent_of_nav": 12.0,
                                "cost_basis_money": 1000.0,
                                "total_realized_pnl": 10.0,
                                "realized_pnl_percent": 1.0,
                                "total_unrealized_pnl": 80.0,
                                "total_fifo_pnl": 90.0,
                            }
                        },
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-17",
                                "symbol": "MSFT",
                                "description": "Microsoft",
                                "asset_class": "STK",
                                "position_value": 900.0,
                                "percent_of_nav": 9.0,
                                "cost_basis_money": 700.0,
                                "total_realized_pnl": -20.0,
                                "realized_pnl_percent": -2.0,
                                "total_unrealized_pnl": 40.0,
                                "total_fifo_pnl": 20.0,
                            }
                        },
                    ],
                },
                "aggregations": {
                    "total_position_value": {"value": 2100.0},
                    "total_cost_basis_money": {"value": 1700.0},
                    "total_realized_pnl": {"value": -10.0},
                    "total_unrealized_pnl": {"value": 120.0},
                    "total_fifo_pnl": {"value": 110.0},
                    "asset_distribution": {
                        "buckets": [
                            {
                                "key": "STK",
                                "doc_count": 2,
                                "position_value": {"value": 2100.0},
                            }
                        ]
                    },
                },
            }
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.list_positions(
        report_date="2026-04-17",
        symbol=None,
        asset_class=None,
        sort_by="position_value",
        sort_order="desc",
        page=1,
        page_size=20,
        include_summary=True,
    )

    assert response.summary is not None
    assert response.summary.total_positions == 2
    assert response.summary.total_position_value == 2100.0
    assert response.summary.top_positions[0].symbol == "AAPL"
    assert response.summary.asset_distribution[0].asset_class == "STK"
    assert "aggs" in es_client.calls[0]["body"]


def test_get_positions_summary_uses_hits_plus_aggregations_only() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {
                            "_source": {
                                "report_date": "2026-04-17",
                                "symbol": "AAPL",
                                "description": "Apple",
                                "asset_class": "STK",
                                "position_value": 1200.0,
                                "percent_of_nav": 12.0,
                            }
                        }
                    ],
                },
                "aggregations": {
                    "total_position_value": {"value": 1200.0},
                    "total_cost_basis_money": {"value": 1000.0},
                    "total_realized_pnl": {"value": 10.0},
                    "total_unrealized_pnl": {"value": 80.0},
                    "total_fifo_pnl": {"value": 90.0},
                    "asset_distribution": {
                        "buckets": [
                            {
                                "key": "STK",
                                "doc_count": 2,
                                "position_value": {"value": 1200.0},
                            }
                        ]
                    },
                },
            }
        ]
    )

    service = PositionService(es_client, DummySettings())
    response = service.get_positions_summary(report_date="2026-04-17", symbol=None, asset_class=None)

    assert response.total_positions == 2
    assert response.top_positions[0].symbol == "AAPL"
    assert len(es_client.calls) == 1


def test_list_positions_uses_cache_for_include_summary_requests() -> None:
    cache_client = StubCacheClient(
        payload={
            "items": [
                {
                    "account_id": "U1",
                    "report_date": "2026-04-17",
                    "symbol": "AAPL",
                    "asset_class": "STK",
                }
            ],
            "pagination": {
                "page": 1,
                "page_size": 20,
                "total": 1,
                "total_pages": 1,
                "has_next": False,
                "has_previous": False,
            },
            "summary": {
                "report_date": "2026-04-17",
                "total_positions": 1,
                "total_position_value": 1200.0,
                "total_cost_basis_money": 1000.0,
                "total_realized_pnl": 100.0,
                "total_unrealized_pnl": 100.0,
                "total_fifo_pnl": 200.0,
                "top_positions": [],
                "asset_distribution": [],
            },
        }
    )

    service = PositionService(StubESClient(responses=[]), DummySettings(), cache_client)
    response = service.list_positions(
        report_date="2026-04-17",
        symbol=None,
        asset_class=None,
        sort_by="position_value",
        sort_order="desc",
        page=1,
        page_size=20,
        include_summary=True,
    )

    assert response.summary is not None
    assert response.summary.total_positions == 1
    assert cache_client.get_calls == [
        "positions:report_date=2026-04-17:symbol=:asset_class=:sort_by=position_value:sort_order=desc:page=1:page_size=20:include_summary=1"
    ]
    assert cache_client.set_calls == []
