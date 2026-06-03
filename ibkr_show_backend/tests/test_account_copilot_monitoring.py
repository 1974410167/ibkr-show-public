from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.agents.account_copilot.planner_schema import CopilotPlannerAction, EvidenceSufficiency
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.api.deps import get_account_copilot_monitoring_service, require_authenticated_session
from app.main import app
from app.clients.es_client import ESIndexNotFoundError
from app.services.account_copilot.monitoring_repository import AccountCopilotMonitoringRepository
from app.services.account_copilot.monitoring_service import AccountCopilotMonitoringService


@dataclass
class Settings:
    es_copilot_tool_call_metrics_index: str = "tool-metrics"
    es_copilot_llm_call_metrics_index: str = "llm-metrics"


class FakeES:
    def __init__(self):
        self.docs: dict[str, dict[str, dict]] = {}
        self.created: list[tuple[str, dict]] = []

    def create_index_if_missing(self, index, body):
        self.created.append((index, body))
        self.docs.setdefault(index, {})

    def index_document(self, index, id, document):
        self.docs.setdefault(index, {})[id] = document
        return {"result": "created"}

    def search(self, index, body):
        docs = list(self.docs.get(index, {}).values())
        filters = ((body.get("query") or {}).get("bool") or {}).get("filter") or []
        for item in filters:
            if "term" in item:
                key, value = next(iter(item["term"].items()))
                docs = [doc for doc in docs if doc.get(key) == value]
            if "range" in item:
                key, config = next(iter(item["range"].items()))
                gte = config.get("gte")
                if gte:
                    docs = [doc for doc in docs if str(doc.get(key) or "") >= str(gte)]
        docs.sort(key=lambda doc: doc.get("created_at") or "", reverse=True)
        return {"hits": {"hits": [{"_source": doc} for doc in docs[: body.get("size", 10)]]}}


class MissingIndexES(FakeES):
    def search(self, index, body):
        raise ESIndexNotFoundError(index)


class FailingRepository:
    def create_tool_metric(self, metric):
        raise RuntimeError("boom")

    def create_llm_metric(self, metric):
        raise RuntimeError("boom")


class FakeLLM:
    def get_active_provider(self):
        return type("Provider", (), {"name": "deepseek", "default_model": "deepseek-v4-pro"})()

    def health(self):
        return {"enabled": True}


class FakeMonitoringService:
    def __init__(self):
        self.tool_calls = []
        self.llm_calls = []

    def record_tool_call(self, **kwargs):
        self.tool_calls.append(kwargs)

    def record_llm_call(self, **kwargs):
        self.llm_calls.append(kwargs)


def _iso(hours_ago: int = 0, minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=minutes)).replace(microsecond=0).isoformat()


def _service():
    es = FakeES()
    repo = AccountCopilotMonitoringRepository(es, Settings())
    return AccountCopilotMonitoringService(repo), es


def test_record_tool_call_writes_tool_metric():
    service, es = _service()
    doc = service.record_tool_call(
        run_id="run1",
        session_id="session1",
        tool_name="ibkr_get_positions",
        ok=True,
        latency_ms=120,
    )

    assert doc is not None
    assert doc["tool_domain"] == "ibkr"
    assert doc["tool_name"] == "ibkr_get_positions"
    assert es.docs["tool-metrics"][doc["id"]]["ok"] is True


def test_record_llm_call_writes_llm_metric():
    service, es = _service()
    doc = service.record_llm_call(
        run_id="run1",
        session_id="session1",
        provider="deepseek",
        model="deepseek-v4-pro",
        call_type="planner",
        ok=True,
        latency_ms=456,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
    )

    assert doc is not None
    assert doc["provider"] == "deepseek"
    assert doc["model"] == "deepseek-v4-pro"
    assert es.docs["llm-metrics"][doc["id"]]["total_tokens"] == 120


