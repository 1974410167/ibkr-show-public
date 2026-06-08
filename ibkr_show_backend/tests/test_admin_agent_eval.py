from fastapi.testclient import TestClient

from app.api.deps import get_agent_change_impact_service, get_agent_eval_service, get_agent_regression_gate_service, get_agent_regression_profile_service, get_baseline_health_report_service, get_eval_failure_mining_service, get_eval_simulation_service, get_failure_to_eval_case_service, get_judge_calibration_service, require_admin_session
from app.main import app

client = TestClient(app)


class FakeAgentEvalService:
    def list_cases(self, **kwargs):
        return [{"case_id": "case-1", "agent_name": "trade_review", "enabled": True, "severity": "medium", "category": ""}]

    def get_case(self, case_id: str):
        return None if case_id == "missing" else {"case_id": case_id}

    def create_case(self, payload: dict):
        return {"case_id": payload.get("case_id", "new-case"), **payload}

    def update_case(self, case_id: str, updates: dict):
        if case_id == "missing":
            return None
        return {"case_id": case_id, **updates}

    def archive_case(self, case_id: str, *, reason: str | None = None):
        if case_id == "missing":
            return None
        return {
            "case_id": case_id,
            "archived": True,
            "enabled": False,
            "archived_at": "2026-01-01T00:00:00+00:00",
            "archived_reason": reason,
        }

    def unarchive_case(self, case_id: str):
        if case_id == "missing":
            return None
        return {
            "case_id": case_id,
            "archived": False,
            "archived_at": None,
            "archived_reason": None,
        }

    def seed_builtin_cases(self, *, force: bool = False):
        return {"created_count": 1, "skipped_count": 0, "created": ["case-1"], "skipped": []}

    def build_case_from_replay(self, replay_id: str, *, save: bool = False):
        return None if replay_id == "missing" else {"case_id": "case-from-replay", "metadata": {"replay_id": replay_id}}

    def run_eval(self, **kwargs):
        return {"eval_run_id": "eval-1", "status": "completed", "summary": {"case_count": 1}, "results": []}

    def list_eval_runs(self, **kwargs):
        return {"items": [{"eval_run_id": "eval-1"}], "summary": {"run_count": 1}}

    def get_eval_run(self, eval_run_id: str):
        return None if eval_run_id == "missing" else {"eval_run_id": eval_run_id}


class FakeSyntheticSimulationService:
    def __init__(self) -> None:
        self.run = {
            "simulation_run_id": "sim-run-1",
            "status": "completed",
            "agent_names": ["trade_decision"],
            "summary": {"scenario_count": 1, "dry_run": True},
        }
        self.result = {
            "simulation_result_id": "sim-result-1",
            "simulation_run_id": "sim-run-1",
            "scenario_id": "synthetic_trade_decision_chase_high_001",
            "agent_name": "trade_decision",
            "status": "skipped",
        }

    def run_scenarios(self, **kwargs):
        if kwargs.get("executor_mode") == "bad":
            raise ValueError("Invalid executor_mode")
        self.run["config"] = kwargs
        return {"simulation_run": self.run, "results": [self.result]}

    def start_scenarios_async(self, **kwargs):
        if kwargs.get("executor_mode") == "bad":
            raise ValueError("Invalid executor_mode")
        self.run["status"] = "running"
        self.run["config"] = {**kwargs, "async_run": True}
        self.run["metadata"] = {"async_run": True, "background_thread_started": True}
        return {"simulation_run": self.run, "results": []}

    def list_runs(self, **kwargs):
        return [self.run]

    def get_run_with_results(self, simulation_run_id: str, **kwargs):
        if simulation_run_id == "missing":
            return None
        return {"simulation_run": self.run, "results": [self.result]}

    def get_result(self, simulation_result_id: str):
        if simulation_result_id == "missing":
            return None
        return self.result


class FakeFailureMiningService:
    def __init__(self) -> None:
        self.run = {
            "failure_mining_run_id": "fm-run-1",
            "simulation_run_id": "sim-run-1",
            "status": "completed",
            "summary": {"failure_count": 1, "by_agent": {"trade_decision": 1}},
        }
        self.failure = {
            "failure_id": "failure-1",
            "failure_mining_run_id": "fm-run-1",
            "simulation_run_id": "sim-run-1",
            "agent_name": "trade_decision",
            "failure_type": "missing_risk_control",
            "severity": "high",
            "should_convert_to_eval_case": True,
        }

    def mine_simulation_run(self, simulation_run_id: str, **kwargs):
        if simulation_run_id == "missing":
            raise ValueError("Simulation run not found")
        self.run["config"] = kwargs
        return {"failure_mining_run": self.run, "failures": [self.failure], "summary": self.run["summary"]}

    def list_failure_mining_runs(self, **kwargs):
        return [self.run]

    def get_failure_mining_run_with_failures(self, failure_mining_run_id: str, **kwargs):
        if failure_mining_run_id == "missing":
            return None
        return {"failure_mining_run": self.run, "failures": [self.failure], "summary": self.run["summary"]}

    def list_failure_items(self, **kwargs):
        return {"items": [self.failure], "summary": {"failure_count": 1}}

    def get_failure_item(self, failure_id: str):
        if failure_id == "missing":
            return None
        return self.failure


class FakeFailureToCaseService:
    def preview_case_from_failure(self, failure_id: str, *, enabled: bool = False):
        if failure_id == "missing":
            raise ValueError("Failure item not found")
        return {
            "draft": {
                "draft_id": "draft-1",
                "failure_id": failure_id,
                "case_payload": {"case_id": "case-1", "enabled": enabled},
                "quality_score": 0.9,
            },
            "quality": {"eligible": True, "quality_score": 0.9, "warnings": []},
            "duplicate": None,
        }

    def convert_failure_to_case(self, failure_id: str, *, enabled: bool = False, force: bool = False):
        if failure_id == "missing":
            raise ValueError("Failure item not found")
        return {
            "failure_id": failure_id,
            "draft_id": "draft-1",
            "case_id": "case-1",
            "status": "saved",
            "reason": "ok",
            "case_payload": {"case_id": "case-1", "enabled": enabled},
            "metadata": {"forced": force},
        }

    def batch_convert_failures(self, **kwargs):
        return {
            "converted_count": 1,
            "skipped_count": 0,
            "duplicate_count": 0,
            "error_count": 0,
            "results": [{"failure_id": "failure-1", "status": "saved", "case_id": "case-1"}],
        }


class FakeBaselineHealthReportService:
    def __init__(self) -> None:
        self.report = {
            "report_id": "report-1",
            "status": "completed",
            "summary": {"failure_count": 1},
            "by_agent": [{"agent_name": "trade_decision"}],
            "markdown_report": "# Eval P3.5 Baseline Health Report\n\n## Summary\n",
        }

    def generate_report(self, **kwargs):
        self.report["config"] = kwargs
        return self.report

    def list_reports(self, **kwargs):
        return [self.report]

    def get_report(self, report_id: str):
        if report_id == "missing":
            return None
        return self.report


