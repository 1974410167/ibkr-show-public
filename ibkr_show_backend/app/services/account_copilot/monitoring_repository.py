from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


COPILOT_TOOL_CALL_METRICS_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "task_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "node_name": {"type": "keyword"},
            "tool_domain": {"type": "keyword"},
            "tool_name": {"type": "keyword"},
            "ok": {"type": "boolean"},
            "latency_ms": {"type": "long"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "source": {"type": "keyword"},
            "empty_result": {"type": "boolean"},
            "raw_ok": {"type": "boolean"},
            "compact_ok": {"type": "boolean"},
            "parsed_fields_count": {"type": "long"},
            "missing_fields_count": {"type": "long"},
            "fallback_used": {"type": "boolean"},
            "created_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


STRUCTURED_OUTPUT_METRICS_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "source": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "node_name": {"type": "keyword"},
            "contract_name": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "task_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "ok": {"type": "boolean"},
            "schema_validation_passed": {"type": "boolean"},
            "repaired": {"type": "boolean"},
            "repair_attempts": {"type": "integer"},
            "fallback_used": {"type": "boolean"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "output_model_name": {"type": "keyword"},
            "raw_response_preview": {"type": "text"},
            "final_response_preview": {"type": "text"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


COPILOT_LLM_CALL_METRICS_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "task_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "node_name": {"type": "keyword"},
            "provider": {"type": "keyword"},
            "model": {"type": "keyword"},
            "call_type": {"type": "keyword"},
            "ok": {"type": "boolean"},
            "latency_ms": {"type": "long"},
            "prompt_tokens": {"type": "long"},
            "completion_tokens": {"type": "long"},
            "total_tokens": {"type": "long"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "created_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class AccountCopilotMonitoringRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_tool_metric(self, metric: dict) -> dict:
        self._ensure_tool_index()
        doc = {
            "id": metric.get("id") or f"tool_metric_{uuid4().hex[:12]}",
            "created_at": metric.get("created_at") or utc_now_iso(),
            **metric,
        }
        self.es_client.index_document(index=self.settings.es_copilot_tool_call_metrics_index, id=doc["id"], document=doc)
        return doc

    def create_llm_metric(self, metric: dict) -> dict:
        self._ensure_llm_index()
        doc = {
            "id": metric.get("id") or f"llm_metric_{uuid4().hex[:12]}",
            "created_at": metric.get("created_at") or utc_now_iso(),
            **metric,
        }
        self.es_client.index_document(index=self.settings.es_copilot_llm_call_metrics_index, id=doc["id"], document=doc)
        return doc

    def query_tool_metrics(self, hours: int = 24, bucket: str = "1h") -> list[dict]:
        return self._search_recent(self.settings.es_copilot_tool_call_metrics_index, hours)

    def query_llm_metrics(self, hours: int = 24, bucket: str = "1h") -> list[dict]:
        return self._search_recent(self.settings.es_copilot_llm_call_metrics_index, hours)

    def query_recent_tool_calls(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        tool_domain: str | None = None,
        tool_name: str | None = None,
    ) -> list[dict]:
        filters: list[dict] = []
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if tool_domain:
            filters.append({"term": {"tool_domain": tool_domain}})
        if tool_name:
            filters.append({"term": {"tool_name": tool_name}})
        return self._search_with_filters(self.settings.es_copilot_tool_call_metrics_index, filters, limit=limit)

    def query_recent_llm_calls(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        model: str | None = None,
    ) -> list[dict]:
        filters: list[dict] = []
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if model:
            filters.append({"term": {"model": model}})
        return self._search_with_filters(self.settings.es_copilot_llm_call_metrics_index, filters, limit=limit)

    def query_recent_failures(self, hours: int = 24, limit: int = 50) -> dict[str, list[dict]]:
        return {
            "tool": self._search_recent(self.settings.es_copilot_tool_call_metrics_index, hours, ok=False, limit=limit),
            "llm": self._search_recent(self.settings.es_copilot_llm_call_metrics_index, hours, ok=False, limit=limit),
        }

    def _search_recent(
        self,
        index: str,
        hours: int,
        *,
        ok: bool | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        filters: list[dict] = [{"range": {"created_at": {"gte": since_iso(hours)}}}]
        if ok is not None:
            filters.append({"term": {"ok": ok}})
        try:
            response = self.es_client.search(
                index=index,
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

    def _search_with_filters(self, index: str, filters: list[dict], *, limit: int) -> list[dict]:
        try:
            response = self.es_client.search(
                index=index,
                body={
                    "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": max(1, min(int(limit), 500)),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_tool_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_tool_call_metrics_index, COPILOT_TOOL_CALL_METRICS_INDEX_BODY)
        self._put_mapping_if_possible(self.settings.es_copilot_tool_call_metrics_index, COPILOT_TOOL_CALL_METRICS_INDEX_BODY)

    def _ensure_llm_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_llm_call_metrics_index, COPILOT_LLM_CALL_METRICS_INDEX_BODY)
        self._put_mapping_if_possible(self.settings.es_copilot_llm_call_metrics_index, COPILOT_LLM_CALL_METRICS_INDEX_BODY)

    def create_structured_output_metric(self, metric: dict) -> dict:
        self._ensure_structured_output_index()
        doc = {
            "id": metric.get("id") or f"so_metric_{uuid4().hex[:12]}",
            "created_at": metric.get("created_at") or utc_now_iso(),
            **metric,
        }
        self.es_client.index_document(index=self.settings.es_structured_output_metrics_index, id=doc["id"], document=doc)
        return doc

    def query_recent_structured_output_events(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        contract_name: str | None = None,
        node_name: str | None = None,
        ok: bool | None = None,
        repaired: bool | None = None,
        fallback_used: bool | None = None,
    ) -> list[dict]:
        filters: list[dict] = []
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if contract_name:
            filters.append({"term": {"contract_name": contract_name}})
        if node_name:
            filters.append({"term": {"node_name": node_name}})
        if ok is not None:
            filters.append({"term": {"ok": ok}})
        if repaired is not None:
            filters.append({"term": {"repaired": repaired}})
        if fallback_used is not None:
            filters.append({"term": {"fallback_used": fallback_used}})
        return self._search_with_filters(self.settings.es_structured_output_metrics_index, filters, limit=limit)

    def _ensure_structured_output_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_structured_output_metrics_index, STRUCTURED_OUTPUT_METRICS_INDEX_BODY)
        self._put_mapping_if_possible(self.settings.es_structured_output_metrics_index, STRUCTURED_OUTPUT_METRICS_INDEX_BODY)

    def _put_mapping_if_possible(self, index: str, body: dict) -> None:
        client = getattr(self.es_client, "_client", None)
        if client is None:
            return
        try:
            client.indices.put_mapping(index=index, properties=body.get("mappings", {}).get("properties", {}))
        except Exception:
            return
