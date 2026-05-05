from dataclasses import dataclass

import pytest

from app.services.account_service import AccountService


@dataclass
class DummySettings:
    es_account_index: str = "account-index"
    es_trade_index: str = "trade-index"
    es_position_index: str = "position-index"


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


def test_get_overview_recomputes_dashboard_pnl_from_trade_and_position_indices() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-17",
                                "currency": "USD",
                                "total_equity": 100.0,
                                "fifo_total_realized_pnl": 0.0,
                                "fifo_total_unrealized_pnl": 999.0,
                                "fifo_total_pnl": 999.0,
                            }
                        },
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-04-16",
                                "currency": "USD",
                                "total_equity": 90.0,
                            }
                        },
                    ]
                }
            },
            {"aggregations": {"total_realized_pnl": {"value": 123.45}}},
            {"aggregations": {"total_unrealized_pnl": {"value": 67.89}}},
            {
                "hits": {
                    "hits": [
                        {"_source": {"report_date": "2026-01-02", "cnav_twr": 1.0}},
                        {"_source": {"report_date": "2026-04-17", "cnav_twr": -0.5}},
                    ]
                }
            },
            {"aggregations": {"total_realized_pnl": {"value": 100.0}}},
            {"aggregations": {"total_unrealized_pnl": {"value": 50.0}}},
        ]
    )

    service = AccountService(es_client, DummySettings())
    overview = service.get_overview()

    assert overview is not None
    assert overview.fifo_total_realized_pnl == 123.45
    assert overview.fifo_total_unrealized_pnl == 67.89
    assert overview.fifo_total_pnl == 191.34
    assert overview.total_equity_delta is not None
    assert overview.total_equity_delta.amount_change == 10.0
    assert overview.total_equity_delta.percent_change == 10.0 / 90.0 * 100
    assert overview.fifo_total_realized_pnl_delta is not None
    assert overview.fifo_total_realized_pnl_delta.amount_change == pytest.approx(23.45)
    assert overview.fifo_total_unrealized_pnl_delta is not None
    assert overview.fifo_total_unrealized_pnl_delta.amount_change == pytest.approx(17.89)
    assert overview.fifo_total_pnl_delta is not None
    assert overview.fifo_total_pnl_delta.amount_change == pytest.approx(41.34)
    assert overview.ytd_twr == pytest.approx(0.495)

    trade_call = es_client.multi_calls[0][0]
    assert trade_call["index"] == "trade-index"
    assert trade_call["body"]["query"]["bool"]["filter"] == [
        {"term": {"account_id": "U1"}},
        {"range": {"trade_date": {"lte": "2026-04-17"}}},
    ]

    position_call = es_client.multi_calls[0][1]
    assert position_call["index"] == "position-index"
    assert position_call["body"]["query"]["bool"]["filter"] == [
        {"term": {"account_id": "U1"}},
        {"term": {"report_date": "2026-04-17"}},
    ]

    ytd_twr_call = es_client.multi_calls[0][2]
    assert ytd_twr_call["index"] == "account-index"
    assert ytd_twr_call["body"]["query"]["bool"]["filter"] == [
        {"term": {"account_id": "U1"}},
        {"range": {"report_date": {"gte": "2026-01-01", "lte": "2026-04-17"}}},
    ]


def test_get_overview_returns_cached_payload_without_querying_es() -> None:
    cache_client = StubCacheClient(
        payload={
            "account_id": "U1",
            "report_date": "2026-04-17",
            "currency": "USD",
            "total_equity": 100.0,
            "fifo_total_realized_pnl": 1.0,
            "fifo_total_unrealized_pnl": 2.0,
            "fifo_total_pnl": 3.0,
        }
    )

    service = AccountService(StubESClient(responses=[]), DummySettings(), cache_client)
    overview = service.get_overview()

    assert overview is not None
    assert overview.account_id == "U1"
    assert overview.fifo_total_pnl == 3.0
    assert cache_client.get_calls == ["account-overview"]
    assert cache_client.set_calls == []
