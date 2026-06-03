from app.services.agent_replay_service import AgentReplayService
from app.services.agent_replay_repository import AGENT_REPLAY_INDEX_BODY


class FakeReplayRepository:
    def __init__(self) -> None:
        self.saved = {}

    def save_snapshot(self, document: dict) -> dict:
        self.saved[document["replay_id"]] = document
        return document

    def get_snapshot(self, replay_id: str) -> dict | None:
        return self.saved.get(replay_id)

    def get_by_run_id(self, run_id: str) -> dict | None:
        return next((item for item in self.saved.values() if item.get("run_id") == run_id), None)

    def list_snapshots(self, **kwargs) -> list[dict]:
        return list(self.saved.values())


def test_agent_replay_service_record_list_get_and_export() -> None:
    service = AgentReplayService(FakeReplayRepository())

    service.record_snapshot(
        {
            "replay_id": "replay-1",
            "run_id": "run-1",
            "agent_name": "trade_review",
            "created_at": "2026-05-26T00:00:00+00:00",
            "final_status": "success",
            "prompt_refs": [{"prompt_key": "trade_review_main"}],
            "model_config": {"model": "model-a"},
            "tool_snapshots": [{"tool_name": "get_context"}],
            "llm_snapshots": [{"call_id": "call-1"}],
        }
    )

    assert service.get_snapshot("replay-1")["prompt_keys"] == ["trade_review_main"]
    assert service.get_by_run_id("run-1")["replay_id"] == "replay-1"
    assert service.list_snapshots()["summary"]["snapshot_count"] == 1
    assert service.export_replay_package("replay-1")["package_type"] == "agent_replay_package"


def test_agent_replay_v2_mapping_keeps_large_payloads_unindexed() -> None:
    mappings = AGENT_REPLAY_INDEX_BODY["mappings"]
    props = mappings["properties"]

    assert mappings["dynamic"] is False
    assert props["replay_id"]["type"] == "keyword"
    assert props["run_id"]["type"] == "keyword"
    assert props["final_status"]["type"] == "keyword"
    assert props["prompt_keys"]["type"] == "keyword"
    assert props["tool_names"]["type"] == "keyword"
    assert props["context_snapshot"]["enabled"] is False
    assert props["tool_snapshots"]["enabled"] is False
    assert props["llm_snapshots"]["enabled"] is False
    assert props["final_output"]["enabled"] is False
    assert props["metadata"]["enabled"] is False
