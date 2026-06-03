"""Tests for the eval harness CLI."""

from __future__ import annotations

import json

import pytest

from app.cli.eval_harness import _evaluate_gate, main
from app.services.agent_eval_service import AgentEvalService


class FakeCaseRepository:
    def __init__(self) -> None:
        self.cases: dict[str, dict] = {}

    def save_case(self, case: dict) -> dict:
        self.cases[case["case_id"]] = case
        return case

    def get_case(self, case_id: str) -> dict | None:
        return self.cases.get(case_id)

    def list_cases(self, **kwargs) -> list[dict]:
        items = list(self.cases.values())
        if kwargs.get("agent_name"):
            items = [i for i in items if i.get("agent_name") == kwargs["agent_name"]]
        if kwargs.get("enabled") is not None:
            items = [i for i in items if i.get("enabled", True) == kwargs["enabled"]]
        if kwargs.get("tag"):
            items = [i for i in items if kwargs["tag"] in (i.get("tags") or [])]
        if kwargs.get("severity"):
            items = [i for i in items if i.get("severity") == kwargs["severity"]]
        return items[: kwargs.get("limit", 100)]

    def seed_builtin_cases(self, **kwargs) -> dict:
        return {"created": [], "skipped": [], "created_count": 0, "skipped_count": 0}


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def save_run(self, run: dict) -> dict:
        self.runs[run["eval_run_id"]] = run
        return run

    def get_run(self, eval_run_id: str) -> dict | None:
        return self.runs.get(eval_run_id)

    def list_runs(self, **kwargs) -> list[dict]:
        return list(self.runs.values())