class FakeJudgeCalibrationService:
    def __init__(self) -> None:
        self.run = {
            "calibration_run_id": "cal-run-1",
            "source_type": "failure_mining_run",
            "source_id": "fm-run-1",
            "status": "completed",
            "summary": {"signal_count": 1, "by_agent": {"trade_decision": 1}},
            "suggestions": [{"suggestion_id": "suggestion-1"}],
        }
        self.signal = {
            "signal_id": "signal-1",
            "calibration_run_id": "cal-run-1",
            "agent_name": "trade_decision",
            "signal_type": "judge_too_lenient",
            "priority": 90,
            "should_create_calibration_case": True,
        }

    def detect_calibration_signals(self, **kwargs):
        self.run["config"] = kwargs
        return {"calibration_run": self.run, "signals": [self.signal], "suggestions": self.run["suggestions"], "summary": self.run["summary"]}

    def list_runs(self, **kwargs):
        return [self.run]

    def get_run_with_signals(self, calibration_run_id: str, **kwargs):
        if calibration_run_id == "missing":
            return None
        return {"calibration_run": self.run, "signals": [self.signal], "suggestions": self.run["suggestions"], "summary": self.run["summary"]}

    def list_signals(self, **kwargs):
        return {"items": [self.signal], "summary": {"signal_count": 1}}

    def get_signal(self, signal_id: str):
        if signal_id == "missing":
            return None
        return self.signal

    def preview_calibration_case(self, signal_id: str, *, enabled: bool = False):
        if signal_id == "missing":
            raise ValueError("Judge calibration signal not found")
        return {
            "draft": {
                "draft_id": "draft-1",
                "signal_id": signal_id,
                "case_payload": {"case_id": "case-1", "enabled": enabled, "source": "judge_calibration_mined"},
                "quality_score": 0.9,
            },
            "quality": {"eligible": True},
            "duplicate": None,
        }

    def create_calibration_case(self, signal_id: str, *, enabled: bool = False, force: bool = False):
        if signal_id == "missing":
            raise ValueError("Judge calibration signal not found")
        return {"signal_id": signal_id, "case_id": "case-1", "status": "saved", "case_payload": {"enabled": enabled}, "metadata": {"forced": force}}

    def batch_create_calibration_cases(self, **kwargs):
        return {"created_count": 1, "skipped_count": 0, "duplicate_count": 0, "error_count": 0, "results": [{"signal_id": "signal-1", "status": "saved"}]}


def test_admin_agent_eval_requires_login() -> None:
    response = client.get("/api/admin/agent-eval/cases")
    assert response.status_code == 401


def test_admin_agent_eval_routes() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalService()
    try:
        cases = client.get("/api/admin/agent-eval/cases")
        case = client.get("/api/admin/agent-eval/cases/case-1")
        seed = client.post("/api/admin/agent-eval/cases/seed")
        from_replay = client.post("/api/admin/agent-eval/cases/from-replay/replay-1")
        run = client.post("/api/admin/agent-eval/runs", json={"replay_ids": ["replay-1"], "mode": "static"})
        runs = client.get("/api/admin/agent-eval/runs")
        run_detail = client.get("/api/admin/agent-eval/runs/eval-1")
        missing = client.get("/api/admin/agent-eval/runs/missing")
    finally:
        app.dependency_overrides.clear()

    assert cases.status_code == 200
    assert cases.json()["items"][0]["case_id"] == "case-1"
    assert case.json()["case_id"] == "case-1"
    assert seed.json()["created_count"] == 1
    assert from_replay.json()["metadata"]["replay_id"] == "replay-1"
    assert run.json()["status"] == "completed"
    assert runs.json()["summary"]["run_count"] == 1
    assert run_detail.json()["eval_run_id"] == "eval-1"
    assert missing.status_code == 404


def test_admin_agent_eval_synthetic_scenarios_list_and_detail() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    try:
        list_resp = client.get(
            "/api/admin/agent-eval/synthetic-scenarios",
            params={"agent_name": "trade_decision", "tag": "chase_high", "limit": 5},
        )
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["items"]
        assert payload["summary"]["total_count"] >= 70
        assert all(item["agent_name"] == "trade_decision" for item in payload["items"])
        assert all("chase_high" in item["tags"] for item in payload["items"])

        scenario_id = payload["items"][0]["scenario_id"]
        detail_resp = client.get(f"/api/admin/agent-eval/synthetic-scenarios/{scenario_id}")
        missing_resp = client.get("/api/admin/agent-eval/synthetic-scenarios/missing")
    finally:
        app.dependency_overrides.clear()

    assert detail_resp.status_code == 200
    assert detail_resp.json()["scenario_id"] == scenario_id
    assert missing_resp.status_code == 404


def test_admin_agent_eval_simulation_routes_default_dry_run() -> None:
    svc = FakeSyntheticSimulationService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_eval_simulation_service] = lambda: svc
    try:
        run_resp = client.post(
            "/api/admin/agent-eval/simulations/run",
            json={"agent_name": "trade_decision", "tag": "chase_high", "limit": 1},
        )
        runs_resp = client.get("/api/admin/agent-eval/simulations/runs")
        detail_resp = client.get("/api/admin/agent-eval/simulations/runs/sim-run-1")
        result_resp = client.get("/api/admin/agent-eval/simulations/results/sim-result-1")
        missing_run = client.get("/api/admin/agent-eval/simulations/runs/missing")
        missing_result = client.get("/api/admin/agent-eval/simulations/results/missing")
    finally:
        app.dependency_overrides.clear()

    assert run_resp.status_code == 200
    assert run_resp.json()["simulation_run"]["simulation_run_id"] == "sim-run-1"
    assert run_resp.json()["simulation_run"]["config"]["dry_run"] is True
    assert runs_resp.json()["items"][0]["simulation_run_id"] == "sim-run-1"
    assert detail_resp.json()["results"][0]["simulation_result_id"] == "sim-result-1"
    assert result_resp.json()["simulation_result_id"] == "sim-result-1"
    assert missing_run.status_code == 404
    assert missing_result.status_code == 404


