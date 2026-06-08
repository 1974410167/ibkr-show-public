from __future__ import annotations

from app.clients.es_client import ESIndexNotFoundError
from app.services.eval_simulation_repository import (
    LEGACY_SIMULATION_RESULT_INDEX,
    SIMULATION_RESULT_INDEX,
    SIMULATION_RESULT_INDEX_BODY,
    InMemorySyntheticSimulationRepository,
    SyntheticSimulationRepository,
)


class FakeEsClient:
    def __init__(self) -> None:
        self.indexed: list[dict] = []
        self.searches: list[dict] = []
        self.hits_by_index: dict[str, list[dict]] = {}
        self.docs_by_index: dict[str, dict[str, dict]] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        return None

    def index_document(self, *, index: str, id: str, document: dict) -> dict:
        self.indexed.append({"index": index, "id": id, "document": document})
        self.docs_by_index.setdefault(index, {})[id] = document
        return document

    def search(self, *, index: str, body: dict) -> dict:
        self.searches.append({"index": index, "body": body})
        if index not in self.hits_by_index:
            raise ESIndexNotFoundError(index)
        return {"hits": {"hits": [{"_source": item} for item in self.hits_by_index[index]]}}

    def get(self, *, index: str, id: str) -> dict | None:
        if index not in self.docs_by_index:
            raise ESIndexNotFoundError(index)
        doc = self.docs_by_index[index].get(id)
        return {"_source": doc} if doc else None


def test_in_memory_simulation_repository_saves_runs_and_results() -> None:
    repo = InMemorySyntheticSimulationRepository()
    run = {
        "simulation_run_id": "run-1",
        "agent_names": ["trade_decision"],
        "status": "completed",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    result = {
        "simulation_result_id": "result-1",
        "simulation_run_id": "run-1",
        "agent_name": "trade_decision",
        "status": "skipped",
        "created_at": "2026-01-01T00:00:01+00:00",
    }

    assert repo.save_run(run) == run
    assert repo.get_run("run-1")["simulation_run_id"] == "run-1"
    assert repo.list_runs(agent_name="trade_decision")[0]["simulation_run_id"] == "run-1"
    assert repo.list_runs(status="completed")[0]["simulation_run_id"] == "run-1"

    assert repo.save_result(result) == result
    assert repo.get_result("result-1")["simulation_result_id"] == "result-1"
    assert repo.list_results("run-1")[0]["simulation_result_id"] == "result-1"
    assert repo.get_run("missing") is None
    assert repo.get_result("missing") is None


def test_es_simulation_repository_does_not_embed_results_in_run_document() -> None:
    es = FakeEsClient()
    repo = SyntheticSimulationRepository(es, settings=object())
    run = {
        "simulation_run_id": "run-1",
        "agent_names": ["trade_decision"],
        "status": "completed",
        "results": [{"output": {"position_advice": {"max_position_pct": 12.5}}}],
    }

    assert repo.save_run(run) == run

    indexed = es.indexed[0]["document"]
    assert "results" not in indexed
    assert run["results"]


def test_simulation_result_index_uses_non_indexed_dynamic_payload_fields() -> None:
    properties = SIMULATION_RESULT_INDEX_BODY["mappings"]["properties"]

    assert SIMULATION_RESULT_INDEX.endswith("_v2")
    assert SIMULATION_RESULT_INDEX_BODY["mappings"]["dynamic"] is False
    for field in ("output", "output_summary", "run_trace", "node_outputs", "tool_calls"):
        assert properties[field]["enabled"] is False
    assert properties["metadata"]["dynamic"] is False


def test_es_simulation_repository_writes_results_to_v2_index() -> None:
    es = FakeEsClient()
    repo = SyntheticSimulationRepository(es, settings=object())
    result = {
        "simulation_result_id": "result-1",
        "simulation_run_id": "run-1",
        "agent_name": "daily_position_review",
        "status": "passed",
        "output": {"many": {"nested": {"fields": "stored only in _source"}}},
    }

    repo.save_result(result)

    assert es.indexed[0]["index"] == SIMULATION_RESULT_INDEX
    assert es.indexed[0]["document"]["output"]["many"]["nested"]["fields"] == "stored only in _source"


def test_es_simulation_repository_reads_legacy_results_when_v2_has_none() -> None:
    es = FakeEsClient()
    repo = SyntheticSimulationRepository(es, settings=object())
    legacy = {
        "simulation_result_id": "legacy-result",
        "simulation_run_id": "run-1",
        "agent_name": "trade_decision",
        "status": "passed",
    }
    es.hits_by_index[SIMULATION_RESULT_INDEX] = []
    es.hits_by_index[LEGACY_SIMULATION_RESULT_INDEX] = [legacy]
    es.docs_by_index[LEGACY_SIMULATION_RESULT_INDEX] = {"legacy-result": legacy}

    assert repo.list_results("run-1") == [legacy]
    assert repo.get_result("legacy-result") == legacy
