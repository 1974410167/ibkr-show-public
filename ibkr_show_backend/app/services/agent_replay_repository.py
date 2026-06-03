from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


AGENT_REPLAY_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "replay_id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "agent_version": {"type": "keyword"},
            "agent_mode": {"type": "keyword"},
            "source": {"type": "keyword"},
            "final_status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "prompt_keys": {"type": "keyword"},
            "model": {"type": "keyword"},
            "tool_names": {"type": "keyword"},
            "llm_call_ids": {"type": "keyword"},
            "persisted_document_id": {"type": "keyword"},
            "request": {"type": "object", "enabled": False},
            "prompt_refs": {"type": "object", "enabled": False},
            "model_config": {"type": "object", "enabled": False},
            "context_snapshot": {"type": "object", "enabled": False},
            "tool_snapshots": {"type": "object", "enabled": False},
            "llm_snapshots": {"type": "object", "enabled": False},
            "final_output": {"type": "object", "enabled": False},
            "trace_ref": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "enabled": False},
        }
    },
}


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class AgentReplayRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_replay_index

    def save_snapshot(self, document: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=document["replay_id"], document=document)
        return document

    def get_snapshot(self, replay_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=replay_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def get_by_run_id(self, run_id: str) -> dict | None:
        results = self._search(filters=[{"term": {"run_id": run_id}}], limit=1)
        return results[0] if results else None

    def list_snapshots(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        final_status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = [{"range": {"created_at": {"gte": since_iso(hours)}}}]
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if final_status:
            filters.append({"term": {"final_status": final_status}})
        return self._search(filters=filters, limit=limit)

    def _search(self, *, filters: list[dict], limit: int) -> list[dict]:
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
        self.es_client.create_index_if_missing(self.index_name, AGENT_REPLAY_INDEX_BODY)