def test_admin_agent_eval_simulation_run_supports_async_mode() -> None:
    svc = FakeSyntheticSimulationService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_eval_simulation_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/simulations/run",
            json={
                "agent_name": "daily_position_review",
                "tag": "synthetic",
                "limit": 1,
                "dry_run": False,
                "executor_mode": "real",
                "async_run": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["simulation_run"]["status"] == "running"
    assert data["simulation_run"]["config"]["async_run"] is True
    assert data["simulation_run"]["metadata"]["background_thread_started"] is True
    assert data["results"] == []


def test_admin_agent_eval_simulation_run_returns_400_on_invalid_selector() -> None:
    svc = FakeSyntheticSimulationService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_eval_simulation_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/simulations/run",
            json={"executor_mode": "bad"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "Invalid executor_mode" in resp.json()["detail"]


def test_admin_agent_eval_failure_mining_routes() -> None:
    svc = FakeFailureMiningService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_eval_failure_mining_service] = lambda: svc
    try:
        run_resp = client.post(
            "/api/admin/agent-eval/failure-mining/run",
            json={"simulation_run_id": "sim-run-1", "min_severity": "medium"},
        )
        missing_run_source = client.post(
            "/api/admin/agent-eval/failure-mining/run",
            json={"simulation_run_id": "missing"},
        )
        runs_resp = client.get("/api/admin/agent-eval/failure-mining/runs")
        detail_resp = client.get("/api/admin/agent-eval/failure-mining/runs/fm-run-1")
        failures_resp = client.get(
            "/api/admin/agent-eval/failure-mining/failures",
            params={"agent_name": "trade_decision", "failure_type": "missing_risk_control"},
        )
        failure_resp = client.get("/api/admin/agent-eval/failure-mining/failures/failure-1")
        missing_run = client.get("/api/admin/agent-eval/failure-mining/runs/missing")
        missing_failure = client.get("/api/admin/agent-eval/failure-mining/failures/missing")
    finally:
        app.dependency_overrides.clear()

    assert run_resp.status_code == 200
    assert run_resp.json()["failure_mining_run"]["failure_mining_run_id"] == "fm-run-1"
    assert run_resp.json()["failure_mining_run"]["config"]["include_judge"] is False
    assert run_resp.json()["failure_mining_run"]["config"]["include_dry_run_results"] is False
    assert missing_run_source.status_code == 404
    assert runs_resp.json()["items"][0]["failure_mining_run_id"] == "fm-run-1"
    assert detail_resp.json()["failures"][0]["failure_id"] == "failure-1"
    assert failures_resp.json()["items"][0]["failure_type"] == "missing_risk_control"
    assert failure_resp.json()["failure_id"] == "failure-1"
    assert missing_run.status_code == 404
    assert missing_failure.status_code == 404


def test_admin_agent_eval_failure_to_case_routes() -> None:
    svc = FakeFailureToCaseService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_failure_to_eval_case_service] = lambda: svc
    try:
        preview = client.post(
            "/api/admin/agent-eval/failure-mining/failures/failure-1/preview-case",
            json={"enabled": False},
        )
        convert = client.post(
            "/api/admin/agent-eval/failure-mining/failures/failure-1/convert-case",
            json={"enabled": False, "force": False},
        )
        batch = client.post(
            "/api/admin/agent-eval/failure-mining/convert-cases",
            json={"failure_ids": ["failure-1"], "max_cases": 1},
        )
        missing = client.post("/api/admin/agent-eval/failure-mining/failures/missing/preview-case", json={})
    finally:
        app.dependency_overrides.clear()

    assert preview.status_code == 200
    assert preview.json()["draft"]["case_payload"]["enabled"] is False
    assert convert.status_code == 200
    assert convert.json()["status"] == "saved"
    assert convert.json()["case_payload"]["enabled"] is False
    assert batch.status_code == 200
    assert batch.json()["converted_count"] == 1
    assert missing.status_code == 404


def test_admin_agent_eval_baseline_health_routes() -> None:
    svc = FakeBaselineHealthReportService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_baseline_health_report_service] = lambda: svc
    try:
        create = client.post(
            "/api/admin/agent-eval/baseline-health/reports",
            json={"simulation_run_id": "sim-1", "failure_mining_run_id": "fm-1"},
        )
        list_resp = client.get("/api/admin/agent-eval/baseline-health/reports")
        detail = client.get("/api/admin/agent-eval/baseline-health/reports/report-1")
        markdown = client.get("/api/admin/agent-eval/baseline-health/reports/report-1/markdown")
        missing = client.get("/api/admin/agent-eval/baseline-health/reports/missing")
        missing_md = client.get("/api/admin/agent-eval/baseline-health/reports/missing/markdown")
    finally:
        app.dependency_overrides.clear()

    assert create.status_code == 200
    assert create.json()["report_id"] == "report-1"
    assert create.json()["config"]["include_converted_cases"] is True
    assert list_resp.json()["items"][0]["report_id"] == "report-1"
    assert detail.json()["report_id"] == "report-1"
    assert "Summary" in markdown.json()["markdown_report"]
    assert missing.status_code == 404
    assert missing_md.status_code == 404


def test_admin_agent_eval_judge_calibration_routes() -> None:
    svc = FakeJudgeCalibrationService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_judge_calibration_service] = lambda: svc
    try:
        run_resp = client.post(
            "/api/admin/agent-eval/judge-calibration/run",
            json={"failure_mining_run_id": "fm-run-1", "min_priority": 50},
        )
        runs_resp = client.get("/api/admin/agent-eval/judge-calibration/runs")
        detail_resp = client.get("/api/admin/agent-eval/judge-calibration/runs/cal-run-1")
        signals_resp = client.get("/api/admin/agent-eval/judge-calibration/signals", params={"signal_type": "judge_too_lenient"})
        signal_resp = client.get("/api/admin/agent-eval/judge-calibration/signals/signal-1")
        preview = client.post("/api/admin/agent-eval/judge-calibration/signals/signal-1/preview-case", json={"enabled": False})
        create = client.post("/api/admin/agent-eval/judge-calibration/signals/signal-1/create-case", json={"enabled": False})
        batch = client.post("/api/admin/agent-eval/judge-calibration/create-cases", json={"calibration_run_id": "cal-run-1", "max_cases": 1})
        missing_run = client.get("/api/admin/agent-eval/judge-calibration/runs/missing")
        missing_signal = client.get("/api/admin/agent-eval/judge-calibration/signals/missing")
        missing_preview = client.post("/api/admin/agent-eval/judge-calibration/signals/missing/preview-case", json={})
    finally:
        app.dependency_overrides.clear()

    assert run_resp.status_code == 200
    assert run_resp.json()["calibration_run"]["calibration_run_id"] == "cal-run-1"
    assert run_resp.json()["calibration_run"]["config"]["deduplicate"] is True
    assert runs_resp.json()["items"][0]["calibration_run_id"] == "cal-run-1"
    assert detail_resp.json()["signals"][0]["signal_id"] == "signal-1"
    assert signals_resp.json()["items"][0]["signal_type"] == "judge_too_lenient"
    assert signal_resp.json()["signal_id"] == "signal-1"
    assert preview.json()["draft"]["case_payload"]["enabled"] is False
    assert create.json()["status"] == "saved"
    assert create.json()["case_payload"]["enabled"] is False
    assert batch.json()["created_count"] == 1
    assert missing_run.status_code == 404
    assert missing_signal.status_code == 404
    assert missing_preview.status_code == 404


