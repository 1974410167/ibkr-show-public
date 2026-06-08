from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

TRADE_REVIEW_INDEX_V2 = "ibkr_trade_reviews_v2"

TRADE_REVIEW_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "review_type": {"type": "keyword"},
            "symbol": {"type": "keyword"},
            "trade_ids": {"type": "keyword"},
            "start_date": {"type": "date"},
            "end_date": {"type": "date"},
            "overall_score": {"type": "double"},
            "rating": {"type": "keyword"},
            "score_detail": {"type": "object", "enabled": True},
            "summary": {"type": "text"},
            "strengths": {"type": "text"},
            "weaknesses": {"type": "text"},
            "mistake_tags": {"type": "keyword"},
            "improvement_suggestions": {"type": "text"},
            "data_limitations": {"type": "text"},
            "run_trace": {"type": "object", "enabled": True},
            "evidence_pack": {"type": "object", "enabled": True},
            "raw_llm_response": {"type": "text", "index": False},
            "model_provider_snapshot": {"type": "object", "enabled": True},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    },
}

TRADE_REVIEW_INDEX_V2_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "id": {"type": "keyword"},
            "review_type": {"type": "keyword"},
            "symbol": {"type": "keyword"},
            "trade_ids": {"type": "keyword"},
            "start_date": {"type": "date"},
            "end_date": {"type": "date"},
            "overall_score": {"type": "double"},
            "rating": {"type": "keyword"},
            "score_detail": {"type": "object", "enabled": False},
            "summary": {"type": "text"},
            "strengths": {"type": "text"},
            "weaknesses": {"type": "text"},
            "mistake_tags": {"type": "keyword"},
            "improvement_suggestions": {"type": "text"},
            "data_limitations": {"type": "text"},
            "run_trace": {"type": "object", "enabled": False},
            "evidence_pack": {"type": "object", "enabled": False},
            "raw_llm_response": {"type": "text", "index": False},
            "model_provider_snapshot": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "enabled": False},
            "agent_run_trace": {"type": "object", "enabled": False},
            "agent_replay": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeReviewRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def save_review(self, document: dict) -> dict:
        self.es_client.create_index_if_missing(TRADE_REVIEW_INDEX_V2, TRADE_REVIEW_INDEX_V2_BODY)
        now = utc_now_iso()
        review_id = document.get("id") or str(uuid4())
        stored = {
            **document,
            "id": review_id,
            "created_at": document.get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=TRADE_REVIEW_INDEX_V2, id=review_id, document=stored)
        return stored

    def get_review(self, review_id: str) -> dict | None:
        response = self.es_client.get(index=TRADE_REVIEW_INDEX_V2, id=review_id)
        if response:
            return response.get("_source")
        try:
            response = self.es_client.get(index=self.settings.es_trade_review_index, id=review_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_symbol_reviews(self, symbol: str, limit: int) -> list[dict]:
        body = {
            "query": {"bool": {"filter": [{"term": {"symbol": symbol}}]}},
            "sort": [{"created_at": {"order": "desc"}}],
            "size": limit,
            "_source": True,
        }
        return self._search_reviews_with_legacy_fallback(body, limit)

    def list_recent_reviews(self, limit: int, review_type: str | None = None) -> list[dict]:
        filters = []
        if review_type:
            filters.append({"term": {"review_type": review_type}})
        body = {
            "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
            "sort": [{"created_at": {"order": "desc"}}],
            "size": limit,
            "_source": True,
        }
        return self._search_reviews_with_legacy_fallback(body, limit)

    def _search_reviews_with_legacy_fallback(self, body: dict, limit: int) -> list[dict]:
        reviews = []
        seen_ids = set()
        for index in [TRADE_REVIEW_INDEX_V2, self.settings.es_trade_review_index]:
            try:
                response = self.es_client.search(index=index, body=body)
            except ESIndexNotFoundError:
                continue
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source") or {}
                review_id = source.get("id")
                dedupe_key = review_id or hit.get("_id")
                if dedupe_key in seen_ids:
                    continue
                if dedupe_key:
                    seen_ids.add(dedupe_key)
                reviews.append(source)
        reviews.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return reviews[:limit]

    def summarize_mistakes(self) -> list[dict]:
        items = self._summarize_mistakes_for_index(TRADE_REVIEW_INDEX_V2)
        if items:
            return items
        return self._summarize_mistakes_for_index(self.settings.es_trade_review_index)

    def _summarize_mistakes_for_index(self, index: str) -> list[dict]:
        try:
            response = self.es_client.search(
                index=index,
                body={
                    "size": 0,
                    "aggs": {
                        "mistakes": {
                            "terms": {"field": "mistake_tags", "size": 50},
                            "aggs": {
                                "symbols": {"terms": {"field": "symbol", "size": 20}},
                                "latest": {
                                    "top_hits": {
                                        "size": 1,
                                        "sort": [{"created_at": {"order": "desc"}}],
                                        "_source": ["id"],
                                    }
                                },
                            },
                        }
                    },
                },
            )
        except ESIndexNotFoundError:
            return []
        items = []
        for bucket in response.get("aggregations", {}).get("mistakes", {}).get("buckets", []):
            latest_hits = bucket.get("latest", {}).get("hits", {}).get("hits", [])
            items.append(
                {
                    "tag": bucket.get("key"),
                    "count": bucket.get("doc_count", 0),
                    "symbols": [item.get("key") for item in bucket.get("symbols", {}).get("buckets", [])],
                    "latest_review_id": latest_hits[0].get("_source", {}).get("id") if latest_hits else "",
                }
            )
        return items
