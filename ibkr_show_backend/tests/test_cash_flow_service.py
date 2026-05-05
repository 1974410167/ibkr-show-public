from dataclasses import dataclass

from app.services.cash_flow_service import CashFlowService


@dataclass
class DummySettings:
    es_cash_flow_index: str = "cash-flow-index"


class StubESClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        return self.response


def test_summarize_cash_flows_groups_amounts_by_currency() -> None:
    es_client = StubESClient(
        {
            "hits": {"total": {"value": 4}},
            "aggregations": {
                "deposit_count": {"doc_count": 3},
                "withdrawal_count": {"doc_count": 1},
                "deposit_only_amount": {"amount": {"value": 300.0}},
                "withdrawal_only_amount": {"amount": {"value": -40.0}},
                "by_currency": {
                    "buckets": [
                        {
                            "key": "USD",
                            "doc_count": 1,
                            "deposit_count": {"doc_count": 0},
                            "withdrawal_count": {"doc_count": 1},
                            "deposit_only_amount": {"amount": {"value": 0.0}},
                            "withdrawal_only_amount": {"amount": {"value": -40.0}},
                        },
                        {
                            "key": "HKD",
                            "doc_count": 3,
                            "deposit_count": {"doc_count": 3},
                            "withdrawal_count": {"doc_count": 0},
                            "deposit_only_amount": {"amount": {"value": 300.0}},
                            "withdrawal_only_amount": {"amount": {"value": 0.0}},
                        },
                    ]
                },
            },
        }
    )

    service = CashFlowService(es_client, DummySettings())
    summary = service.summarize_cash_flows(None, None, None, None)

    assert summary.record_count == 4
    assert summary.deposit_count == 3
    assert summary.withdrawal_count == 1
    assert summary.total_deposit_amount is None
    assert summary.total_withdrawal_amount is None
    assert summary.net_amount is None
    assert [item.currency for item in summary.by_currency] == ["HKD", "USD"]
    assert summary.by_currency[0].net_amount == 300.0
    assert summary.by_currency[1].net_amount == -40.0

    assert es_client.calls[0]["index"] == "cash-flow-index"
    assert {"term": {"flow_type": "Deposits/Withdrawals"}} in es_client.calls[0]["body"]["query"]["bool"]["filter"]


def test_list_cash_flows_only_queries_deposit_withdrawal_records() -> None:
    es_client = StubESClient({"hits": {"total": {"value": 0}, "hits": []}})

    service = CashFlowService(es_client, DummySettings())
    response = service.list_cash_flows(None, None, None, None, "date_time", "desc", 1, 20)

    assert response.items == []
    assert {"term": {"flow_type": "Deposits/Withdrawals"}} in es_client.calls[0]["body"]["query"]["bool"]["filter"]
