from __future__ import annotations

from dataclasses import dataclass

from app.clients.es_client import ESIndexNotFoundError
from app.services.trade_review_repository import (
    TRADE_REVIEW_INDEX_V2,
    TRADE_REVIEW_INDEX_V2_BODY,
    TradeReviewRepository,
)


@dataclass
class DummySettings:
    es_trade_review_index: str = "ibkr_trade_reviews_v1"


class StubESClient:
    def __init__(self) -> None:
        self.index_bodies: dict[str, dict] = {}
        self.documents: dict[str, dict[str, dict]] = {}
        self.indexed_calls: list[tuple[str, str, dict]] = []
        self.search_calls: list[tuple[str, dict]] = []
        self.missing_search_indexes: set[str] = set()

    def create_index_if_missing(self, index: str, body: dict) -> None:
        self.index_bodies[index] = body
        self.documents.setdefault(index, {})

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.indexed_calls.append((index, id, document))
        self.documents.setdefault(index, {})[id] = document
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        document = self.documents.get(index, {}).get(id)
        return {"_source": document} if document else None

    def search(self, index: str, body: dict) -> dict:
        if index in self.missing_search_indexes:
            raise ESIndexNotFoundError(index)
        self.search_calls.append((index, body))
        if body.get("aggs"):
            return self._search_aggregations(index)
        documents = list(self.documents.get(index, {}).values())
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        for item in filters:
            term = item.get("term")
            if not term:
                continue
            field, expected = next(iter(term.items()))
            documents = [doc for doc in documents if doc.get(field) == expected]
        documents.sort(key=lambda doc: doc.get("created_at") or "", reverse=True)
        size = body.get("size", len(documents))
        return {"hits": {"hits": [{"_id": doc.get("id"), "_source": doc} for doc in documents[:size]]}}

    def _search_aggregations(self, index: str) -> dict:
        buckets: dict[str, dict] = {}
        for document in self.documents.get(index, {}).values():
            for tag in document.get("mistake_tags") or []:
                bucket = buckets.setdefault(
                    tag,
                    {
                        "key": tag,
                        "doc_count": 0,
                        "symbols": {"buckets": []},
                        "latest": {"hits": {"hits": []}},
                    },
                )
                bucket["doc_count"] += 1
                symbols = {item["key"] for item in bucket["symbols"]["buckets"]}
                symbol = document.get("symbol")
                if symbol and symbol not in symbols:
                    bucket["symbols"]["buckets"].append({"key": symbol, "doc_count": 1})
                latest = bucket["latest"]["hits"]["hits"]
                if not latest or (document.get("created_at") or "") > (
                    latest[0].get("_source", {}).get("created_at") or ""
                ):
                    latest[:] = [{"_source": {"id": document.get("id"), "created_at": document.get("created_at")}}]
        return {"aggregations": {"mistakes": {"buckets": list(buckets.values())}}}


def make_repository(es: StubESClient | None = None) -> tuple[TradeReviewRepository, StubESClient]:
    client = es or StubESClient()
    return TradeReviewRepository(client, DummySettings()), client


def test_trade_review_v2_mapping_disables_high_variance_objects() -> None:
    properties = TRADE_REVIEW_INDEX_V2_BODY["mappings"]["properties"]

    assert TRADE_REVIEW_INDEX_V2_BODY["mappings"]["dynamic"] is False
    for field in [
        "score_detail",
        "run_trace",
        "evidence_pack",
        "model_provider_snapshot",
        "metadata",
        "agent_run_trace",
        "agent_replay",
    ]:
        assert properties[field]["enabled"] is False


