from __future__ import annotations

from app.services.eval_baseline_health_repository import InMemoryBaselineHealthReportRepository
from app.services.eval_baseline_health_service import BaselineHealthReportService
from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository


class FakeCaseRepository:
    def __init__(self, cases: list[dict] | None = None) -> None:
        self.cases = cases or []

    def list_cases(self, **kwargs):
        items = list(self.cases)
        if kwargs.get("source"):
            items = [item for item in items if item.get("source") == kwargs["source"]]
        return items[: kwargs.get("limit", 100)]


def _service(
    *,
    failures: list[dict] | None = None,
    results: list[dict] | None = None,
    cases: list[dict] | None = None,
) -> BaselineHealthReportService:
    report_repo = InMemoryBaselineHealthReportRepository()
    sim_repo = InMemorySyntheticSimulationRepository()
    failure_repo = InMemorySyntheticFailureMiningRepository()
    sim_repo.save_run({"simulation_run_id": "sim-1", "agent_names": ["trade_decision"], "status": "completed"})
    failure_repo.save_failure_mining_run({"failure_mining_run_id": "fm-1", "simulation_run_id": "sim-1", "status": "completed"})
    for result in results or []:
        sim_repo.save_result(result)
    for failure in failures or []:
        failure_repo.save_failure_item(failure)
    return BaselineHealthReportService(
        report_repository=report_repo,
        simulation_repository=sim_repo,
        failure_repository=failure_repo,
        case_repository=FakeCaseRepository(cases),
    )


def _failure(**overrides) -> dict:
    base = {
        "failure_id": "failure-1",
        "failure_mining_run_id": "fm-1",
        "simulation_run_id": "sim-1",
        "simulation_result_id": "result-1",
        "scenario_id": "scenario-1",
        "agent_name": "trade_decision",
        "user_question": "Should I buy?",
        "severity": "high",
        "failure_type": "missing_risk_control",
        "failed_dimensions": ["risk_awareness"],
        "failed_checks": [{"check_name": "investment_safety", "passed": False, "severity": "fatal"}],
        "judge_result": {"passed": True, "raw": {"dimension_scores": {"risk_awareness": 0.9}}},
        "output_excerpt": "buy",
        "recommendation": "Add risk controls.",
        "should_convert_to_eval_case": True,
        "conversion_priority": 90,
        "duplicate_key": "trade_decision:risk:missing_risk_control:risk_awareness",
    }
    base.update(overrides)
    return base


def test_generate_report_supports_empty_failure_data() -> None:
    service = _service()

    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert report["status"] in {"completed", "completed_with_warnings"}
    assert report["summary"]["failure_count"] == 0
    assert report["summary"]["overall_health_score"] == 1.0
    assert report["architecture_signals"][0]["signal_type"] == "no_architecture_change_needed"
    assert "## Summary" in report["markdown_report"]


def test_generate_report_aggregates_summary_agent_failure_type_and_dimension() -> None:
    failures = [
        _failure(),
        _failure(failure_id="failure-2", severity="critical", failure_type="weak_signal_overstatement", failed_dimensions=["no_signal_overstatement"], conversion_priority=100),
    ]
    results = [{"simulation_result_id": "result-1", "simulation_run_id": "sim-1", "agent_name": "trade_decision"}]
    cases = [{
        "case_id": "case-1",
        "source": "synthetic_failure",
        "agent_name": "trade_decision",
        "enabled": False,
        "metadata": {"failure_mining_run_id": "fm-1", "simulation_run_id": "sim-1"},
    }]
    service = _service(failures=failures, results=results, cases=cases)

    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert report["summary"]["failure_count"] == 2
    assert report["summary"]["critical_failure_count"] == 1
    assert report["summary"]["high_failure_count"] == 1
    assert report["summary"]["converted_case_count"] == 1
    assert report["summary"]["global_converted_case_count"] == 1
    assert report["by_agent"][0]["agent_name"] == "trade_decision"
    assert report["by_agent"][0]["failure_count"] == 2
    assert report["by_failure_type"][0]["count"] >= 1
    assert report["by_dimension"][0]["failed_count"] >= 1
    assert report["high_priority_failures"]
    assert report["recommendations"]
    assert any(signal["signal_type"] in {"need_decision_separation", "need_stronger_risk_gate"} for signal in report["architecture_signals"])
    assert "## Recommendations" in report["markdown_report"]
    assert "## Architecture Signals" in report["markdown_report"]


def test_converted_cases_are_filtered_to_report_source_with_global_count() -> None:
    cases = [
        {
            "case_id": "case-1",
            "source": "synthetic_failure",
            "agent_name": "trade_decision",
            "enabled": False,
            "metadata": {"failure_mining_run_id": "fm-1", "simulation_run_id": "sim-1"},
        },
        {
            "case_id": "case-other",
            "source": "synthetic_failure",
            "agent_name": "trade_decision",
            "enabled": False,
            "metadata": {"failure_mining_run_id": "fm-other", "simulation_run_id": "sim-other"},
        },
    ]
    service = _service(failures=[_failure()], cases=cases)

    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert report["summary"]["converted_case_count"] == 1
    assert report["summary"]["global_converted_case_count"] == 2
    assert report["converted_case_summary"]["converted_case_count"] == 1


def test_judge_calibration_signal_detects_rule_critical_but_judge_passed() -> None:
    service = _service(failures=[_failure()])

    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert any(signal["signal_type"] == "judge_too_lenient" for signal in report["judge_calibration_signals"])


def test_scenario_context_failure_points_to_scenario_fix_without_architecture_signal() -> None:
    service = _service(failures=[
        _failure(
            failure_type="scenario_missing_required_context",
            severity="medium",
            failed_dimensions=["scenario_context"],
            failed_checks=[],
            judge_result={},
            recommendation="Fix synthetic scenario context before judging agent output.",
            should_convert_to_eval_case=False,
            conversion_priority=30,
            duplicate_key="daily_position_review:scenario_missing_required_context:scenario_context",
        )
    ])

    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert report["summary"]["top_failure_type"] == "scenario_missing_required_context"
    assert report["summary"]["suggested_eval_case_count"] == 0
    assert report["by_failure_type"][0]["suggested_action"] == "Fix synthetic scenario required context fields before judging agent output quality."
    assert report["recommendations"][0]["area"] == "simulation_scenario"
    assert "context" in report["recommendations"][0]["suggested_action"]
    assert all(signal["signal_type"] not in {"need_decision_separation", "need_stronger_risk_gate"} for signal in report["architecture_signals"])


def test_report_repository_list_and_get() -> None:
    service = _service(failures=[_failure()])
    report = service.generate_report(simulation_run_id="sim-1", failure_mining_run_id="fm-1")

    assert service.get_report(report["report_id"])["report_id"] == report["report_id"]
    assert service.list_reports(agent_name="trade_decision")[0]["report_id"] == report["report_id"]