def test_admin_agent_eval_create_and_update_case() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalService()
    try:
        create_resp = client.post(
            "/api/admin/agent-eval/cases",
            json={"case_id": "new-1", "agent_name": "trade_review", "title": "Test"},
        )
        assert create_resp.status_code == 200
        assert create_resp.json()["case_id"] == "new-1"

        update_resp = client.patch(
            "/api/admin/agent-eval/cases/new-1",
            json={"title": "Updated", "severity": "high", "enabled": False, "expected_tools": ["tool_a"]},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["title"] == "Updated"
        assert update_resp.json()["severity"] == "high"
        assert update_resp.json()["enabled"] is False

        missing_resp = client.patch(
            "/api/admin/agent-eval/cases/missing",
            json={"title": "Nope"},
        )
        assert missing_resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_admin_agent_eval_archive_and_unarchive_case() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalService()
    try:
        archive_resp = client.patch(
            "/api/admin/agent-eval/cases/case-1/archive",
            json={"reason": "online verification cleanup"},
        )
        unarchive_resp = client.patch("/api/admin/agent-eval/cases/case-1/unarchive")
        missing_resp = client.patch("/api/admin/agent-eval/cases/missing/archive", json={})
    finally:
        app.dependency_overrides.clear()

    assert archive_resp.status_code == 200
    assert archive_resp.json()["archived"] is True
    assert archive_resp.json()["enabled"] is False
    assert archive_resp.json()["archived_reason"] == "online verification cleanup"
    assert unarchive_resp.status_code == 200
    assert unarchive_resp.json()["archived"] is False
    assert missing_resp.status_code == 404


def test_create_case_without_case_id() -> None:
    from app.agents.eval_harness import EvalCase, new_eval_case_id
    from app.services.agent_eval_service import AgentEvalService

    class MinimalRepo:
        def __init__(self):
            self.saved = []
        def save_case(self, case):
            self.saved.append(case)
            return case
        def get_case(self, case_id):
            return None
        def list_cases(self, **kwargs):
            return []

    repo = MinimalRepo()
    svc = AgentEvalService(repo, None)

    result = svc.create_case({"agent_name": "trade_review", "title": "No case_id"})
    assert "case_id" in result
    assert result["case_id"].startswith("trade_review_case_")
    assert result["title"] == "No case_id"

    result2 = svc.create_case({"case_id": "custom-id", "agent_name": "test", "title": "With id"})
    assert result2["case_id"] == "custom-id"


# ── Agent Regression Run API Tests ────────────────────────────────────


class FakeAgentEvalServiceWithRegression(FakeAgentEvalService):
    def run_agent_regression_eval(self, payload: dict):
        if payload.get("agent_name") == "no_cases":
            from fastapi import HTTPException
            raise ValueError("No eval cases matched regression selector")
        return {
            "eval_run": {
                "eval_run_id": "reg-eval-1",
                "status": "completed",
                "config": {
                    "run_type": "agent_regression",
                    "gate_result": {"passed": True, "reasons": []},
                    "prompt": payload.get("prompt", {}),
                    "model": payload.get("model", {}),
                    "git": payload.get("git", {}),
                },
                "summary": {"case_count": 2, "pass_rate": 1.0},
            },
            "gate_result": {"passed": True, "reasons": [], "pass_rate": 1.0, "min_pass_rate": 0.95},
            "baseline_compare_result": None,
            "selected_case_count": 2,
            "skipped_judge_case_count": 0,
            "skipped_disabled_case_count": 0,
        }

    def compare_eval_runs(self, baseline_run_id, candidate_run_id):
        return {"baseline_run_id": baseline_run_id, "candidate_run_id": candidate_run_id, "summary": {}}


def test_regression_run_api_success() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithRegression()
    try:
        resp = client.post("/api/admin/agent-eval/regression-runs", json={
            "agent_name": "trade_decision",
            "mode": "static",
            "case_tag": "regression",
        })
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["eval_run"]["eval_run_id"] == "reg-eval-1"
    assert data["gate_result"]["passed"] is True
    assert data["selected_case_count"] == 2


def test_regression_run_api_no_cases_returns_400() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithRegression()
    try:
        resp = client.post("/api/admin/agent-eval/regression-runs", json={
            "agent_name": "no_cases",
        })
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "No eval cases matched" in resp.json()["detail"]


def test_regression_run_api_prompt_model_git_in_config() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithRegression()
    try:
        resp = client.post("/api/admin/agent-eval/regression-runs", json={
            "agent_name": "trade_decision",
            "prompt": {"prompt_key": "test_prompt", "prompt_version": "v1"},
            "model": {"provider": "openrouter", "model": "gpt-5"},
            "git": {"commit_sha": "abc123"},
        })
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    config = resp.json()["eval_run"]["config"]
    assert config["prompt"]["prompt_key"] == "test_prompt"
    assert config["model"]["provider"] == "openrouter"
    assert config["git"]["commit_sha"] == "abc123"


def test_regression_run_api_with_baseline() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithRegression()
    try:
        resp = client.post("/api/admin/agent-eval/regression-runs", json={
            "agent_name": "trade_decision",
            "baseline_eval_run_id": "baseline-1",
        })
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["eval_run"]["eval_run_id"] == "reg-eval-1"


def test_regression_run_api_include_judge_field() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithRegression()
    try:
        resp = client.post("/api/admin/agent-eval/regression-runs", json={
            "agent_name": "trade_decision",
            "include_judge": False,
        })
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["skipped_judge_case_count"] == 0


# ── Coverage API Tests ────────────────────────────────────────────────


class FakeAgentEvalServiceWithCoverage(FakeAgentEvalService):
    def get_eval_coverage(self, **kwargs):
        agent_name = kwargs.get("agent_name")
        include_disabled = kwargs.get("include_disabled", True)
        items = self.list_cases()
        if agent_name:
            items = [c for c in items if c.get("agent_name") == agent_name]
        if not include_disabled:
            items = [c for c in items if c.get("enabled", True)]
        by_agent = []
        agents = {c.get("agent_name") for c in items if c.get("agent_name")}
        for a in agents:
            acases = [c for c in items if c.get("agent_name") == a]
            by_agent.append({
                "agent_name": a,
                "case_count": len(acases),
                "enabled_case_count": sum(1 for c in acases if c.get("enabled", True)),
                "high_case_count": sum(1 for c in acases if c.get("severity") == "high"),
                "critical_case_count": sum(1 for c in acases if c.get("severity") == "critical"),
                "recent_pass_rate": None,
                "recent_failed_count": 0,
                "recent_error_count": 0,
                "recent_eval_run_count": 0,
                "high_critical_failure_count": 0,
                "never_evaluated_case_count": len(acases),
            })
        case_coverage = []
        for c in items:
            case_coverage.append({
                "case_id": c.get("case_id"),
                "agent_name": c.get("agent_name"),
                "title": c.get("title"),
                "enabled": c.get("enabled", True),
                "severity": c.get("severity"),
                "category": c.get("category"),
                "tags": c.get("tags"),
                "source": c.get("source"),
                "judge_enabled": c.get("judge_enabled"),
                "never_evaluated": True,
            })
        return {
            "summary": {
                "case_count": len(items),
                "enabled_case_count": sum(1 for c in items if c.get("enabled", True)),
                "disabled_case_count": sum(1 for c in items if not c.get("enabled", True)),
                "agent_count": len(agents),
                "judge_case_count": 0,
                "bad_case_source_count": 0,
                "replay_source_count": 0,
                "manual_source_count": 0,
                "recent_eval_run_count": 0,
                "recent_evaluated_case_count": 0,
                "never_evaluated_case_count": len(items),
            },
            "by_agent": by_agent,
            "by_agent_category": [],
            "by_agent_severity": [],
            "by_agent_tag": [],
            "by_source": [],
            "case_coverage": case_coverage,
            "gaps": [
                {
                    "gap_id": f"gap_{a}_no_enabled_cases" if not any(c.get("enabled", True) for c in items if c.get("agent_name") == a) else f"gap_{a}_never_evaluated",
                    "agent_name": a,
                    "gap_type": "no_enabled_cases" if not any(c.get("enabled", True) for c in items if c.get("agent_name") == a) else "never_evaluated_cases",
                    "severity": "critical" if not any(c.get("enabled", True) for c in items if c.get("agent_name") == a) else "medium",
                    "category": "coverage",
                    "title": f"{a} gap",
                    "description": "desc",
                    "evidence": {},
                    "suggested_action": "act",
                }
                for a in agents
            ],
            "recommendations": [
                {
                    "recommendation_id": f"rec_{a}_no_enabled_cases",
                    "agent_name": a,
                    "priority": "critical",
                    "title": "act",
                    "description": "desc",
                    "action_type": "create_eval_case",
                    "related_gap_ids": [],
                    "metadata": {},
                }
                for a in agents
            ],
        }


def test_coverage_api_success() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "by_agent" in data
    assert "by_agent_category" in data
    assert "case_coverage" in data
    assert data["summary"]["case_count"] == 1


def test_coverage_api_agent_name_filter() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage?agent_name=trade_review")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["summary"]["case_count"] == 1


def test_coverage_api_include_disabled_false() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage?include_disabled=false")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["case_count"] == 1


def test_coverage_api_hours_validation() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage?hours=0")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


def test_coverage_api_response_structure() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    for key in ("summary", "by_agent", "by_agent_category", "by_agent_severity", "by_agent_tag", "by_source", "case_coverage", "gaps", "recommendations"):
        assert key in data


def test_coverage_api_gaps_in_response() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["gaps"], list)
    assert len(data["gaps"]) > 0
    gap = data["gaps"][0]
    assert "gap_id" in gap
    assert "agent_name" in gap
    assert "gap_type" in gap
    assert "severity" in gap


