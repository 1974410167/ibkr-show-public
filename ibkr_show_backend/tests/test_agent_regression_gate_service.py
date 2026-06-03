from __future__ import annotations

import pytest

from app.services.agent_regression_gate_service import AgentRegressionGateService


class _FakeImpactServiceForGate:
    def __init__(self, impact_result: dict | None = None, *, raise_error: Exception | None = None) -> None:
        self._result = impact_result or self._default_impact()
        self._raise = raise_error

    @staticmethod
    def _default_impact() -> dict:
        return {
            "impacted_agents": [],
            "unmatched_files": [],
            "summary": {"changed_file_count": 0, "impacted_agent_count": 0, "recommended_run_count": 0},
        }

    def analyze_changed_files(self, changed_files, *, base_ref=None, head_ref=None, include_payload=True):
        if self._raise:
            raise self._raise
        return self._result

    def analyze_git_diff(self, base_ref, head_ref, *, include_payload=True):
        if self._raise:
            raise self._raise
        return self._result


class _FakeEvalServiceForGate:
    def __init__(self, results: dict | None = None, *, raise_error: Exception | None = None) -> None:
        self._results = results or {}
        self._raise = raise_error
        self.calls: list[dict] = []

    def run_agent_regression_eval(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self._raise:
            raise self._raise
        agent_name = payload.get("agent_name", "unknown")
        return self._results.get(agent_name, {
            "eval_run": {"eval_run_id": f"eval-{agent_name}"},
            "gate_result": {"passed": True, "reasons": []},
            "selected_case_count": 5,
        })


def _make_impact_with_agent(agent_name: str, recommended: bool = True) -> dict:
    return {
        "impacted_agents": [{
            "agent_name": agent_name,
            "confidence": "high",
            "matched_files": ["some/file.py"],
            "impacted_nodes": [],
            "profile_exists": True,
            "profile_enabled": True,
            "trigger_policy_on_code_change": True,
            "recommended": recommended,
            "reason": "agent/node files changed",
            "regression_payload": {"agent_name": agent_name, "mode": "static", "limit": 100},
        }],
        "unmatched_files": [],
        "summary": {"changed_file_count": 1, "impacted_agent_count": 1, "recommended_run_count": 1 if recommended else 0},
    }


class TestRegressionGate:
    def test_dry_run_with_recommended_agent(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(
            changed_files=["file.py"], dry_run=True,
        )

        assert result["ok"] is True
        assert result["dry_run"] is True
        assert result["summary"]["recommended_run_count"] == 1
        assert result["summary"]["executed_run_count"] == 0
        assert len(result["runs"]) == 1
        assert result["runs"][0]["dry_run"] is True
        assert result["runs"][0]["agent_name"] == "trade_decision"
        assert len(eval_svc.calls) == 0

    def test_no_impacted_agents_ok(self):
        impact_svc = _FakeImpactServiceForGate()
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is True
        assert result["summary"]["recommended_run_count"] == 0
        assert "no recommended regression runs" in result["reasons"]

    def test_run_recommended_agent_gate_passed(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate({
            "trade_decision": {
                "eval_run": {"eval_run_id": "eval-td-1"},
                "gate_result": {"passed": True, "reasons": []},
                "selected_case_count": 5,
            }
        })
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is True
        assert result["summary"]["executed_run_count"] == 1
        assert result["summary"]["passed_run_count"] == 1
        assert result["summary"]["failed_run_count"] == 0
        assert result["runs"][0]["gate_passed"] is True
        assert result["runs"][0]["eval_run_id"] == "eval-td-1"
        assert len(eval_svc.calls) == 1

    def test_run_recommended_agent_gate_failed(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate({
            "trade_decision": {
                "eval_run": {"eval_run_id": "eval-td-1"},
                "gate_result": {"passed": False, "reasons": ["critical_failure_count 1 > 0"]},
                "selected_case_count": 5,
            }
        })
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is False
        assert result["summary"]["failed_run_count"] == 1
        assert result["runs"][0]["gate_passed"] is False
        assert any("trade_decision" in r for r in result["reasons"])
        assert any("critical_failure_count" in r for r in result["reasons"])

    def test_run_exception_records_error(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate(raise_error=RuntimeError("connection failed"))
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is False
        assert result["summary"]["failed_run_count"] == 1
        assert result["runs"][0]["error"] == "connection failed"
        assert any("connection failed" in r for r in result["reasons"])

    def test_max_agents_exceeded_raises(self):
        agents = []
        for i in range(5):
            agents.append({
                "agent_name": f"agent_{i}",
                "confidence": "high",
                "matched_files": [],
                "impacted_nodes": [],
                "profile_exists": True,
                "profile_enabled": True,
                "trigger_policy_on_code_change": True,
                "recommended": True,
                "reason": "test",
                "regression_payload": {"agent_name": f"agent_{i}"},
            })
        impact_result = {
            "impacted_agents": agents,
            "unmatched_files": [],
            "summary": {"changed_file_count": 5, "impacted_agent_count": 5, "recommended_run_count": 5},
        }
        impact_svc = _FakeImpactServiceForGate(impact_result)
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        with pytest.raises(ValueError, match="max_agents"):
            gate_svc.run_regression_gate(changed_files=["file.py"], max_agents=3)

    def test_run_not_recommended_flag(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision", recommended=False))
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(
            changed_files=["file.py"], run_not_recommended=True,
        )

        assert result["summary"]["recommended_run_count"] == 1
        assert len(eval_svc.calls) == 1

    def test_skip_not_recommended_by_default(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision", recommended=False))
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["summary"]["recommended_run_count"] == 0
        assert len(eval_svc.calls) == 0

    def test_multiple_agents_mixed_results(self):
        impact_result = {
            "impacted_agents": [
                {
                    "agent_name": "trade_decision",
                    "confidence": "high", "matched_files": [], "impacted_nodes": [],
                    "profile_exists": True, "profile_enabled": True,
                    "trigger_policy_on_code_change": True, "recommended": True,
                    "reason": "test",
                    "regression_payload": {"agent_name": "trade_decision"},
                },
                {
                    "agent_name": "trade_review",
                    "confidence": "high", "matched_files": [], "impacted_nodes": [],
                    "profile_exists": True, "profile_enabled": True,
                    "trigger_policy_on_code_change": True, "recommended": True,
                    "reason": "test",
                    "regression_payload": {"agent_name": "trade_review"},
                },
            ],
            "unmatched_files": [],
            "summary": {"changed_file_count": 2, "impacted_agent_count": 2, "recommended_run_count": 2},
        }
        impact_svc = _FakeImpactServiceForGate(impact_result)
        eval_svc = _FakeEvalServiceForGate({
            "trade_decision": {
                "eval_run": {"eval_run_id": "eval-td"},
                "gate_result": {"passed": True, "reasons": []},
            },
            "trade_review": {
                "eval_run": {"eval_run_id": "eval-tr"},
                "gate_result": {"passed": False, "reasons": ["min_pass_rate 0.5 < 0.9"]},
            },
        })
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is False
        assert result["summary"]["passed_run_count"] == 1
        assert result["summary"]["failed_run_count"] == 1
        assert len(eval_svc.calls) == 2

    def test_requires_input(self):
        impact_svc = _FakeImpactServiceForGate()
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        with pytest.raises(ValueError, match="provide"):
            gate_svc.run_regression_gate()

    def test_git_diff_mode(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(
            base_ref="origin/main", head_ref="HEAD", dry_run=True,
        )

        assert result["ok"] is True
        assert result["base_ref"] == "origin/main"
        assert result["head_ref"] == "HEAD"

    def test_agent_without_payload_skipped(self):
        impact_result = {
            "impacted_agents": [{
                "agent_name": "trade_decision",
                "confidence": "high", "matched_files": [], "impacted_nodes": [],
                "profile_exists": False, "profile_enabled": False,
                "trigger_policy_on_code_change": False, "recommended": False,
                "reason": "missing profile",
                "regression_payload": None,
            }],
            "unmatched_files": [],
            "summary": {"changed_file_count": 1, "impacted_agent_count": 1, "recommended_run_count": 0},
        }
        impact_svc = _FakeImpactServiceForGate(impact_result)
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)

        result = gate_svc.run_regression_gate(changed_files=["file.py"])

        assert result["ok"] is True
        assert len(result["runs"]) == 0


class _FakeReportRepository:
    def __init__(self) -> None:
        self.reports: dict[str, dict] = {}

    def save_report(self, report: dict) -> dict:
        self.reports[report["report_id"]] = report
        return report

    def get_report(self, report_id: str) -> dict | None:
        return self.reports.get(report_id)

    def list_reports(self, **kwargs) -> list[dict]:
        items = list(self.reports.values())
        if kwargs.get("status"):
            items = [r for r in items if r.get("status") == kwargs["status"]]
        if kwargs.get("trigger"):
            items = [r for r in items if r.get("trigger") == kwargs["trigger"]]
        if kwargs.get("ok") is not None:
            items = [r for r in items if r.get("ok") == kwargs["ok"]]
        if kwargs.get("dry_run") is not None:
            items = [r for r in items if r.get("dry_run") == kwargs["dry_run"]]
        if kwargs.get("agent_name"):
            aname = kwargs["agent_name"]
            items = [r for r in items if aname in r.get("impacted_agents", []) or aname in r.get("recommended_agents", [])]
        return items[:kwargs.get("limit", 100)]


class TestSaveReport:
    def test_save_report_creates_report_id(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        result = gate_svc.run_regression_gate(changed_files=["file.py"], dry_run=True, save_report=True, trigger="cli")

        assert "report_id" in result
        assert result["report_id"].startswith("regression_gate_report_")
        assert len(report_repo.reports) == 1

    def test_save_report_status_dry_run(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], dry_run=True, save_report=True)
        report = list(report_repo.reports.values())[0]
        assert report["status"] == "dry_run"
        assert report["dry_run"] is True

    def test_save_report_status_passed(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], save_report=True)
        report = list(report_repo.reports.values())[0]
        assert report["status"] == "passed"
        assert report["ok"] is True

    def test_save_report_status_failed(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate({
            "trade_decision": {
                "eval_run": {"eval_run_id": "eval-1"},
                "gate_result": {"passed": False, "reasons": ["fail"]},
            }
        })
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], save_report=True)
        report = list(report_repo.reports.values())[0]
        assert report["status"] == "failed"
        assert report["ok"] is False

    def test_save_report_status_error(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate(raise_error=RuntimeError("boom"))
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], save_report=True)
        report = list(report_repo.reports.values())[0]
        assert report["status"] == "error"
        assert report["ok"] is False

    def test_save_report_no_save_when_flag_false(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        result = gate_svc.run_regression_gate(changed_files=["file.py"], save_report=False)

        assert "report_id" not in result
        assert len(report_repo.reports) == 0

    def test_save_report_agents_populated(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], save_report=True, trigger="api_dry_run", created_by="admin")
        report = list(report_repo.reports.values())[0]
        assert "trade_decision" in report["impacted_agents"]
        assert "trade_decision" in report["recommended_agents"]
        assert report["trigger"] == "api_dry_run"
        assert report["created_by"] == "admin"

    def test_list_reports(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_svc.run_regression_gate(changed_files=["file.py"], dry_run=True, save_report=True)
        result = gate_svc.list_reports()
        assert result["summary"]["report_count"] == 1
        assert result["summary"]["dry_run_count"] == 1

    def test_get_report(self):
        impact_svc = _FakeImpactServiceForGate(_make_impact_with_agent("trade_decision"))
        eval_svc = _FakeEvalServiceForGate()
        report_repo = _FakeReportRepository()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc, report_repository=report_repo)

        gate_result = gate_svc.run_regression_gate(changed_files=["file.py"], dry_run=True, save_report=True)
        report_id = gate_result["report_id"]
        report = gate_svc.get_report(report_id)
        assert report is not None
        assert report["report_id"] == report_id

    def test_get_report_nonexistent(self):
        impact_svc = _FakeImpactServiceForGate()
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)
        assert gate_svc.get_report("nonexistent") is None

    def test_list_reports_no_repo(self):
        impact_svc = _FakeImpactServiceForGate()
        eval_svc = _FakeEvalServiceForGate()
        gate_svc = AgentRegressionGateService(impact_svc, eval_svc)
        result = gate_svc.list_reports()
        assert result["summary"]["report_count"] == 0
