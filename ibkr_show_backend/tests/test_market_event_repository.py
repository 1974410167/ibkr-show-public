from unittest.mock import MagicMock

from app.services.market_event_repository import MarketEventRepository


def test_list_sources_sorts_in_python_without_es_priority_sort() -> None:
    es_client = MagicMock()
    settings = MagicMock()
    settings.es_market_event_source_index = "test_sources"
    es_client.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "LONGBRIDGE", "_source": {"source_code": "LONGBRIDGE", "priority": "50"}},
                {"_id": "BLS", "_source": {"source_code": "BLS", "priority": ""}},
                {"_id": "BEA", "_source": {"source_code": "BEA", "priority": "10"}},
            ]
        }
    }
    repo = MarketEventRepository(es_client, settings)

    result = repo.list_sources()

    _, body = es_client.search.call_args.args
    assert "sort" not in body
    assert [item["source_code"] for item in result] == ["BEA", "LONGBRIDGE", "BLS"]


def test_update_source_does_not_write_es_metadata_id_into_document() -> None:
    es_client = MagicMock()
    settings = MagicMock()
    settings.es_market_event_source_index = "test_sources"
    es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "BLS",
                    "_source": {
                        "source_code": "BLS",
                        "priority": 10,
                        "last_check_status": None,
                    },
                }
            ]
        }
    }
    repo = MarketEventRepository(es_client, settings)

    repo.update_source("BLS", {"last_check_status": "SKIPPED"})

    _, kwargs = es_client.index_document.call_args
    assert kwargs["id"] == "BLS"
    assert "_id" not in kwargs["document"]
    assert kwargs["document"]["last_check_status"] == "SKIPPED"