def test_tool_metrics_aggregate_by_domain_success_rate_and_latency():
    service, _es = _service()
    for item in [
        ("ibkr_get_positions", True, 100),
        ("ibkr_get_trades", False, 300),
        ("longbridge_call_public_tool", True, 1000),
    ]:
        service.record_tool_call(run_id="r", session_id="s", tool_name=item[0], ok=item[1], latency_ms=item[2])

    result = service.get_tool_metrics(hours=24, bucket="1h")

    ibkr = result["ibkr"]["series"][0]
    assert ibkr["call_count"] == 2
    assert ibkr["success_rate"] == 0.5
    assert ibkr["failure_rate"] == 0.5
    assert ibkr["avg_latency_ms"] == 200
    assert ibkr["p95_latency_ms"] == 300
    assert result["longbridge"]["series"][0]["call_count"] == 1


def test_probe_results_write_tool_metrics_with_probe_source():
    service, es = _service()
    service.record_probe_results(
        probe_run_id="probe_run_1",
        results=[
            {
                "probe_run_id": "probe_run_1",
                "tool_name": "ibkr_get_positions",
                "tool_domain": "ibkr",
                "category": "portfolio",
                "probe_type": "invoke",
                "status": "pass",
                "latency_ms": 88,
            },
            {
                "probe_run_id": "probe_run_1",
                "tool_name": "quote",
                "tool_domain": "longbridge",
                "category": "quote",
                "probe_type": "invoke",
                "status": "fail",
                "latency_ms": 120,
                "error_code": "MCP_ERROR",
                "error_message": "bad",
            },
            {
                "probe_run_id": "probe_run_1",
                "tool_name": "ibkr_schema",
                "tool_domain": "ibkr",
                "probe_type": "schema",
                "status": "pass",
            },
            {
                "probe_run_id": "probe_run_1",
                "tool_name": "longbridge_quote",
                "tool_domain": "longbridge",
                "probe_type": "invoke",
                "status": "skipped",
            },
        ],
    )

    docs = list(es.docs["tool-metrics"].values())
    assert len(docs) == 2
    # Probe results now write as source=runtime (unified)
    assert {doc["source"] for doc in docs} == {"runtime"}
    assert {doc["ok"] for doc in docs} == {True, False}
    assert docs[0]["metadata"]["probe_run_id"] == "probe_run_1"


def test_tool_metrics_returns_all_data():
    service, _es = _service()
    service.record_tool_call(run_id="runtime", session_id="s", tool_name="ibkr_get_positions", ok=True, latency_ms=100)
    service.record_tool_call(run_id="", session_id="", tool_name="ibkr_get_positions", ok=False, latency_ms=300, source="probe")

    # Source filtering removed — all queries return all data
    metrics = service.get_tool_metrics(hours=24, bucket="1h")

    assert metrics["ibkr"]["series"][0]["call_count"] == 2
    assert metrics["ibkr"]["series"][0]["success_rate"] == 0.5


def test_query_recent_tool_calls_filters_and_missing_index_returns_empty():
    service, es = _service()
    service.record_tool_call(
        run_id="r1",
        session_id="s",
        agent_name="trade_decision",
        node_name="market_trend",
        tool_name="quote",
        tool_domain="longbridge",
        ok=True,
        latency_ms=10,
    )
    service.record_tool_call(
        run_id="r2",
        session_id="s",
        agent_name="account_copilot",
        node_name="tool_action",
        tool_name="ibkr_get_positions",
        tool_domain="ibkr",
        ok=True,
        latency_ms=20,
    )

    repo = AccountCopilotMonitoringRepository(es, Settings())
    rows = repo.query_recent_tool_calls(limit=10, agent_name="trade_decision", tool_domain="longbridge")

    assert len(rows) == 1
    assert rows[0]["run_id"] == "r1"
    assert rows[0]["node_name"] == "market_trend"
    assert AccountCopilotMonitoringRepository(MissingIndexES(), Settings()).query_recent_tool_calls() == []


