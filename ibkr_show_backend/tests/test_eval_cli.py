"""Tests for the eval harness CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.eval_harness import _evaluate_gate, main
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository
from app.services.eval_simulation_service import SyntheticSimulationService
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


def test_synthetic_scenarios_cli_json_summary(capsys):
    ret = main(["synthetic-scenarios", "--summary", "--output", "json", "--agent-name", "trade_decision", "--limit", "2"])

    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["summary"]["total_count"] >= 70
    assert len(data["items"]) == 2
    assert all(item["agent_name"] == "trade_decision" for item in data["items"])


def test_synthetic_scenarios_cli_text_filter(capsys):
    ret = main(["synthetic-scenarios", "--summary", "--tag", "missing_data", "--limit", "3"])

    assert ret == 0
    out = capsys.readouterr().out
    assert "Synthetic scenarios:" in out
    assert "missing_data" in out or "synthetic_" in out


def _patch_simulation_service(monkeypatch):
    calls = []

    def build(*, use_in_memory: bool = False):
        calls.append(use_in_memory)
        return SyntheticSimulationService(InMemorySyntheticSimulationRepository())

    monkeypatch.setattr("app.cli.eval_harness._build_simulation_service", build)
    return calls


def test_simulation_run_cli_dry_run_json(monkeypatch, capsys):
    calls = _patch_simulation_service(monkeypatch)

    ret = main([
        "simulation-run",
        "--agent-name",
        "trade_decision",
        "--tag",
        "chase_high",
        "--limit",
        "2",
        "--dry-run",
        "--output",
        "json",
    ])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert calls == [False]
    assert data["simulation_run"]["summary"]["scenario_count"] == 2
    assert data["simulation_run"]["summary"]["dry_run"] is True
    assert len(data["results"]) == 2
    assert all(item["status"] == "skipped" for item in data["results"])


def test_simulation_run_cli_in_memory_uses_in_memory_builder(monkeypatch, capsys):
    calls = _patch_simulation_service(monkeypatch)

    ret = main([
        "simulation-run",
        "--agent-name",
        "account_copilot",
        "--limit",
        "1",
        "--in-memory",
        "--output",
        "json",
    ])

    assert ret == 0
    assert calls == [True]
    assert json.loads(capsys.readouterr().out)["results"][0]["agent_name"] == "account_copilot"


def test_simulation_run_cli_invalid_selector_returns_2(monkeypatch, capsys):
    _patch_simulation_service(monkeypatch)

    ret = main(["simulation-run", "--scenario-id", "missing", "--output", "json"])

    assert ret == 2
    err = capsys.readouterr().err
    assert "Unknown synthetic scenario_id" in err


def test_simulation_run_cli_output_file(monkeypatch, tmp_path, capsys):
    _patch_simulation_service(monkeypatch)
    outfile = tmp_path / "simulation.json"
    ret = main([
        "simulation-run",
        "--agent-name",
        "account_copilot",
        "--limit",
        "1",
        "--output",
        "json",
        "--output-file",
        str(outfile),
    ])

    assert ret == 0
    assert "Written to" in capsys.readouterr().out
    data = json.loads(outfile.read_text())
    assert data["results"][0]["agent_name"] == "account_copilot"


def test_cli_simulation_run_output_can_be_mined_with_shared_repository(monkeypatch, capsys):
    sim_repo = InMemorySyntheticSimulationRepository()
    failure_repo = None

    def build_simulation(*, use_in_memory: bool = False):
        return SyntheticSimulationService(sim_repo)

    def build_failure_mining():
        nonlocal failure_repo
        from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository
        from app.services.eval_failure_mining_service import SyntheticFailureMiningService

        failure_repo = InMemorySyntheticFailureMiningRepository()
        return SyntheticFailureMiningService(failure_repository=failure_repo, simulation_repository=sim_repo)

    monkeypatch.setattr("app.cli.eval_harness._build_simulation_service", build_simulation)
    monkeypatch.setattr("app.cli.eval_harness._build_failure_mining_service", build_failure_mining)

    sim_ret = main([
        "simulation-run",
        "--agent-name",
        "trade_decision",
        "--tag",
        "chase_high",
        "--limit",
        "1",
        "--dry-run",
        "--output",
        "json",
    ])
    sim_data = json.loads(capsys.readouterr().out)
    mining_ret = main([
        "failure-mining",
        "--simulation-run-id",
        sim_data["simulation_run"]["simulation_run_id"],
        "--include-dry-run-results",
        "--output",
        "json",
    ])
    mining_data = json.loads(capsys.readouterr().out)

    assert sim_ret == 0
    assert mining_ret == 0
    assert mining_data["failure_mining_run"]["simulation_run_id"] == sim_data["simulation_run"]["simulation_run_id"]


class FakeFailureMiningCliService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def mine_simulation_run(self, simulation_run_id: str, **kwargs):
        self.calls.append({"simulation_run_id": simulation_run_id, **kwargs})
        if simulation_run_id == "missing":
            raise ValueError("Simulation run not found")
        return {
            "failure_mining_run": {
                "failure_mining_run_id": "fm-run-1",
                "simulation_run_id": simulation_run_id,
                "status": "completed",
            },
            "failures": [
                {
                    "failure_id": "failure-1",
                    "agent_name": "trade_decision",
                    "severity": "high",
                    "failure_type": "missing_risk_control",
                }
            ],
            "summary": {"failure_count": 1, "critical_count": 0, "high_count": 1, "suggested_eval_case_count": 1},
        }


def test_failure_mining_cli_json(monkeypatch, capsys):
    service = FakeFailureMiningCliService()
    monkeypatch.setattr("app.cli.eval_harness._build_failure_mining_service", lambda: service)

    ret = main(["failure-mining", "--simulation-run-id", "sim-1", "--min-severity", "medium", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["failure_mining_run"]["failure_mining_run_id"] == "fm-run-1"
    assert data["summary"]["failure_count"] == 1
    assert service.calls[0]["include_dry_run_results"] is False


def test_failure_mining_cli_can_include_dry_run_results(monkeypatch, capsys):
    service = FakeFailureMiningCliService()
    monkeypatch.setattr("app.cli.eval_harness._build_failure_mining_service", lambda: service)

    ret = main(["failure-mining", "--simulation-run-id", "sim-1", "--include-dry-run-results", "--output", "json"])

    assert ret == 0
    capsys.readouterr()
    assert service.calls[0]["include_dry_run_results"] is True


def test_failure_mining_cli_param_error(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_failure_mining_service", lambda: FakeFailureMiningCliService())

    ret = main(["failure-mining", "--simulation-run-id", "missing", "--output", "json"])

    assert ret == 2
    assert "Simulation run not found" in capsys.readouterr().err


def test_failure_mining_cli_output_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_failure_mining_service", lambda: FakeFailureMiningCliService())
    outfile = tmp_path / "failure-mining.json"

    ret = main(["failure-mining", "--simulation-run-id", "sim-1", "--output", "json", "--output-file", str(outfile)])

    assert ret == 0
    assert "Written to" in capsys.readouterr().out
    assert json.loads(outfile.read_text())["failures"][0]["failure_id"] == "failure-1"


class FakeFailureToCaseCliService:
    def preview_case_from_failure(self, failure_id: str, *, enabled: bool = False):
        return {
            "draft": {
                "draft_id": "draft-1",
                "failure_id": failure_id,
                "case_payload": {"case_id": "case-1", "enabled": enabled},
                "quality_score": 0.9,
            },
            "quality": {"eligible": True, "quality_score": 0.9},
        }

    def convert_failure_to_case(self, failure_id: str, *, enabled: bool = False, force: bool = False):
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


def test_failure_to_case_cli_preview_json(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_failure_to_case_service", lambda: FakeFailureToCaseCliService())

    ret = main(["failure-to-case", "--failure-id", "failure-1", "--preview", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["draft"]["case_payload"]["enabled"] is False


def test_failure_to_case_cli_convert_json(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_failure_to_case_service", lambda: FakeFailureToCaseCliService())

    ret = main(["failure-to-case", "--failure-id", "failure-1", "--convert", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "saved"
    assert data["case_payload"]["enabled"] is False


def test_failure_to_case_cli_batch_output_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_failure_to_case_service", lambda: FakeFailureToCaseCliService())
    outfile = tmp_path / "failure-to-case.json"

    ret = main([
        "failure-to-case",
        "--failure-mining-run-id",
        "fm-1",
        "--batch",
        "--output",
        "json",
        "--output-file",
        str(outfile),
    ])

    assert ret == 0
    assert "Written to" in capsys.readouterr().out
    assert json.loads(outfile.read_text())["converted_count"] == 1


def test_failure_to_case_cli_requires_exactly_one_action(capsys):
    ret = main(["failure-to-case", "--failure-id", "failure-1", "--output", "json"])

    assert ret == 2
    assert "choose exactly one" in capsys.readouterr().err


class FakeBaselineHealthCliService:
    def generate_report(self, **kwargs):
        return {
            "report_id": "report-1",
            "status": "completed",
            "summary": {"overall_health_score": 0.8, "failure_count": 2, "suggested_eval_case_count": 1},
            "markdown_report": "# Eval P3.5 Baseline Health Report\n\n## Summary\n\n## Recommendations\n\n## Architecture Signals\n",
        }


def test_baseline_health_report_cli_json(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_baseline_health_report_service", lambda: FakeBaselineHealthCliService())

    ret = main(["baseline-health-report", "--simulation-run-id", "sim-1", "--failure-mining-run-id", "fm-1", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["report_id"] == "report-1"
    assert data["summary"]["failure_count"] == 2


def test_baseline_health_report_cli_markdown(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_baseline_health_report_service", lambda: FakeBaselineHealthCliService())

    ret = main(["baseline-health-report", "--output", "markdown"])

    assert ret == 0
    out = capsys.readouterr().out
    assert "# Eval P3.5 Baseline Health Report" in out
    assert "## Recommendations" in out


def test_baseline_health_report_cli_output_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_baseline_health_report_service", lambda: FakeBaselineHealthCliService())
    outfile = tmp_path / "baseline.md"

    ret = main(["baseline-health-report", "--output", "markdown", "--output-file", str(outfile)])

    assert ret == 0
    assert "Written to" in capsys.readouterr().out
    assert "Architecture Signals" in outfile.read_text()


class FakeJudgeCalibrationCliService:
    def detect_calibration_signals(self, **kwargs):
        return {
            "calibration_run": {
                "calibration_run_id": "cal-run-1",
                "source_type": "failure_mining_run",
                "source_id": kwargs.get("failure_mining_run_id"),
                "status": "completed",
            },
            "signals": [{"signal_id": "signal-1", "signal_type": "judge_too_lenient"}],
            "suggestions": [{"suggestion_id": "suggestion-1"}],
            "summary": {"signal_count": 1, "case_candidate_count": 1},
        }

    def preview_calibration_case(self, signal_id: str, *, enabled: bool = False):
        return {
            "draft": {
                "draft_id": "draft-1",
                "signal_id": signal_id,
                "case_payload": {"case_id": "case-1", "enabled": enabled},
                "quality_score": 0.9,
            },
            "quality": {"eligible": True},
        }

    def create_calibration_case(self, signal_id: str, *, enabled: bool = False, force: bool = False):
        return {
            "signal_id": signal_id,
            "case_id": "case-1",
            "status": "saved",
            "case_payload": {"enabled": enabled},
            "metadata": {"forced": force},
        }

    def batch_create_calibration_cases(self, **kwargs):
        return {
            "created_count": 1,
            "skipped_count": 0,
            "duplicate_count": 0,
            "error_count": 0,
            "results": [{"signal_id": "signal-1", "status": "saved"}],
        }


def test_judge_calibration_cli_json(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_judge_calibration_service", lambda: FakeJudgeCalibrationCliService())

    ret = main(["judge-calibration", "--failure-mining-run-id", "fm-1", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["calibration_run"]["calibration_run_id"] == "cal-run-1"
    assert data["summary"]["signal_count"] == 1


def test_judge_calibration_case_cli_preview_json(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_judge_calibration_service", lambda: FakeJudgeCalibrationCliService())

    ret = main(["judge-calibration-case", "--signal-id", "signal-1", "--preview", "--output", "json"])

    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["draft"]["case_payload"]["enabled"] is False


def test_judge_calibration_case_cli_create_and_batch(monkeypatch, capsys):
    monkeypatch.setattr("app.cli.eval_harness._build_judge_calibration_service", lambda: FakeJudgeCalibrationCliService())

    create_ret = main(["judge-calibration-case", "--signal-id", "signal-1", "--create", "--output", "json"])
    create_data = json.loads(capsys.readouterr().out)
    batch_ret = main(["judge-calibration-case", "--calibration-run-id", "cal-run-1", "--batch", "--max-cases", "1", "--output", "json"])
    batch_data = json.loads(capsys.readouterr().out)

    assert create_ret == 0
    assert create_data["status"] == "saved"
    assert create_data["case_payload"]["enabled"] is False
    assert batch_ret == 0
    assert batch_data["created_count"] == 1


def test_judge_calibration_case_cli_requires_exactly_one_action(capsys):
    ret = main(["judge-calibration-case", "--signal-id", "signal-1", "--output", "json"])

    assert ret == 2
    assert "choose exactly one" in capsys.readouterr().err


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
