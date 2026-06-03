from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


AGENT_RUN_TRACE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "run_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "agent_version": {"type": "keyword"},
            "agent_mode": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "request_id": {"type": "keyword"},
            "final_status": {"type": "keyword"},
            "error_code": {"type": "keyword"},
            "latency_ms": {"type": "long"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "prompt_keys": {"type": "keyword"},
            "prompt_versions": {"type": "keyword"},
            "prompt_hashes": {"type": "keyword"},
            "llm_call_count": {"type": "integer"},
            "tool_call_count": {"type": "integer"},
            "total_tokens": {"type": "long"},
            "estimated_cost": {"type": "double"},
            "prompt_metadata": {"type": "object", "enabled": False},
            "context_manifest": {"type": "object", "enabled": False},
            "node_traces": {"type": "object", "enabled": False},
            "llm_calls": {"type": "object", "enabled": False},
            "tool_calls": {"type": "object", "enabled": False},
            "validation": {"type": "object", "enabled": False},
            "repair_attempts": {"type": "object", "enabled": False},
            "fallback": {"type": "object", "enabled": False},
            "quality_score": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "enabled": False},
        }
    },
}


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class AgentRunTraceRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_run_trace_index

    def save_trace(self, document: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=document["run_id"], document=document)
        return document

    def get_trace(self, run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_traces(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        final_status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = [{"range": {"started_at": {"gte": since_iso(hours)}}}]
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if final_status:
            filters.append({"term": {"final_status": final_status}})
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"started_at": {"order": "desc"}}],
                    "size": max(1, min(int(limit), 10000)),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, AGENT_RUN_TRACE_INDEX_BODY)