def test_save_review_writes_to_v2_index_and_preserves_source_payload() -> None:
    repository, es = make_repository()
    large_payload = {f"dynamic_{idx}": {"nested": idx} for idx in range(1500)}

    stored = repository.save_review(
        {
            "id": "review-1",
            "review_type": "symbol_level_review",
            "symbol": "AMD.US",
            "overall_score": 80,
            "mistake_tags": ["position_sizing"],
            "evidence_pack": large_payload,
            "run_trace": large_payload,
            "score_detail": large_payload,
            "model_provider_snapshot": large_payload,
        }
    )

    assert TRADE_REVIEW_INDEX_V2 in es.index_bodies
    assert es.indexed_calls[0][0] == TRADE_REVIEW_INDEX_V2
    assert "ibkr_trade_reviews_v1" not in es.documents
    assert stored["evidence_pack"]["dynamic_1499"]["nested"] == 1499
    assert stored["run_trace"]["dynamic_1499"]["nested"] == 1499


def test_get_review_prefers_v2_over_legacy() -> None:
    repository, es = make_repository()
    es.documents[TRADE_REVIEW_INDEX_V2] = {"same-id": {"id": "same-id", "summary": "v2"}}
    es.documents["ibkr_trade_reviews_v1"] = {"same-id": {"id": "same-id", "summary": "legacy"}}

    assert repository.get_review("same-id")["summary"] == "v2"


def test_get_review_falls_back_to_legacy_index() -> None:
    repository, es = make_repository()
    es.documents["ibkr_trade_reviews_v1"] = {"legacy-id": {"id": "legacy-id", "summary": "legacy"}}

    assert repository.get_review("legacy-id")["summary"] == "legacy"


def test_list_symbol_reviews_merges_v2_and_legacy_sorted_and_deduped() -> None:
    repository, es = make_repository()
    es.documents[TRADE_REVIEW_INDEX_V2] = {
        "new": {"id": "new", "symbol": "AMD.US", "created_at": "2026-06-05T10:00:00+00:00"},
        "shared": {"id": "shared", "symbol": "AMD.US", "created_at": "2026-06-05T09:00:00+00:00"},
    }
    es.documents["ibkr_trade_reviews_v1"] = {
        "old": {"id": "old", "symbol": "AMD.US", "created_at": "2026-06-04T10:00:00+00:00"},
        "shared": {"id": "shared", "symbol": "AMD.US", "created_at": "2026-06-01T10:00:00+00:00"},
        "other": {"id": "other", "symbol": "NVDA.US", "created_at": "2026-06-05T10:00:00+00:00"},
    }

    reviews = repository.list_symbol_reviews("AMD.US", limit=10)

    assert [item["id"] for item in reviews] == ["new", "shared", "old"]


def test_list_recent_reviews_reads_v2_data() -> None:
    repository, es = make_repository()
    es.documents[TRADE_REVIEW_INDEX_V2] = {
        "symbol": {
            "id": "symbol",
            "review_type": "symbol_level_review",
            "created_at": "2026-06-05T10:00:00+00:00",
        },
        "trade": {
            "id": "trade",
            "review_type": "single_trade_review",
            "created_at": "2026-06-05T11:00:00+00:00",
        },
    }

    reviews = repository.list_recent_reviews(limit=5, review_type="symbol_level_review")

    assert [item["id"] for item in reviews] == ["symbol"]


def test_summarize_mistakes_reads_v2_and_can_fallback_to_legacy() -> None:
    repository, es = make_repository()
    es.documents[TRADE_REVIEW_INDEX_V2] = {
        "v2": {
            "id": "v2",
            "symbol": "AMD.US",
            "mistake_tags": ["position_sizing"],
            "created_at": "2026-06-05T10:00:00+00:00",
        }
    }

    assert repository.summarize_mistakes()[0]["tag"] == "position_sizing"

    es.documents.pop(TRADE_REVIEW_INDEX_V2)
    es.missing_search_indexes.add(TRADE_REVIEW_INDEX_V2)
    es.documents["ibkr_trade_reviews_v1"] = {
        "old": {
            "id": "old",
            "symbol": "TSLA.US",
            "mistake_tags": ["chasing"],
            "created_at": "2026-06-01T10:00:00+00:00",
        }
    }

    assert repository.summarize_mistakes()[0]["tag"] == "chasing"