def _make_case(case_id: str, **overrides) -> dict:
    base = {
        "case_id": case_id,
        "agent_name": "trade_review",
        "title": f"Case {case_id}",
        "source": "manual",
        "enabled": True,
        "severity": "medium",
        "category": "",
        "tags": [],
        "judge_enabled": False,
        "metadata": {"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    }
    base.update(overrides)
    return base


def _patch_service(monkeypatch, service):
    monkeypatch.setattr("app.cli.eval_harness._build_service", lambda: service)


def test_dry_run(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    case_repo.save_case(_make_case("c2", agent_name="trade_decision"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "2 cases matched" in out
    assert "c1" in out
    assert "c2" in out


def test_dry_run_with_agent_filter(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    case_repo.save_case(_make_case("c2", agent_name="trade_decision"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run", "--agent", "trade_decision"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "1 cases matched" in out
    assert "c2" in out


def test_dry_run_with_tag_filter(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", tags=["ci"]))
    case_repo.save_case(_make_case("c2", tags=["manual"]))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run", "--case-tag", "ci"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "1 cases matched" in out
    assert "c1" in out


def test_dry_run_with_case_id(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    case_repo.save_case(_make_case("c2"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run", "--case-id", "c1"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "1 cases matched" in out


def test_run_static(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--mode", "static", "--case-id", "c1"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Eval Run:" in out
    assert "Cases: 1" in out


def test_run_min_pass_rate_fail(monkeypatch, capsys):
    case_repo = FakeCaseRepository
    case_repo_inst = FakeCaseRepository()
    case_repo_inst.save_case(_make_case(
        "c1",
        expected_output_fields=["nonexistent_field"],
        metadata={"output": {"bad": "data"}},
    ))
    service = AgentEvalService(case_repo_inst, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--mode", "static", "--case-id", "c1", "--min-pass-rate", "0.99"])
    assert ret == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def test_run_output_json(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--mode", "static", "--case-id", "c1", "--output", "json"])
    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "ok" in data
    assert "eval_run_id" in data
    assert "summary" in data
    assert "gate" in data
    assert "skipped_judge_case_count" in data["gate"]


def test_run_json_output_skipped_judge_count(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", judge_enabled=True))
    case_repo.save_case(_make_case("c2", judge_enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--mode", "static", "--output", "json"])
    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["gate"]["skipped_judge_case_count"] == 1


def test_run_output_file(monkeypatch, tmp_path):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1"))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    outfile = str(tmp_path / "result.json")
    ret = main(["run", "--mode", "static", "--case-id", "c1", "--output", "json", "--output-file", outfile])
    assert ret == 0
    data = json.loads(Path(outfile).read_text())
    assert data["ok"] is True


def test_run_no_cases_match(monkeypatch):
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--mode", "static", "--agent", "nonexistent"])
    assert ret == 1


def test_dry_run_skips_judge_by_default(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", judge_enabled=True))
    case_repo.save_case(_make_case("c2", judge_enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "1 cases matched" in out
    assert "c2" in out
    assert "c1" not in out
    assert "1 judge-enabled cases skipped" in out


def test_dry_run_includes_judge_with_flag(monkeypatch, capsys):
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", judge_enabled=True))
    case_repo.save_case(_make_case("c2", judge_enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())
    _patch_service(monkeypatch, service)

    ret = main(["run", "--dry-run", "--include-judge"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "2 cases matched" in out
    assert "skipped" not in out


def test_gate_fail_on_critical():
    summary = {"pass_rate": 1.0, "critical_failure_count": 1, "high_priority_failure_count": 1, "failed_count": 0, "error_count": 0}

    class Args:
        fail_on_critical = True
        fail_on_high = False
        max_failed = None
        min_pass_rate = None

    gate = _evaluate_gate(summary, Args())
    assert gate["passed"] is False
    assert "critical_failure_count" in gate["reasons"][0]


def test_gate_fail_on_high():
    summary = {"pass_rate": 1.0, "critical_failure_count": 0, "high_priority_failure_count": 2, "failed_count": 0, "error_count": 0}

    class Args:
        fail_on_critical = False
        fail_on_high = True
        max_failed = None
        min_pass_rate = None

    gate = _evaluate_gate(summary, Args())
    assert gate["passed"] is False
    assert "high_priority_failure_count" in gate["reasons"][0]


def test_gate_max_failed():
    summary = {"pass_rate": 0.5, "critical_failure_count": 0, "high_priority_failure_count": 0, "failed_count": 3, "error_count": 0}

    class Args:
        fail_on_critical = False
        fail_on_high = False
        max_failed = 2
        min_pass_rate = None

    gate = _evaluate_gate(summary, Args())
    assert gate["passed"] is False
    assert "max_failed" in gate["reasons"][0]


def test_gate_pass():
    summary = {"pass_rate": 0.95, "critical_failure_count": 0, "high_priority_failure_count": 0, "failed_count": 0, "error_count": 0}

    class Args:
        fail_on_critical = True
        fail_on_high = True
        max_failed = 5
        min_pass_rate = 0.8

    gate = _evaluate_gate(summary, Args())
    assert gate["passed"] is True
    assert gate["reasons"] == []


from pathlib import Path
from unittest.mock import patch


def test_regression_gate_dry_run_json(monkeypatch, capsys):
    fake_result = {
        "ok": True,
        "mode": "regression_gate",
        "base_ref": None,
        "head_ref": None,
        "dry_run": True,
        "summary": {
            "changed_file_count": 1,
            "impacted_agent_count": 1,
            "recommended_run_count": 1,
            "executed_run_count": 0,
            "passed_run_count": 0,
            "failed_run_count": 0,
        },
        "impact_analysis": {},
        "runs": [{"agent_name": "trade_decision", "dry_run": True}],
        "reasons": [],
    }

    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: fake_result),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--dry-run", "--output", "json"])
    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True
    assert data["mode"] == "regression_gate"
    assert data["dry_run"] is True


def test_regression_gate_no_input_returns_2(monkeypatch):
    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", lambda: type("S", (), {})())
    ret = main(["regression-gate"])
    assert ret == 2


def test_regression_gate_failed_returns_1(monkeypatch, capsys):
    fake_result = {
        "ok": False,
        "mode": "regression_gate",
        "base_ref": None,
        "head_ref": None,
        "dry_run": False,
        "summary": {
            "changed_file_count": 1,
            "impacted_agent_count": 1,
            "recommended_run_count": 1,
            "executed_run_count": 1,
            "passed_run_count": 0,
            "failed_run_count": 1,
        },
        "impact_analysis": {},
        "runs": [{"agent_name": "trade_decision", "gate_passed": False}],
        "reasons": ["trade_decision gate failed"],
    }

    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: fake_result),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--output", "json"])
    assert ret == 1


def test_regression_gate_no_recommended_returns_0(monkeypatch, capsys):
    fake_result = {
        "ok": True,
        "mode": "regression_gate",
        "base_ref": None,
        "head_ref": None,
        "dry_run": False,
        "summary": {
            "changed_file_count": 1,
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

    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: fake_result),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--output", "json"])
    assert ret == 0


def test_regression_gate_text_output(monkeypatch, capsys):
    fake_result = {
        "ok": True,
        "mode": "regression_gate",
        "base_ref": "origin/main",
        "head_ref": "HEAD",
        "dry_run": True,
        "summary": {
            "changed_file_count": 2,
            "impacted_agent_count": 1,
            "recommended_run_count": 1,
            "executed_run_count": 0,
            "passed_run_count": 0,
            "failed_run_count": 0,
        },
        "impact_analysis": {},
        "runs": [{"agent_name": "trade_decision", "dry_run": True}],
        "reasons": [],
    }

    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: fake_result),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--output", "text"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "trade_decision" in out


def test_regression_gate_value_error_returns_2(monkeypatch):
    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: (_ for _ in ()).throw(ValueError("bad input"))),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--output", "json"])
    assert ret == 2


def test_regression_gate_save_report(monkeypatch, capsys):
    fake_result = {
        "ok": True,
        "mode": "regression_gate",
        "dry_run": True,
        "report_id": "regression_gate_report_abc123",
        "summary": {"changed_file_count": 1, "impacted_agent_count": 0, "recommended_run_count": 0,
                     "executed_run_count": 0, "passed_run_count": 0, "failed_run_count": 0},
        "impact_analysis": {},
        "runs": [],
        "reasons": [],
    }
    recorded = {}

    def mock_run(**kw):
        recorded.update(kw)
        return fake_result

    def mock_build():
        return type("GateSvc", (), {"run_regression_gate": staticmethod(mock_run)})()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--dry-run", "--output", "json", "--save-report"])
    assert ret == 0
    assert recorded.get("save_report") is True
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["report_id"] == "regression_gate_report_abc123"


def test_regression_gate_no_save_report_by_default(monkeypatch):
    recorded = {}

    def mock_run(**kw):
        recorded.update(kw)
        return {"ok": True, "mode": "regression_gate", "dry_run": True, "summary": {}, "impact_analysis": {}, "runs": [], "reasons": []}

    def mock_build():
        return type("GateSvc", (), {"run_regression_gate": staticmethod(mock_run)})()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--dry-run", "--output", "json"])
    assert ret == 0
    assert recorded.get("save_report") is False


def test_regression_gate_trigger_flag(monkeypatch):
    recorded = {}

    def mock_run(**kw):
        recorded.update(kw)
        return {"ok": True, "mode": "regression_gate", "dry_run": True, "summary": {}, "impact_analysis": {}, "runs": [], "reasons": []}

    def mock_build():
        return type("GateSvc", (), {"run_regression_gate": staticmethod(mock_run)})()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--dry-run", "--output", "json", "--save-report", "--trigger", "ci_deploy"])
    assert ret == 0
    assert recorded.get("trigger") == "ci_deploy"


def test_regression_gate_text_output_with_report_id(monkeypatch, capsys):
    fake_result = {
        "ok": True,
        "mode": "regression_gate",
        "dry_run": True,
        "report_id": "regression_gate_report_xyz",
        "summary": {"changed_file_count": 1, "impacted_agent_count": 0, "recommended_run_count": 0,
                     "executed_run_count": 0, "passed_run_count": 0, "failed_run_count": 0},
        "impact_analysis": {},
        "runs": [],
        "reasons": [],
    }

    def mock_build():
        return type("GateSvc", (), {
            "run_regression_gate": staticmethod(lambda **kw: fake_result),
        })()

    monkeypatch.setattr("app.cli.eval_harness._build_gate_service", mock_build)
    ret = main(["regression-gate", "--changed-file", "file.py", "--dry-run", "--output", "text"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "regression_gate_report_xyz" in out