def test_query_recent_llm_calls_filters_and_missing_index_returns_empty():
    service, es = _service()
    service.record_llm_call(run_id="r1", session_id="s", agent_name="trade_decision", node_name="event_catalyst", provider="deepseek", model="m1", call_type="sub_agent", ok=True)
    service.record_llm_call(run_id="r2", session_id="s", agent_name="account_copilot", node_name="planner", provider="deepseek", model="m2", call_type="planner", ok=True)

    repo = AccountCopilotMonitoringRepository(es, Settings())
    rows = repo.query_recent_llm_calls(limit=10, agent_name="trade_decision", model="m1")

    assert len(rows) == 1
    assert rows[0]["run_id"] == "r1"
    assert rows[0]["node_name"] == "event_catalyst"
    assert AccountCopilotMonitoringRepository(MissingIndexES(), Settings()).query_recent_llm_calls() == []


def test_recent_failures_returns_all_data():
    service, _es = _service()
    service.record_tool_call(run_id="runtime", session_id="s", tool_name="ibkr_get_positions", ok=True, latency_ms=100)
    service.record_tool_call(run_id="", session_id="", tool_name="longbridge_call_public_tool", ok=False, latency_ms=300, source="probe", error_code="PROBE_FAIL")

    # Source filtering removed — all queries return all data
    failures = service.get_recent_failures(hours=24, limit=10)

    assert len(failures["items"]) == 1
    assert failures["items"][0]["error_code"] == "PROBE_FAIL"


def test_recent_tool_calls_have_rolling_rates_and_unknown_defaults():
    service, es = _service()
    for index, ok in enumerate([True, False, True, True, False, True, True, True, False, True, False], start=1):
        doc = {
            "id": f"old-{index}",
            "run_id": f"r{index}",
            "session_id": "",
            "tool_domain": "longbridge",
            "tool_name": "quote",
            "ok": ok,
            "latency_ms": index,
            "source": "runtime",
            "created_at": _iso(minutes=20 - index),
            "metadata": {},
        }
        es.docs.setdefault("tool-metrics", {})[doc["id"]] = doc

    result = service.get_recent_tool_calls(limit=11, tool_domain="longbridge")
    items = result["items"]

    assert items[0]["rolling_window_size"] == 1
    assert items[0]["agent_name"] == "unknown"
    assert items[-1]["rolling_window_size"] == 10
    assert items[-1]["rolling_success_rate_10"] == 0.6
    assert abs(items[-1]["rolling_failure_rate_10"] - 0.4) < 0.00001


def test_recent_llm_calls_have_complete_fields():
    service, _es = _service()
    service.record_llm_call(
        run_id="r1",
        session_id="s",
        task_id="task1",
        agent_name="trade_decision",
        node_name="market_trend",
        provider="deepseek",
        model="deepseek-v4",
        call_type="sub_agent",
        ok=True,
        latency_ms=123,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )

    item = service.get_recent_llm_calls(limit=10)["items"][0]

    assert item["agent_name"] == "trade_decision"
    assert item["node_name"] == "market_trend"
    assert item["task_id"] == "task1"
    assert item["rolling_success_rate_10"] == 1
    assert item["total_tokens"] == 15


def test_llm_metrics_group_by_model():
    service, _es = _service()
    service.record_llm_call(run_id="r", session_id="s", provider="deepseek", model="deepseek-v4-pro", call_type="planner", ok=True, latency_ms=4000, prompt_tokens=1000, completion_tokens=300, total_tokens=1300)
    service.record_llm_call(run_id="r", session_id="s", provider="xiaomi", model="mimo-2.5-pro", call_type="planner", ok=False, latency_ms=6000, prompt_tokens=500, completion_tokens=0, total_tokens=500)

    result = service.get_llm_metrics(hours=24, bucket="1h")

    models = {item["model"]: item for item in result["models"]}
    assert set(models) == {"deepseek-v4-pro", "mimo-2.5-pro"}
    assert models["deepseek-v4-pro"]["series"][0]["avg_total_tokens"] == 1300
    assert models["mimo-2.5-pro"]["series"][0]["failure_rate"] == 1.0


