from dataclasses import dataclass

from app.services.trade_service import TradeService


@dataclass
class DummySettings:
    es_trade_index: str = "trade-index"


class StubESClient:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        return self._responses.pop(0)


def test_summarize_trades_applies_buy_sell_filter() -> None:
    es_client = StubESClient(
        responses=[
            {
                "hits": {"total": {"value": 3}},
                "aggregations": {
                    "buy_count": {"doc_count": 3},
                    "sell_count": {"doc_count": 0},
                    "total_commission": {"value": -1.2},
                    "total_realized_pnl": {"value": 45.6},
                    "total_proceeds": {"value": 1234.5},
                    "symbols_count": {"value": 2},
                },
            }
        ]
    )

    service = TradeService(es_client, DummySettings())
    summary = service.summarize_trades(
        start_date="2026-04-01",
        end_date="2026-04-30",
        symbol="AMD",
        asset_class="STK",
        buy_sell="BUY",
    )

    assert summary.trade_count == 3
    assert summary.buy_count == 3
    filters = es_client.calls[0]["body"]["query"]["bool"]["filter"]
    assert {"term": {"symbol": "AMD"}} in filters
    assert {"term": {"asset_class": "STK"}} in filters
    assert {"term": {"buy_sell": "BUY"}} in filters
