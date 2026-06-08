from __future__ import annotations

from app.agents.eval_failure_mining import SEVERITY_ORDER
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


FAILURE_MINING_RUN_INDEX = "ibkr_agent_eval_failure_mining_runs"
FAILURE_ITEM_INDEX = "ibkr_agent_eval_failure_items"


FAILURE_MINING_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "failure_mining_run_id": {"type": "keyword"},
            "simulation_run_id": {"type": "keyword"},
            "agent_names": {"type": "keyword"},
            "name": {"type": "keyword"},
            "status": {"type": "keyword"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "summary": {"type": "object", "enabled": True},
            "config": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


FAILURE_ITEM_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "failure_id": {"type": "keyword"},
            "failure_mining_run_id": {"type": "keyword"},
            "simulation_run_id": {"type": "keyword"},
            "simulation_result_id": {"type": "keyword"},
            "scenario_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "failure_type": {"type": "keyword"},
            "failure_tags": {"type": "keyword"},
            "failed_dimensions": {"type": "keyword"},
            "should_convert_to_eval_case": {"type": "boolean"},
            "conversion_priority": {"type": "integer"},
            "duplicate_key": {"type": "keyword"},
            "created_at": {"type": "date"},
            "failed_checks": {"type": "object", "enabled": True},
            "judge_result": {"type": "object", "enabled": True},
            "evidence": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


class SyntheticFailureMiningRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def save_failure_mining_run(self, run: dict) -> dict:
        self.es_client.create_index_if_missing(FAILURE_MINING_RUN_INDEX, FAILURE_MINING_RUN_INDEX_BODY)
        self.es_client.index_document(index=FAILURE_MINING_RUN_INDEX, id=run["failure_mining_run_id"], document=run)
        return run

    def get_failure_mining_run(self, failure_mining_run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=FAILURE_MINING_RUN_INDEX, id=failure_mining_run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_failure_mining_runs(
        self,
        *,
        simulation_run_id: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
        if simulation_run_id:
            filters.append({"term": {"simulation_run_id": simulation_run_id}})
        if agent_name:
            filters.append({"term": {"agent_names": agent_name}})
        if status:
            filters.append({"term": {"status": status}})
        body = {
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "sort": [{"started_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=FAILURE_MINING_RUN_INDEX, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def save_failure_item(self, item: dict) -> dict:
        self.es_client.create_index_if_missing(FAILURE_ITEM_INDEX, FAILURE_ITEM_INDEX_BODY)
        self.es_client.index_document(index=FAILURE_ITEM_INDEX, id=item["failure_id"], document=item)
        return item

    def list_failure_items(
        self,
        *,
        failure_mining_run_id: str | None = None,
        simulation_run_id: str | None = None,
        agent_name: str | None = None,
        failure_type: str | None = None,
        min_severity: str | None = None,
        should_convert_to_eval_case: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        filters: list[dict] = []
        if failure_mining_run_id:
            filters.append({"term": {"failure_mining_run_id": failure_mining_run_id}})
        if simulation_run_id:
            filters.append({"term": {"simulation_run_id": simulation_run_id}})
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if failure_type:
            filters.append({"term": {"failure_type": failure_type}})
        if should_convert_to_eval_case is not None:
            filters.append({"term": {"should_convert_to_eval_case": should_convert_to_eval_case}})
        body = {
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "sort": [{"conversion_priority": {"order": "desc"}}, {"created_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=FAILURE_ITEM_INDEX, body=body)
        except ESIndexNotFoundError:
            return []
        items = [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        return _filter_min_severity(items, min_severity)

    def get_failure_item(self, failure_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=FAILURE_ITEM_INDEX, id=failure_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None


class InMemorySyntheticFailureMiningRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.items: dict[str, dict] = {}

    def save_failure_mining_run(self, run: dict) -> dict:
        self.runs[run["failure_mining_run_id"]] = dict(run)
        return run

    def get_failure_mining_run(self, failure_mining_run_id: str) -> dict | None:
        run = self.runs.get(failure_mining_run_id)
        return dict(run) if run else None

    def list_failure_mining_runs(
        self,
        *,
        simulation_run_id: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = list(self.runs.values())
        if simulation_run_id:
            items = [item for item in items if item.get("simulation_run_id") == simulation_run_id]
        if agent_name:
            items = [item for item in items if agent_name in (item.get("agent_names") or [])]
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return [dict(item) for item in items[:limit]]

    def save_failure_item(self, item: dict) -> dict:
        self.items[item["failure_id"]] = dict(item)
        return item

    def list_failure_items(
        self,
        *,
        failure_mining_run_id: str | None = None,
        simulation_run_id: str | None = None,
        agent_name: str | None = None,
        failure_type: str | None = None,
        min_severity: str | None = None,
        should_convert_to_eval_case: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        items = list(self.items.values())
        if failure_mining_run_id:
            items = [item for item in items if item.get("failure_mining_run_id") == failure_mining_run_id]
        if simulation_run_id:
            items = [item for item in items if item.get("simulation_run_id") == simulation_run_id]
        if agent_name:
            items = [item for item in items if item.get("agent_name") == agent_name]
        if failure_type:
            items = [item for item in items if item.get("failure_type") == failure_type]
        if should_convert_to_eval_case is not None:
            items = [item for item in items if item.get("should_convert_to_eval_case") is should_convert_to_eval_case]
        items = _filter_min_severity(items, min_severity)
        items.sort(key=lambda item: (item.get("conversion_priority") or 0, item.get("created_at") or ""), reverse=True)
        return [dict(item) for item in items[:limit]]

    def get_failure_item(self, failure_id: str) -> dict | None:
        item = self.items.get(failure_id)
        return dict(item) if item else None


def _filter_min_severity(items: list[dict], min_severity: str | None) -> list[dict]:
    if not min_severity:
        return items
    threshold = SEVERITY_ORDER.get(min_severity, 1)
    return [item for item in items if SEVERITY_ORDER.get(item.get("severity"), 0) >= threshold]
