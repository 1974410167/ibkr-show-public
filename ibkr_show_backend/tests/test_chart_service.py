from dataclasses import dataclass

import pytest

from app.services.chart_service import ChartService


@dataclass
class DummySettings:
    es_account_index: str = "account-index"
    es_cash_flow_index: str = "cash-flow-index"
    es_trade_index: str = "trade-index"
    es_position_index: str = "position-index"


class StubESClient:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        return self._responses.pop(0)


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


def test_get_equity_curve_builds_equity_pnl_and_net_cost_series() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-17"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-04-15", "total_equity": 100.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-16", "total_equity": 130.000001}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-17", "total_equity": 150.0, "cnav_mtm": -2.0, "cnav_twr": -1.2}},
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "date_time": "2026-04-15T00:00:00",
                                "settle_date": "2026-04-15",
                                "report_date": "2026-04-15",
                                "amount_in_base": 80.0,
                            }
                        },
                        {
                            "_source": {
                                "date_time": "2026-04-16T00:00:00",
                                "settle_date": "2026-04-16",
                                "report_date": "2026-04-16",
                                "amount_in_base": 20.0,
                            }
                        },
                        {
                            "_source": {
                                "date_time": "2026-04-17T00:00:00",
                                "settle_date": "2026-04-17",
                                "report_date": "2026-04-17",
                                "amount_in_base": 10.0,
                            }
                        },
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "trade_date": "2026-04-15",
                                "fifo_pnl_realized": 12.0,
                            }
                        },
                        {
                            "_source": {
                                "trade_date": "2026-04-17",
                                "fifo_pnl_realized": 8.0,
                            }
                        },
                    ]
                }
            },
        ]
    )

    service = ChartService(es_client, DummySettings())
    response = service.get_equity_curve(None, None)

    assert [item.report_date for item in response.items] == ["2026-04-15", "2026-04-16", "2026-04-17"]
    assert [item.total_equity for item in response.items] == [100.0, 130.0, 150.0]
    assert [item.net_cost for item in response.items] == [80.0, 100.0, 110.0]
    assert [item.total_pnl for item in response.items] == pytest.approx([20.0, 30.0, 40.0])
    assert [item.realized_pnl for item in response.items] == [12.0, 12.0, 20.0]
    assert response.items[0].daily_mtm is None
    assert response.items[1].daily_mtm == 10.0
    assert response.items[2].daily_mtm == pytest.approx(-2.0)
    assert response.items[0].daily_twr is None
    assert response.items[1].daily_twr == 10.0
    assert response.items[2].daily_twr == pytest.approx(-1.2)
    assert {"term": {"flow_type": "Deposits/Withdrawals"}} in es_client.calls[2]["body"]["query"]["bool"]["filter"]


def test_get_equity_curve_drops_near_zero_inferred_daily_pnl() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-03"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-04-02", "total_equity": 59062.647184219}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-03", "total_equity": 59062.647186383}},
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )

    service = ChartService(es_client, DummySettings())
    response = service.get_equity_curve("2026-04-02", "2026-04-03")

    assert [item.daily_mtm for item in response.items] == [None, 0.0]
    assert [item.daily_twr for item in response.items] == [None, 0.0]


def test_get_equity_curve_aligns_net_cost_to_settle_date() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-01-02"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2025-12-29", "total_equity": 43114.89}},
                        {"_source": {"account_id": "U1", "report_date": "2025-12-30", "total_equity": 51878.12}},
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "date_time": "2025-12-29T21:35:54",
                                "settle_date": "2025-12-30",
                                "report_date": "2025-12-30",
                                "amount_in_base": 8581.2,
                            }
                        }
                    ]
                }
            },
            {"hits": {"hits": []}},
        ]
    )

    service = ChartService(es_client, DummySettings())
    response = service.get_equity_curve("2025-12-29", "2026-01-02")

    assert [item.report_date for item in response.items] == ["2025-12-29", "2025-12-30"]
    assert [item.net_cost for item in response.items] == [0.0, 8581.2]
    assert [round(item.total_pnl or 0.0, 2) for item in response.items] == [43114.89, 43296.92]


def test_get_equity_curve_only_keeps_daily_metrics_for_latest_calendar_month() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-02"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-03-31", "total_equity": 100.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-01", "total_equity": 110.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-02", "total_equity": 120.0}},
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )

    service = ChartService(es_client, DummySettings())
    response = service.get_equity_curve("2026-03-31", "2026-04-02")

    assert [item.report_date for item in response.items] == ["2026-03-31", "2026-04-01", "2026-04-02"]
    assert response.items[0].daily_mtm is None
    assert response.items[0].daily_twr is None
    assert response.items[1].daily_mtm == 10.0
    assert response.items[1].daily_twr == 10.0
    assert response.items[2].daily_mtm == 10.0
    assert response.items[2].daily_twr == 9.09


