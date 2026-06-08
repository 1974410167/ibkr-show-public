from __future__ import annotations

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


SIMULATION_RUN_INDEX = "ibkr_agent_eval_simulation_runs"
LEGACY_SIMULATION_RESULT_INDEX = "ibkr_agent_eval_simulation_results"
SIMULATION_RESULT_INDEX = "ibkr_agent_eval_simulation_results_v2"


SIMULATION_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "simulation_run_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "scenario_ids": {"type": "keyword"},
            "agent_names": {"type": "keyword"},
            "status": {"type": "keyword"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "summary": {"type": "object", "enabled": True},
            "config": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


SIMULATION_RESULT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "simulation_result_id": {"type": "keyword"},
            "simulation_run_id": {"type": "keyword"},
            "scenario_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "status": {"type": "keyword"},
            "latency_ms": {"type": "integer"},
            "error_code": {"type": "keyword"},
            "source_run_id": {"type": "keyword"},
            "source_task_id": {"type": "keyword"},
            "source_document_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "output": {"type": "object", "enabled": False},
            "output_summary": {"type": "object", "enabled": False},
            "run_trace": {"type": "object", "enabled": False},
            "node_outputs": {"type": "object", "enabled": False},
            "tool_calls": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "dynamic": False},
        }
    },
}


class SyntheticSimulationRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def run_index_name(self) -> str:
        return SIMULATION_RUN_INDEX

    @property
    def result_index_name(self) -> str:
        return SIMULATION_RESULT_INDEX

    def save_run(self, run: dict) -> dict:
        self._ensure_run_index()
        document = dict(run)
        document.pop("results", None)
        self.es_client.index_document(index=self.run_index_name, id=run["simulation_run_id"], document=document)
        return run

    def get_run(self, simulation_run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.run_index_name, id=simulation_run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_runs(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        filters: list[dict] = []
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
            response = self.es_client.search(index=self.run_index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def save_result(self, result: dict) -> dict:
        self._ensure_result_index()
        self.es_client.index_document(index=self.result_index_name, id=result["simulation_result_id"], document=result)
        return result

    def list_results(self, simulation_run_id: str, limit: int = 1000) -> list[dict]:
        items = self._list_results_from_index(self.result_index_name, simulation_run_id, limit=limit)
        if items:
            return items
        return self._list_results_from_index(LEGACY_SIMULATION_RESULT_INDEX, simulation_run_id, limit=limit)

    def _list_results_from_index(self, index_name: str, simulation_run_id: str, limit: int = 1000) -> list[dict]:
        body = {
            "query": {"term": {"simulation_run_id": simulation_run_id}},
            "sort": [{"created_at": {"order": "asc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def get_result(self, simulation_result_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.result_index_name, id=simulation_result_id)
        except ESIndexNotFoundError:
            hit = None
        if hit:
            return hit.get("_source")
        try:
            legacy_hit = self.es_client.get(index=LEGACY_SIMULATION_RESULT_INDEX, id=simulation_result_id)
        except ESIndexNotFoundError:
            return None
        return legacy_hit.get("_source") if legacy_hit else None

    def _ensure_run_index(self) -> None:
        self.es_client.create_index_if_missing(self.run_index_name, SIMULATION_RUN_INDEX_BODY)

    def _ensure_result_index(self) -> None:
        self.es_client.create_index_if_missing(self.result_index_name, SIMULATION_RESULT_INDEX_BODY)


class InMemorySyntheticSimulationRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.results: dict[str, dict] = {}

    def save_run(self, run: dict) -> dict:
        self.runs[run["simulation_run_id"]] = dict(run)
        return run

    def get_run(self, simulation_run_id: str) -> dict | None:
        run = self.runs.get(simulation_run_id)
        return dict(run) if run else None

    def list_runs(
        self,
        *,
        agent_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = list(self.runs.values())
        if agent_name:
            items = [item for item in items if agent_name in (item.get("agent_names") or [])]
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return [dict(item) for item in items[:limit]]

    def save_result(self, result: dict) -> dict:
        self.results[result["simulation_result_id"]] = dict(result)
        return result

    def list_results(self, simulation_run_id: str, limit: int = 1000) -> list[dict]:
        items = [item for item in self.results.values() if item.get("simulation_run_id") == simulation_run_id]
        items.sort(key=lambda item: item.get("created_at") or "")
        return [dict(item) for item in items[:limit]]

    def get_result(self, simulation_result_id: str) -> dict | None:
        result = self.results.get(simulation_result_id)
        return dict(result) if result else None
