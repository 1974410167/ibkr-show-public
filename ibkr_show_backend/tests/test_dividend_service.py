from dataclasses import dataclass

from app.services.dividend_service import DividendService


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


def test_summarize_dividends_groups_amounts_by_currency() -> None:
    es_client = StubESClient(
        {
            "hits": {"total": {"value": 4}},
            "aggregations": {
                "dividend_count": {"doc_count": 3},
                "withholding_tax_count": {"doc_count": 1},
                "gross_dividend_amount": {"amount": {"value": 20.0}},
                "withholding_tax_amount": {"amount": {"value": -2.0}},
                "by_currency": {
                    "buckets": [
                        {
                            "key": "USD",
                            "doc_count": 4,
                            "dividend_count": {"doc_count": 3},
                            "withholding_tax_count": {"doc_count": 1},
                            "gross_dividend_amount": {"amount": {"value": 20.0}},
                            "withholding_tax_amount": {"amount": {"value": -2.0}},
                        }
                    ]
                },
            },
        }
    )

    service = DividendService(es_client, DummySettings())
    summary = service.summarize_dividends(None, None, None, None)

    assert summary.record_count == 4
    assert summary.dividend_count == 3
    assert summary.withholding_tax_count == 1
    assert summary.gross_dividend_amount == 20.0
    assert summary.withholding_tax_amount == -2.0
    assert summary.net_amount == 18.0
    assert es_client.calls[0]["index"] == "cash-flow-index"
    assert {"terms": {"flow_type": ["Dividends", "Ordinary Dividend", "Withholding Tax", "Payment In Lieu Of Dividends", "Payment In Lieu Of Dividend"]}} in es_client.calls[0]["body"]["query"]["bool"]["filter"]


def test_list_dividends_filters_by_symbol_and_dividend_flow_types() -> None:
    es_client = StubESClient(
        {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_source": {
                            "account_id": "U1",
                            "currency": "USD",
                            "symbol": "MSFT",
                            "amount": 14.56,
                            "flow_type": "Dividends",
                            "transaction_id": "DIV1",
                        }
                    }
                ],
            }
        }
    )

    service = DividendService(es_client, DummySettings())
    response = service.list_dividends(None, None, "usd", "msft", "date_time", "desc", 1, 20)

    assert response.items[0].symbol == "MSFT"
    filters = es_client.calls[0]["body"]["query"]["bool"]["filter"]
    assert {"term": {"currency": "USD"}} in filters
    assert {"term": {"symbol": "MSFT"}} in filters
