from types import SimpleNamespace

import pytest

from app.agents.graph.result_contract import (
    assert_saved_document_contract,
    build_agent_metadata,
    build_run_trace_from_state,
    classify_agent_status,
    get_public_data_runtime_status,
)


def test_public_data_runtime_status_uses_client_health_not_enabled_only() -> None:
    class Client:
        enabled = True

        def health(self):
            return {"ok": False, "message": "LongBridge OpenAPI OAuth authorization is required"}

    status = get_public_data_runtime_status(mcp_adapter=SimpleNamespace(client=Client()))

    assert status["mcp_enabled"] is True
    assert status["mcp_available"] is False
    assert status["public_data_mode"] == "unavailable"
    assert "OAuth authorization" in status["mcp_last_error"]


def test_build_run_trace_from_state_adds_event_and_persist_trace() -> None:
    trace = build_run_trace_from_state(
        {"node_traces": [{"node_name": "load", "status": "success", "_start_perf": 1.0}]},
        {"node_name": "persist", "status": "success"},
    )

    assert [item["node_name"] for item in trace] == ["load", "persist"]
    assert all(item["event"] == "node_success" for item in trace)
    assert "_start_perf" not in trace[0]


def test_saved_document_contract_rejects_success_without_trace() -> None:
    document = {
        "metadata": build_agent_metadata(agent_mode="agent_v1", graph_version="graph_v1"),
        "run_trace": [],
        "fallback_used": False,
    }

    with pytest.raises(ValueError, match="non-empty run_trace"):
        assert_saved_document_contract(document)


def test_classify_agent_status_marks_fallback_without_core_evidence_failed() -> None:
    document = {
        "metadata": build_agent_metadata(
            agent_mode="agent_v1",
            graph_version="graph_v1",
            fallback_used=True,
            fallback_reason="graph completed without saving",
        ),
        "fallback_used": True,
        "fallback_reason": "graph completed without saving",
        "data_limitations": ["graph_failed: graph completed without saving"],
        "run_trace": [],
    }

    assert classify_agent_status(document) == "failed"


def test_classify_agent_status_keeps_data_limitations_success_without_fallback() -> None:
    document = {
        "metadata": build_agent_metadata(agent_mode="agent_v1", graph_version="graph_v1"),
        "fallback_used": False,
        "data_limitations": ["MSFT PS TTM数据缺失", "宏观事件和利率汇率数据未提供"],
        "run_trace": [{"node_name": "persist_daily_review", "status": "success"}],
    }

    assert classify_agent_status(document) == "success"
