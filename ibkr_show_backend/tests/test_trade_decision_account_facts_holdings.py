from types import SimpleNamespace

from app.services.trade_decision_account_facts import TradeDecisionAccountFactsBuilder


class FakeElasticsearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append((index, body))
        if index == "accounts":
            return {
                "hits": {
                    "hits": [
                        {"_source": {"report_date": "2026-06-12", "total_equity": "100000", "cash": "1000"}}
                    ]
                }
            }
        if index == "positions":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "symbol": "AAPL",
                                "quantity": "10",
                                "mark_price": "200",
                                "position_value": "2000",
                                "percent_of_nav": "2",
                                "average_cost_price": "150",
                                "cost_basis_money": "1500",
                                "total_unrealized_pnl": "500",
                                "unrealized_pnl_percent": "33.3333",
                            }
                        },
                        {
                            "_source": {
                                "symbol": "MSFT",
                                "quantity": "5",
                                "mark_price": "400",
                                "position_value": "2000",
                                "percent_of_nav": "2",
                                "average_cost_price": "350",
                                "cost_basis_money": "1750",
                                "total_unrealized_pnl": "250",
                                "unrealized_pnl_percent": "14.2857",
                            }
                        },
                    ]
                }
            }
        if index == "reviews":
            assert body["size"] == 0
            return {
                "aggregations": {
                    "by_symbol": {
                        "buckets": [
                            {
                                "key": "AAPL.US",
                                "latest": {
                                    "hits": {
                                        "hits": [
                                            {"_source": {"id": "review-aapl", "overall_score": 82, "rating": "good"}}
                                        ]
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        if index == "decisions":
            assert body["size"] == 0
            return {
                "aggregations": {
                    "by_symbol": {
                        "buckets": [
                            {
                                "key": "AAPL.US",
                                "latest": {
                                    "hits": {
                                        "hits": [
                                            {"_source": {"id": "decision-aapl", "action": "hold", "overall_score": 75}}
                                        ]
                                    }
                                },
                            },
                            {
                                "key": "MSFT.US",
                                "latest": {
                                    "hits": {
                                        "hits": [
                                            {"_source": {"id": "decision-msft", "action": "watchlist", "overall_score": 60}}
                                        ]
                                    }
                                },
                            },
                        ]
                    }
                }
            }
        raise AssertionError(f"unexpected index {index}")


def test_list_current_holdings_fetches_latest_review_and_decision_in_bulk() -> None:
    es_client = FakeElasticsearchClient()
    settings = SimpleNamespace(
        es_account_index="accounts",
        es_position_index="positions",
        es_trade_review_index="reviews",
        es_trade_decision_index="decisions",
    )
    builder = TradeDecisionAccountFactsBuilder(es_client, settings)

    holdings = builder.list_current_holdings()

    assert len(holdings) == 2
    assert holdings[0]["normalized_symbol"] == "AAPL.US"
    assert holdings[0]["latest_review_score"] == 82
    assert holdings[0]["latest_decision"] == "hold"
    assert holdings[1]["normalized_symbol"] == "MSFT.US"
    assert holdings[1]["latest_review_score"] is None
    assert holdings[1]["latest_decision"] == "watchlist"
    assert [index for index, _body in es_client.calls].count("reviews") == 1
    assert [index for index, _body in es_client.calls].count("decisions") == 1