def test_failures_returns_tool_and_llm_failures():
    service, _es = _service()
    service.record_tool_call(run_id="r1", session_id="s", tool_name="longbridge_call_public_tool", ok=False, latency_ms=123, error_code="MCP_ERROR", error_message="bad")
    service.record_llm_call(run_id="r2", session_id="s", provider="deepseek", model="deepseek-v4-pro", call_type="planner", ok=False, latency_ms=456, error_code="PROVIDER_ERROR", error_message="bad llm")

    result = service.get_recent_failures(hours=24, limit=10)

    kinds = {item["kind"] for item in result["items"]}
    assert kinds == {"tool", "llm"}
    assert {item["domain"] for item in result["items"]} == {"longbridge", "llm"}


def test_overview_unknown_when_no_data():
    service, _es = _service()
    result = service.get_monitoring_overview(hours=24, bucket="1h")

    assert result["ibkr"]["status"] == "unknown"
    assert result["longbridge"]["status"] == "unknown"
    assert result["llm"]["status"] == "unknown"


def test_metrics_api_does_not_leak_sensitive_fields():
    service, _es = _service()
    service.record_tool_call(
        run_id="r",
        session_id="s",
        tool_name="ibkr_get_positions",
        ok=False,
        error_code="ERR",
        error_message="authorization: secret",
        metadata={"api_key": "secret", "safe": "yes", "prompt": "raw prompt"},
    )
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    app.dependency_overrides[get_account_copilot_monitoring_service] = lambda: service
    try:
        client = TestClient(app)
        payload = client.get("/api/agent/account-copilot/monitoring/failures").json()
    finally:
        app.dependency_overrides.clear()

    text = json.dumps(payload, ensure_ascii=False).lower()
    assert "api_key" not in text
    assert "cookie" not in text
    assert "authorization:" not in text
    assert "raw prompt" not in text
    assert "secret" not in text


def test_recent_monitoring_api_returns_tool_and_llm_items():
    service, _es = _service()
    service.record_tool_call(
        run_id="r",
        session_id="s",
        agent_name="trade_decision",
        node_name="event_catalyst",
        tool_name="news_search",
        tool_domain="longbridge",
        ok=False,
        latency_ms=123,
        empty_result=True,
    )
    service.record_llm_call(
        run_id="r",
        session_id="s",
        agent_name="trade_decision",
        node_name="event_catalyst",
        provider="deepseek",
        model="deepseek-v4",
        call_type="sub_agent",
        ok=True,
        latency_ms=456,
    )
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    app.dependency_overrides[get_account_copilot_monitoring_service] = lambda: service
    try:
        client = TestClient(app)
        tool_payload = client.get("/api/agent/account-copilot/monitoring/tool-calls/recent?agent_name=trade_decision&tool_domain=longbridge").json()
        llm_payload = client.get("/api/agent/account-copilot/monitoring/llm-calls/recent?agent_name=trade_decision").json()
    finally:
        app.dependency_overrides.clear()

    assert tool_payload["items"][0]["tool_name"] == "news_search"
    assert tool_payload["items"][0]["empty_result"] is True
    assert llm_payload["items"][0]["model"] == "deepseek-v4"
    assert llm_payload["items"][0]["rolling_window_size"] == 1


def test_monitoring_write_failure_does_not_break_runtime():
    registry = AccountCopilotToolRegistry()
    registry.register(
        AccountCopilotToolSpec(
            name="ibkr_get_positions",
            description="positions",
            schema={"name": "ibkr_get_positions", "parameters": {}},
            handler=lambda: {"ok": True, "data": {"positions": []}},
        )
    )
    action = CopilotPlannerAction(
        action_type="call_tool",
        thought_summary="call tool",
        evidence_sufficiency=EvidenceSufficiency(is_sufficient=False, missing_information=[], confidence="low"),
        tool_name="ibkr_get_positions",
        tool_arguments={},
    )
    runtime = AccountCopilotRuntime(FakeLLM(), registry, monitoring_service=AccountCopilotMonitoringService(FailingRepository()))

    observation, tool_call = runtime._execute_tool_action(action, {"id": "a", "run_id": "r", "session_id": "s"}, 1)

    assert observation["ok"] is True
    assert tool_call["ok"] is True