def test_get_equity_curve_returns_cached_payload_without_querying_es() -> None:
    cache_client = StubCacheClient(
        payload={
            "items": [
                {
                    "report_date": "2026-04-17",
                    "total_equity": 150.0,
                    "total_pnl": 40.0,
                    "net_cost": 110.0,
                    "realized_pnl": 20.0,
                }
            ]
        }
    )

    service = ChartService(StubESClient(responses=[]), DummySettings(), cache_client)
    response = service.get_equity_curve("2026-01-01", "2026-04-17")

    assert [item.report_date for item in response.items] == ["2026-04-17"]
    assert cache_client.get_calls == ["equity-curve:start=2026-01-01:end=2026-04-17"]
    assert cache_client.set_calls == []


def test_get_performance_calendar_month_view_returns_full_month_items() -> None:
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-21"}}]}},
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-17"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-04-17", "total_equity": 100.0, "cnav_mtm": 3.0, "cnav_twr": 3.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-20", "total_equity": 98.0, "cnav_mtm": -2.0, "cnav_twr": -2.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-04-21", "total_equity": 101.0, "cnav_mtm": 3.0, "cnav_twr": 3.06}},
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )

    service = ChartService(es_client, DummySettings())
    response = service.get_performance_calendar(view="month", anchor="2026-04")

    assert response.view == "month"
    assert response.anchor == "2026-04"
    assert response.latest_anchor == "2026-04"
    assert response.earliest_anchor == "2026-04"
    assert response.previous_anchor is None
    assert response.next_anchor is None
    assert len(response.items) == 30
    assert response.items[16].label == "17"
    assert response.items[16].pnl == 3.0
    assert response.items[18].pnl is None
    assert response.items[19].pnl == -2.0
    assert response.summary.positive_periods == 2
    assert response.summary.negative_periods == 1
    assert response.summary.total_pnl == 4.0


def test_get_performance_calendar_year_and_all_years_views_aggregate_periods() -> None:
    year_es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-21"}}]}},
            {"hits": {"hits": [{"_source": {"report_date": "2025-12-31"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-01-02", "total_equity": 101.0, "cnav_mtm": 1.0, "cnav_twr": 1.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-01-03", "total_equity": 103.0, "cnav_mtm": 2.0, "cnav_twr": 2.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-02-01", "total_equity": 102.0, "cnav_mtm": -1.0, "cnav_twr": -0.97}},
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )
    year_service = ChartService(year_es_client, DummySettings())
    year_response = year_service.get_performance_calendar(view="year", anchor="2026")

    assert year_response.view == "year"
    assert year_response.anchor == "2026"
    assert year_response.earliest_anchor == "2025"
    assert len(year_response.items) == 12
    assert year_response.items[0].label == "1月"
    assert year_response.items[0].pnl == 3.0
    assert year_response.items[1].pnl == -1.0
    assert year_response.items[2].pnl is None
    assert year_response.summary.positive_periods == 1
    assert year_response.summary.negative_periods == 1
    assert year_response.summary.total_pnl == 2.0

    all_years_es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-04-21"}}]}},
            {"hits": {"hits": [{"_source": {"report_date": "2025-12-31"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2025-12-31", "total_equity": 100.0, "cnav_mtm": 4.0, "cnav_twr": 4.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-01-02", "total_equity": 101.0, "cnav_mtm": 1.0, "cnav_twr": 1.0}},
                        {"_source": {"account_id": "U1", "report_date": "2026-02-01", "total_equity": 99.0, "cnav_mtm": -2.0, "cnav_twr": -1.98}},
                    ]
                }
            },
            {"hits": {"hits": []}},
        ]
    )
    all_years_service = ChartService(all_years_es_client, DummySettings())
    all_years_response = all_years_service.get_performance_calendar(view="all-years", anchor=None)

    assert all_years_response.view == "all-years"
    assert all_years_response.earliest_anchor == "2025"
    assert [item.label for item in all_years_response.items] == ["2025年", "2026年"]
    assert [item.pnl for item in all_years_response.items] == [4.0, -1.0]
    assert all_years_response.summary.positive_periods == 1
    assert all_years_response.summary.negative_periods == 1


def test_get_performance_calendar_ignores_stale_cached_payload_without_earliest_anchor() -> None:
    cache_client = StubCacheClient(
        payload={
            "view": "month",
            "anchor": "2026-05",
            "latest_anchor": "2026-05",
            "items": [],
            "summary": {
                "positive_periods": 0,
                "negative_periods": 0,
                "total_pnl": None,
                "periods_with_data": 0,
            },
        }
    )
    es_client = StubESClient(
        responses=[
            {"hits": {"hits": [{"_source": {"report_date": "2026-05-01"}}]}},
            {"hits": {"hits": [{"_source": {"report_date": "2024-10-01"}}]}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"account_id": "U1", "report_date": "2026-05-01", "total_equity": 101.0, "cnav_mtm": 1.0, "cnav_twr": 1.0}},
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )

    service = ChartService(es_client, DummySettings(), cache_client)
    response = service.get_performance_calendar(view="month", anchor="2026-05")

    assert response.earliest_anchor == "2024-10"
    assert cache_client.get_calls == ["performance-calendar:view=month:anchor=2026-05"]
    assert len(cache_client.set_calls) == 1