def test_coverage_api_recommendations_in_response() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalServiceWithCoverage()
    try:
        resp = client.get("/api/admin/agent-eval/coverage")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) > 0
    rec = data["recommendations"][0]
    assert "recommendation_id" in rec
    assert "agent_name" in rec
    assert "action_type" in rec
    assert "priority" in rec


# ── Node Eval Data Model API Tests (Stage 01) ──────────────────────


class _RecordingService(FakeAgentEvalService):
    def __init__(self) -> None:
        self.list_kwargs = None
        self.created_payload = None
        self.update_payload = None
        self.update_case_id = None

    def list_cases(self, **kwargs):
        self.list_kwargs = kwargs
        return []

    def create_case(self, payload: dict):
        self.created_payload = payload
        case = dict(payload)
        case.setdefault("case_id", "new-1")
        return case

    def update_case(self, case_id: str, updates: dict):
        self.update_case_id = case_id
        self.update_payload = updates
        if case_id == "missing":
            return None
        merged = {"case_id": case_id}
        merged.update(updates)
        return merged


def test_get_cases_supports_new_node_filters() -> None:
    svc = _RecordingService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.get(
            "/api/admin/agent-eval/cases"
            "?eval_scope=node&node_name=event_catalyst"
            "&source_run_id=run_x&source_llm_call_id=llm_x"
            "&prompt_key=pk&model=gpt-5&include_archived=true"
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.list_kwargs["eval_scope"] == "node"
    assert svc.list_kwargs["node_name"] == "event_catalyst"
    assert svc.list_kwargs["source_run_id"] == "run_x"
    assert svc.list_kwargs["source_llm_call_id"] == "llm_x"
    assert svc.list_kwargs["prompt_key"] == "pk"
    assert svc.list_kwargs["model"] == "gpt-5"
    assert svc.list_kwargs["include_archived"] is True


def test_post_cases_node_scope_with_node_name_succeeds() -> None:
    svc = _RecordingService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases",
            json={
                "case_id": "node-1",
                "agent_name": "trade_decision",
                "title": "Node case",
                "eval_scope": "node",
                "node_name": "event_catalyst",
                "source_llm_call_id": "llm_1",
                "prompt_key": "pk",
                "model": "gpt-5",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.created_payload["eval_scope"] == "node"
    assert svc.created_payload["node_name"] == "event_catalyst"


def test_post_cases_invalid_eval_scope_returns_400() -> None:
    from app.agents.eval_harness import EvalCase
    from app.services.agent_eval_service import AgentEvalService

    class _Repo:
        def save_case(self, case): return case
        def get_case(self, case_id): return None
        def list_cases(self, **kwargs): return []

    real_svc = AgentEvalService(_Repo(), None)

    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: real_svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases",
            json={
                "case_id": "bad-scope",
                "agent_name": "trade_decision",
                "title": "bad",
                "eval_scope": "invalid",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "eval_scope" in resp.json()["detail"]


def test_post_cases_node_scope_without_node_name_returns_400() -> None:
    from app.services.agent_eval_service import AgentEvalService

    class _Repo:
        def save_case(self, case): return case
        def get_case(self, case_id): return None
        def list_cases(self, **kwargs): return []

    real_svc = AgentEvalService(_Repo(), None)

    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: real_svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases",
            json={
                "case_id": "node-bad",
                "agent_name": "trade_decision",
                "title": "missing node_name",
                "eval_scope": "node",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "node_name" in resp.json()["detail"]


def test_patch_cases_can_update_node_fields() -> None:
    svc = _RecordingService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.patch(
            "/api/admin/agent-eval/cases/case-1",
            json={
                "eval_scope": "node",
                "node_name": "event_catalyst",
                "source_llm_call_id": "llm_2",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.update_case_id == "case-1"
    assert svc.update_payload["eval_scope"] == "node"
    assert svc.update_payload["node_name"] == "event_catalyst"
    assert svc.update_payload["source_llm_call_id"] == "llm_2"


def test_patch_cases_invalid_eval_scope_returns_400() -> None:
    from app.services.agent_eval_service import AgentEvalService

    class _Repo:
        def __init__(self):
            self.cases = {
                "c1": {
                    "case_id": "c1", "agent_name": "trade_decision", "title": "t",
                    "enabled": True, "source": "manual", "metadata": {},
                    "expected_output_fields": [], "forbidden_behavior": [],
                    "expected_behavior": {}, "scoring_rubric": {},
                    "eval_scope": "agent",
                }
            }
        def save_case(self, case):
            self.cases[case["case_id"]] = case
            return case
        def get_case(self, case_id):
            return self.cases.get(case_id)
        def list_cases(self, **kwargs): return list(self.cases.values())

    real_svc = AgentEvalService(_Repo(), None)

    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: real_svc
    try:
        resp = client.patch(
            "/api/admin/agent-eval/cases/c1",
            json={"eval_scope": "invalid_scope"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "eval_scope" in resp.json()["detail"]


# ── Node Eval Case Builder API Tests (Stage 02) ────────────────────


class _BuilderService:
    def __init__(self) -> None:
        self.saved = False
        self.llm_call = None
        self.llm_save = None
        self.trace_run = None
        self.trace_id = None
        self.trace_save = None

    def build_case_from_llm_call(self, call_id: str, *, save: bool = False):
        self.llm_call = call_id
        self.llm_save = save
        if call_id == "missing":
            return None
        if call_id == "no_node":
            from fastapi import HTTPException
            raise ValueError("LLM call is missing node_name; cannot create node eval case")
        return {
            "case_id": "case-from-llm",
            "eval_scope": "node",
            "node_name": "event_catalyst",
            "source_llm_call_id": call_id,
            "enabled": not save,
            "source": "llm_call",
        }

    def build_case_from_node_trace(self, run_id, node_trace_id, *, save=False):
        self.trace_run = run_id
        self.trace_id = node_trace_id
        self.trace_save = save
        if run_id == "missing" or node_trace_id == "missing-trace":
            return None
        return {
            "case_id": "case-from-trace",
            "eval_scope": "node",
            "node_name": "fundamental_valuation",
            "source_node_trace_id": node_trace_id,
            "enabled": not save,
            "source": "node_trace",
        }


def test_post_cases_from_llm_call_draft() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-llm-call/llm-1?save=false",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["eval_scope"] == "node"
    assert data["node_name"] == "event_catalyst"
    assert data["source_llm_call_id"] == "llm-1"
    assert svc.llm_call == "llm-1"
    assert svc.llm_save is False


def test_post_cases_from_llm_call_save_true() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-llm-call/llm-1?save=true",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.llm_save is True


def test_post_cases_from_llm_call_not_found_returns_404() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-llm-call/missing",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "LLM call not found" in resp.json()["detail"]


def test_post_cases_from_llm_call_missing_node_name_returns_400() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-llm-call/no_node",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "node_name" in resp.json()["detail"]


def test_post_cases_from_node_trace_draft() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-node-trace/run-1/trace-1?save=false",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["eval_scope"] == "node"
    assert data["source_node_trace_id"] == "trace-1"
    assert svc.trace_run == "run-1"
    assert svc.trace_id == "trace-1"


def test_post_cases_from_node_trace_save_true() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-node-trace/run-1/trace-1?save=true",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.trace_save is True


def test_post_cases_from_node_trace_not_found_run_returns_404() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-node-trace/missing/trace-1",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


def test_post_cases_from_node_trace_not_found_trace_returns_404() -> None:
    svc = _BuilderService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/cases/from-node-trace/run-1/missing-trace",
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Agent Regression include_node_eval API Tests (Stage 05) ──────


class _RegressionService:
    def __init__(self) -> None:
        self.last_payload = None

    def run_agent_regression_eval(self, payload: dict) -> dict:
        self.last_payload = dict(payload)
        include_node_eval = bool(payload.get("include_node_eval", False))
        node_name = payload.get("node_name")
        if include_node_eval and node_name == "no_cases":
            from fastapi import HTTPException
            raise ValueError("No eval cases matched regression selector")
        return {
            "eval_run": {
                "eval_run_id": "reg-1",
                "status": "completed",
                "config": {
                    "run_type": "agent_regression",
                    "include_node_eval": include_node_eval,
                    "case_selector": {
                        "include_node_eval": include_node_eval,
                        "node_name": node_name,
                    },
                    "selected_agent_case_count": 2 if not include_node_eval else 1,
                    "selected_node_case_count": 0 if not include_node_eval else 2,
                    "scope_breakdown": {
                        "agent": {"case_count": 1, "passed_count": 1, "failed_count": 0, "error_count": 0, "pass_rate": 1.0},
                        "node": ({"case_count": 2, "passed_count": 1, "failed_count": 1, "error_count": 0, "pass_rate": 0.5} if include_node_eval else {"case_count": 0, "passed_count": 0, "failed_count": 0, "error_count": 0, "pass_rate": None}),
                        "mixed": include_node_eval,
                    },
                    "gate_result": {
                        "passed": True,
                        "reasons": [],
                        "agent_case_count": 1,
                        "agent_failed_count": 0,
                        "agent_pass_rate": 1.0,
                        "node_case_count": 2 if include_node_eval else 0,
                        "node_failed_count": 0,
                        "node_pass_rate": 1.0 if include_node_eval else None,
                    },
                },
                "summary": {"case_count": 1, "pass_rate": 1.0},
            },
            "gate_result": {
                "passed": True,
                "reasons": [],
                "agent_case_count": 1,
                "agent_failed_count": 0,
                "agent_pass_rate": 1.0,
                "node_case_count": 2 if include_node_eval else 0,
                "node_failed_count": 0,
                "node_pass_rate": 1.0 if include_node_eval else None,
            },
            "baseline_compare_result": None,
            "selected_case_count": 1,
            "selected_agent_case_count": 1,
            "selected_node_case_count": 2 if include_node_eval else 0,
            "skipped_judge_case_count": 0,
            "skipped_disabled_case_count": 0,
            "scope_breakdown": {},
        }


def test_regression_run_default_does_not_include_node_eval() -> None:
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={"agent_name": "trade_decision"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.last_payload.get("include_node_eval") is False
    assert resp.json()["selected_node_case_count"] == 0
    assert resp.json()["eval_run"]["config"]["include_node_eval"] is False


def test_regression_run_include_node_eval_true() -> None:
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={
                "agent_name": "trade_decision",
                "include_node_eval": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.last_payload.get("include_node_eval") is True
    data = resp.json()
    assert data["selected_node_case_count"] == 2
    assert data["selected_agent_case_count"] == 1
    assert "scope_breakdown" in data["eval_run"]["config"]


def test_regression_run_include_node_eval_with_node_name() -> None:
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={
                "agent_name": "trade_decision",
                "include_node_eval": True,
                "node_name": "event_catalyst",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert svc.last_payload.get("node_name") == "event_catalyst"
    assert resp.json()["eval_run"]["config"]["case_selector"]["node_name"] == "event_catalyst"


def test_regression_run_response_includes_scope_breakdown_and_node_counts() -> None:
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={
                "agent_name": "trade_decision",
                "include_node_eval": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "selected_agent_case_count" in data
    assert "selected_node_case_count" in data
    assert "scope_breakdown" in data
    gate = data["gate_result"]
    assert "agent_case_count" in gate
    assert "node_case_count" in gate
    assert "agent_pass_rate" in gate
    assert "node_pass_rate" in gate


def test_regression_run_node_failure_returns_400() -> None:
    """No matching cases at all → 400."""
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={
                "agent_name": "trade_decision",
                "include_node_eval": True,
                "node_name": "no_cases",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400


def test_regression_run_eval_run_config_includes_include_node_eval() -> None:
    svc = _RegressionService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-runs",
            json={
                "agent_name": "trade_decision",
                "include_node_eval": True,
                "node_name": "event_catalyst",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    config = resp.json()["eval_run"]["config"]
    assert config["case_selector"]["include_node_eval"] is True
    assert config["case_selector"]["node_name"] == "event_catalyst"
    assert config["selected_agent_case_count"] == 1
    assert config["selected_node_case_count"] == 2
    assert "scope_breakdown" in config


# ── Regression Profile API Tests ─────────────────────────────────────


class _FakeProfileService:
    def __init__(self) -> None:
        self.profiles: dict[str, dict] = {}

    def get_regression_profile(self, agent_name: str) -> dict | None:
        return self.profiles.get(agent_name)

    def list_regression_profiles(self, *, enabled=None, query=None, limit=100) -> dict:
        items = list(self.profiles.values())
        if enabled is not None:
            items = [p for p in items if p.get("enabled", True) == enabled]
        return {
            "items": items[:limit],
            "summary": {"profile_count": len(items), "enabled_count": sum(1 for p in items if p.get("enabled", True))},
        }

    def upsert_regression_profile(self, agent_name: str, payload: dict) -> dict:
        if not agent_name:
            raise ValueError("agent_name is required")
        if payload.get("agent_name") and payload["agent_name"] != agent_name:
            raise ValueError("agent_name mismatch")
        mode = payload.get("mode", "static")
        if mode not in {"static", "live_mock"}:
            raise ValueError(f"invalid mode '{mode}'")
        severity = payload.get("severity")
        if severity is not None and severity not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"invalid severity '{severity}'")
        limit = payload.get("limit", 100)
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        gate = payload.get("gate", {})
        min_pr = gate.get("min_pass_rate")
        if min_pr is not None and (min_pr < 0 or min_pr > 1):
            raise ValueError("min_pass_rate must be 0-1")
        max_f = gate.get("max_failed")
        if max_f is not None and max_f < 0:
            raise ValueError("max_failed must be >= 0")

        profile = {
            "profile_id": agent_name,
            "agent_name": agent_name,
            "enabled": payload.get("enabled", True),
            "mode": mode,
            "case_tag": payload.get("case_tag"),
            "severity": severity,
            "category": payload.get("category"),
            "include_disabled": payload.get("include_disabled", False),
            "include_judge": payload.get("include_judge", False),
            "include_node_eval": payload.get("include_node_eval", False),
            "node_name": payload.get("node_name"),
            "limit": limit,
            "gate": {"fail_on_critical": True, "fail_on_high": False, "min_pass_rate": 0.9, "max_failed": None, **gate},
            "trigger_policy": {"on_prompt_save": False, "on_code_change": False, "on_deploy": False},
            "notes": payload.get("notes", ""),
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "version": 1,
        }
        self.profiles[agent_name] = profile
        return profile

    def disable_regression_profile(self, agent_name: str) -> dict | None:
        profile = self.profiles.get(agent_name)
        if profile is None:
            return None
        profile["enabled"] = False
        return profile

    def build_regression_payload_from_profile(self, agent_name: str, overrides=None) -> dict:
        profile = self.profiles.get(agent_name)
        if profile is None:
            raise ValueError(f"Profile for '{agent_name}' not found")
        payload = {
            "agent_name": profile["agent_name"],
            "mode": profile.get("mode", "static"),
            "case_tag": profile.get("case_tag"),
            "severity": profile.get("severity"),
            "category": profile.get("category"),
            "include_disabled": profile.get("include_disabled", False),
            "include_judge": profile.get("include_judge", False),
            "include_node_eval": profile.get("include_node_eval", False),
            "node_name": profile.get("node_name"),
            "limit": profile.get("limit", 100),
            "gate": profile.get("gate", {}),
        }
        if overrides:
            for k, v in overrides.items():
                if v is not None:
                    payload[k] = v
        return payload


def test_regression_profile_list_empty() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-profiles")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["profile_count"] == 0


def test_regression_profile_create_and_get() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.put(
            "/api/admin/agent-eval/regression-profiles/trade_decision",
            json={"mode": "static", "case_tag": "regression", "limit": 50},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "trade_decision"
        assert data["limit"] == 50

        resp = client.get("/api/admin/agent-eval/regression-profiles/trade_decision")
        assert resp.status_code == 200
        assert resp.json()["agent_name"] == "trade_decision"
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_update() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "limit": 100, "gate": {}, "trigger_policy": {},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.put(
            "/api/admin/agent-eval/regression-profiles/trade_decision",
            json={"limit": 200, "notes": "updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["limit"] == 200
        assert resp.json()["notes"] == "updated"
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_invalid_mode_returns_400() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.put(
            "/api/admin/agent-eval/regression-profiles/trade_decision",
            json={"mode": "invalid"},
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_invalid_severity_returns_400() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.put(
            "/api/admin/agent-eval/regression-profiles/trade_decision",
            json={"severity": "ultra"},
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_min_pass_rate_gt_1_returns_400() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.put(
            "/api/admin/agent-eval/regression-profiles/trade_decision",
            json={"gate": {"min_pass_rate": 1.5}},
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_disable() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "limit": 100, "gate": {}, "trigger_policy": {},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post("/api/admin/agent-eval/regression-profiles/trade_decision/disable")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_disable_nonexistent_returns_404() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post("/api/admin/agent-eval/regression-profiles/nonexistent/disable")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_get_nonexistent_returns_404() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-profiles/nonexistent")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_build_payload() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "case_tag": "regression", "limit": 100,
        "gate": {"fail_on_critical": True, "min_pass_rate": 0.9},
        "trigger_policy": {}, "include_node_eval": False,
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-profiles/trade_decision/build-payload",
            json={"overrides": {"limit": 200}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "trade_decision"
        assert data["limit"] == 200
        assert data["mode"] == "static"
        assert data["gate"]["fail_on_critical"] is True
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_build_payload_nonexistent_returns_404() -> None:
    svc = _FakeProfileService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post("/api/admin/agent-eval/regression-profiles/nonexistent/build-payload")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_list_with_items() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "limit": 100, "gate": {}, "trigger_policy": {},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    svc.profiles["trade_review"] = {
        "profile_id": "trade_review", "agent_name": "trade_review",
        "enabled": False, "mode": "static", "limit": 100, "gate": {}, "trigger_policy": {},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["profile_count"] == 2
        assert data["summary"]["enabled_count"] == 1
        assert len(data["items"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_build_payload_with_prompt_overrides() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "case_tag": "regression", "limit": 100,
        "gate": {"fail_on_critical": True, "min_pass_rate": 0.9},
        "trigger_policy": {}, "include_node_eval": False,
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-profiles/trade_decision/build-payload",
            json={
                "overrides": {
                    "trigger": "prompt_save",
                    "name": "Prompt regression - trade_decision - trade_decision_system",
                    "prompt": {
                        "prompt_key": "trade_decision_system",
                        "prompt_version": "v3",
                        "prompt_hash": "abc123",
                        "saved_at": "2026-01-01T00:00:00+00:00",
                        "source": "admin_prompt_save",
                    },
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "trade_decision"
        assert data["trigger"] == "prompt_save"
        assert data["name"] == "Prompt regression - trade_decision - trade_decision_system"
        assert data["prompt"]["prompt_key"] == "trade_decision_system"
        assert data["prompt"]["source"] == "admin_prompt_save"
        assert data["mode"] == "static"
        assert data["gate"]["fail_on_critical"] is True
    finally:
        app.dependency_overrides.clear()


def test_regression_profile_build_payload_preserves_profile_fields() -> None:
    svc = _FakeProfileService()
    svc.profiles["trade_decision"] = {
        "profile_id": "trade_decision", "agent_name": "trade_decision",
        "enabled": True, "mode": "static", "case_tag": "regression", "limit": 50,
        "gate": {"fail_on_critical": True, "min_pass_rate": 0.9},
        "trigger_policy": {}, "include_node_eval": True, "node_name": "event_catalyst",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "version": 1,
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_profile_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-profiles/trade_decision/build-payload",
            json={"overrides": {"trigger": "prompt_save"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["include_node_eval"] is True
        assert data["node_name"] == "event_catalyst"
        assert data["limit"] == 50
        assert data["case_tag"] == "regression"
        assert data["trigger"] == "prompt_save"
    finally:
        app.dependency_overrides.clear()


# ── Impact Analysis API Tests ────────────────────────────────────────


class _FakeImpactService:
    def __init__(self) -> None:
        self.profiles: dict[str, dict] = {}

    def analyze_changed_files(self, changed_files, *, base_ref=None, head_ref=None, include_payload=True):
        if not changed_files:
            raise ValueError("changed_files is empty")
        impacted = []
        unmatched = []
        for f in changed_files:
            if "trade_decision" in f:
                profile = self.profiles.get("trade_decision")
                entry = {
                    "agent_name": "trade_decision",
                    "confidence": "high",
                    "matched_files": [f],
                    "impacted_nodes": [],
                    "profile_exists": profile is not None,
                    "profile_enabled": profile.get("enabled", True) if profile else False,
                    "trigger_policy_on_code_change": profile.get("trigger_policy", {}).get("on_code_change", False) if profile else False,
                    "recommended": bool(profile and profile.get("enabled") and profile.get("trigger_policy", {}).get("on_code_change")),
                    "reason": "agent/node files changed",
                    "regression_payload": {"agent_name": "trade_decision", "trigger": "code_change"} if profile else None,
                }
                impacted.append(entry)
            else:
                unmatched.append(f)
        recommended_count = sum(1 for a in impacted if a["recommended"])
        return {
            "impacted_agents": impacted,
            "unmatched_files": unmatched,
            "summary": {"changed_file_count": len(changed_files), "impacted_agent_count": len(impacted), "recommended_run_count": recommended_count},
        }

    def analyze_git_diff(self, base_ref, head_ref, *, include_payload=True):
        if not base_ref or not head_ref:
            raise ValueError("base_ref and head_ref are required")
        return self.analyze_changed_files(["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"], base_ref=base_ref, head_ref=head_ref, include_payload=include_payload)


def test_impact_analysis_changed_files_success() -> None:
    svc = _FakeImpactService()
    svc.profiles["trade_decision"] = {"enabled": True, "trigger_policy": {"on_code_change": True}}
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["impacted_agent_count"] == 1
        assert data["impacted_agents"][0]["agent_name"] == "trade_decision"
        assert data["impacted_agents"][0]["recommended"] is True
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_changed_files_empty_returns_400() -> None:
    svc = _FakeImpactService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": []},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_changed_files_unmatched() -> None:
    svc = _FakeImpactService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": ["ibkr_show_backend/app/services/account_service.py"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["impacted_agent_count"] == 0
        assert data["unmatched_files"] == ["ibkr_show_backend/app/services/account_service.py"]
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_git_diff_success() -> None:
    svc = _FakeImpactService()
    svc.profiles["trade_decision"] = {"enabled": True, "trigger_policy": {"on_code_change": True}}
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/git-diff",
            json={"base_ref": "origin/main", "head_ref": "HEAD"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["impacted_agent_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_git_diff_missing_ref_returns_400() -> None:
    svc = _FakeImpactService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/git-diff",
            json={"base_ref": "", "head_ref": "HEAD"},
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_profile_disabled_recommended_false() -> None:
    svc = _FakeImpactService()
    svc.profiles["trade_decision"] = {"enabled": False, "trigger_policy": {"on_code_change": True}}
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["impacted_agents"][0]["recommended"] is False
        assert data["impacted_agents"][0]["profile_enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_on_code_change_false_recommended_false() -> None:
    svc = _FakeImpactService()
    svc.profiles["trade_decision"] = {"enabled": True, "trigger_policy": {"on_code_change": False}}
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["impacted_agents"][0]["recommended"] is False
        assert data["impacted_agents"][0]["trigger_policy_on_code_change"] is False
    finally:
        app.dependency_overrides.clear()


def test_impact_analysis_profile_missing_recommended_false() -> None:
    svc = _FakeImpactService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_change_impact_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/impact-analysis/changed-files",
            json={"changed_files": ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["impacted_agents"][0]["profile_exists"] is False
        assert data["impacted_agents"][0]["recommended"] is False
        assert data["impacted_agents"][0]["regression_payload"] is None
    finally:
        app.dependency_overrides.clear()


# ── Regression Gate Dry-Run API Tests ────────────────────────────────


class _FakeGateService:
    def __init__(self):
        self.reports: dict[str, dict] = {}

    def run_regression_gate(self, *, changed_files=None, base_ref=None, head_ref=None, dry_run=False, run_not_recommended=False, max_agents=10, save_report=False, trigger="cli", created_by=None, metadata=None):
        result = {
            "ok": True,
            "mode": "regression_gate",
            "base_ref": base_ref,
            "head_ref": head_ref,
            "dry_run": dry_run,
            "summary": {
                "changed_file_count": len(changed_files or []),
                "impacted_agent_count": 0,
                "recommended_run_count": 0,
                "executed_run_count": 0,
                "passed_run_count": 0,
                "failed_run_count": 0,
            },
            "impact_analysis": {},
            "runs": [],
            "reasons": ["no recommended regression runs"],
        }
        if save_report:
            report_id = "regression_gate_report_test123"
            self.reports[report_id] = {"report_id": report_id, "status": "dry_run" if dry_run else "passed", "ok": True, "dry_run": dry_run, "trigger": trigger}
            result["report_id"] = report_id
        return result

    def list_reports(self, **kwargs):
        items = list(self.reports.values())
        return {
            "items": items,
            "summary": {"report_count": len(items), "passed_count": 0, "failed_count": 0, "dry_run_count": len(items), "error_count": 0},
        }

    def get_report(self, report_id: str):
        return self.reports.get(report_id)


def test_regression_gate_dry_run_api() -> None:
    svc = _FakeGateService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_gate_service] = lambda: svc
    try:
        resp = client.post(
            "/api/admin/agent-eval/regression-gate/dry-run",
            json={"changed_files": ["file.py"], "max_agents": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["dry_run"] is True
        assert "report_id" in data
    finally:
        app.dependency_overrides.clear()


def test_regression_gate_list_reports() -> None:
    svc = _FakeGateService()
    svc.reports["r1"] = {"report_id": "r1", "status": "dry_run", "ok": True, "dry_run": True, "trigger": "cli"}
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_gate_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-gate/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["report_count"] == 1
        assert data["items"][0]["report_id"] == "r1"
    finally:
        app.dependency_overrides.clear()


def test_regression_gate_get_report() -> None:
    svc = _FakeGateService()
    svc.reports["r1"] = {
        "report_id": "r1",
        "status": "passed",
        "ok": True,
        "dry_run": False,
        "trigger": "cli",
        "summary": {"changed_file_count": 2, "recommended_run_count": 1, "executed_run_count": 1, "passed_run_count": 1, "failed_run_count": 0},
        "runs": [{"agent_name": "trade_decision", "gate_passed": True, "eval_run_id": "eval-1"}],
        "impact_analysis": {"impacted_agents": [{"agent_name": "trade_decision"}]},
        "reasons": [],
    }
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_gate_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-gate/reports/r1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_id"] == "r1"
        assert data["status"] == "passed"
        assert data["ok"] is True
        assert data["summary"]["executed_run_count"] == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["agent_name"] == "trade_decision"
        assert "impacted_agents" in data["impact_analysis"]
        assert data["reasons"] == []
    finally:
        app.dependency_overrides.clear()


def test_regression_gate_get_report_not_found() -> None:
    svc = _FakeGateService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_gate_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-gate/reports/nonexistent")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_regression_gate_list_reports_empty() -> None:
    svc = _FakeGateService()
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_regression_gate_service] = lambda: svc
    try:
        resp = client.get("/api/admin/agent-eval/regression-gate/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["report_count"] == 0
    finally:
        app.dependency_overrides.clear()
