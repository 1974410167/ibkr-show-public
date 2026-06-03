from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.services.llm_observability import utc_now_iso


LLM_CALL_METRICS_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "call_id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "provider_id": {"type": "keyword"},
            "provider_name": {"type": "keyword"},
            "provider_type": {"type": "keyword"},
            "model": {"type": "keyword"},
            "call_type": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "node_name": {"type": "keyword"},
            "prompt_key": {"type": "keyword"},
            "prompt_version": {"type": "keyword"},
            "prompt_hash": {"type": "keyword"},
            "prompt_source": {"type": "keyword"},
            "response_format_type": {"type": "keyword"},
            "tool_calling": {"type": "boolean"},
            "tool_count": {"type": "integer"},
            "temperature": {"type": "float"},
            "max_tokens": {"type": "integer"},
            "latency_ms": {"type": "long"},
            "ok": {"type": "boolean"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "prompt_tokens": {"type": "long"},
            "completion_tokens": {"type": "long"},
            "total_tokens": {"type": "long"},
            "reasoning_tokens": {"type": "long"},
            "cached_tokens": {"type": "long"},
            "estimated_cost": {"type": "double"},
            "created_at": {"type": "date"},
        }
    },
}


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class LLMCallMetricsRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_llm_call_metrics_index

    def create_metric(self, document: dict) -> dict:
        self._ensure_index()
        doc = {"created_at": utc_now_iso(), **document}
        self.es_client.index_document(index=self.index_name, id=doc["call_id"], document=doc)
        return doc

    def get_metric(self, call_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=call_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_recent(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        prompt_key: str | None = None,
        model: str | None = None,
        ok: bool | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = [{"range": {"created_at": {"gte": since_iso(hours)}}}]
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if prompt_key:
            filters.append({"term": {"prompt_key": prompt_key}})
        if model:
            filters.append({"term": {"model": model}})
        if ok is not None:
            filters.append({"term": {"ok": ok}})
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": max(1, min(int(limit), 10000)),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, LLM_CALL_METRICS_INDEX_BODY)
