from app.agents.agent_run_trace import (
    build_agent_run_trace,
    new_agent_run_id,
    normalize_runtime_trace_events,
    sanitize_trace_payload,
)
from app.services.agent_run_trace_service import AgentRunTraceService
from app.services.agent_run_trace_repository import AGENT_RUN_TRACE_INDEX_BODY


def test_new_agent_run_id_uses_agent_prefix() -> None:
    run_id = new_agent_run_id("trade_review")
    assert run_id.startswith("trade_review_run_")
    assert len(run_id) > len("trade_review_run_")


def test_normalize_runtime_trace_events_extracts_llm_and_tool_calls() -> None:
    events = [
        {
            "node_name": "compose",
            "runtime_trace": [
                {"event": "llm_start", "round": 1},
                {
                    "event": "llm_finish",
                    "call_id": "call-1",
                    "model": "model-a",
                    "prompt_key": "trade_review_main",
                    "prompt_version": "v2",
                    "prompt_hash": "abc",
                    "prompt_source": "admin_active",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "latency_ms": 123,
                    "estimated_cost": 0.01,
                },
                {"event": "tool_start", "tool_call_id": "tool-1", "tool": "get_context", "arguments": {"symbol": "AMD", "api_key": "secret"}},
                {"event": "tool_finish", "tool_call_id": "tool-1", "tool": "get_context", "ok": True, "summary": "object keys: a"},
            ],
        }
    ]

    result = normalize_runtime_trace_events(events)

    assert result["llm_calls"][0]["call_id"] == "call-1"
    assert result["llm_calls"][0]["node_name"] == "compose"
    assert result["total_tokens"] == 15
    assert result["estimated_cost"] == 0.01
    assert result["prompt_metadata"]["trade_review_main"]["content_hash"] == "abc"
    assert result["tool_calls"][0]["tool"] == "get_context"
    assert result["tool_calls"][0]["arguments_preview"]["api_key"] == "***"


def test_sanitize_trace_payload_redacts_sensitive_fields() -> None:
    payload = {
        "authorization": "Bearer secret",
        "nested": {"access_token": "token", "normal": "ok"},
    }
    assert sanitize_trace_payload(payload) == {
        "authorization": "***",
        "nested": {"access_token": "***", "normal": "ok"},
    }


def test_build_agent_run_trace_summarizes_document() -> None:
    document = {
        "id": "AMD",
        "symbol": "AMD",
        "metadata": {"agent_version": "trade_review_v2", "agent_mode": "trade_review_langgraph_v1"},
        "run_trace": [
            {
                "node_name": "compose",
                "status": "success",
                "started_at": "2026-05-26T00:00:00+00:00",
                "finished_at": "2026-05-26T00:00:01+00:00",
                "runtime_trace": [
                    {"event": "llm_finish", "call_id": "call-1", "total_tokens": 9, "prompt_key": "trade_review_main"},
                ],
            }
        ],
    }

    trace = build_agent_run_trace(run_id="run-1", agent_name="trade_review", document=document)

    assert trace.run_id == "run-1"
    assert trace.agent_name == "trade_review"
    assert trace.agent_version == "trade_review_v2"
    assert trace.final_status == "success"
    assert trace.llm_calls[0]["call_id"] == "call-1"
    assert trace.context_manifest["data_limitations"] == []


class FakeRepository:
    def __init__(self) -> None:
        self.saved = {}

    def save_trace(self, document: dict) -> dict:
        self.saved[document["run_id"]] = document
        return document

    def get_trace(self, run_id: str) -> dict | None:
        return self.saved.get(run_id)

    def list_traces(self, **kwargs) -> list[dict]:
        return list(self.saved.values())


def test_agent_run_trace_service_records_and_summarizes() -> None:
    repository = FakeRepository()
    service = AgentRunTraceService(repository)
    service.record_trace(
        {
            "run_id": "run-1",
            "agent_name": "trade_review",
            "started_at": "2026-05-26T00:00:00+00:00",
            "final_status": "success",
            "latency_ms": 100,
            "prompt_metadata": {"trade_review_main": {"version": "v2", "content_hash": "abc"}},
            "llm_calls": [{"total_tokens": 12, "estimated_cost": 0.02, "prompt_key": "trade_review_main"}],
            "tool_calls": [{"tool": "get_context"}],
        }
    )

    stored = service.get_trace("run-1")
    listed = service.list_traces()

    assert stored["llm_call_count"] == 1
    assert stored["tool_call_count"] == 1
    assert stored["total_tokens"] == 12
    assert stored["prompt_keys"] == ["trade_review_main"]
    assert listed["summary"]["run_count"] == 1
    assert listed["summary"]["success_rate"] == 1.0


def test_agent_run_trace_v2_mapping_keeps_dynamic_trace_payloads_unindexed() -> None:
    mappings = AGENT_RUN_TRACE_INDEX_BODY["mappings"]
    props = mappings["properties"]

    assert mappings["dynamic"] is False
    assert props["run_id"]["type"] == "keyword"
    assert props["agent_name"]["type"] == "keyword"
    assert props["final_status"]["type"] == "keyword"
    assert props["llm_call_count"]["type"] == "integer"
    assert props["tool_call_count"]["type"] == "integer"
    assert props["total_tokens"]["type"] == "long"
    assert props["node_traces"]["enabled"] is False
    assert props["llm_calls"]["enabled"] is False
    assert props["tool_calls"]["enabled"] is False
    assert props["validation"]["enabled"] is False
    assert props["quality_score"]["enabled"] is False
    assert props["metadata"]["enabled"] is False
