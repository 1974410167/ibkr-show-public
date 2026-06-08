from __future__ import annotations

from app.agents.eval_simulation_scenarios import filter_synthetic_scenarios
from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository
from app.services.eval_judge_calibration_service import JudgeCalibrationService, build_judge_improvement_suggestions
from app.services.eval_judge_calibration_repository import InMemoryJudgeCalibrationRepository
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository


class FakeCaseRepository:
    def __init__(self) -> None:
        self.cases: dict[str, dict] = {}

    def save_case(self, case: dict) -> dict:
        self.cases[case["case_id"]] = dict(case)
        return case

    def list_cases(self, **kwargs) -> list[dict]:
        items = list(self.cases.values())
        if kwargs.get("agent_name"):
            items = [item for item in items if item.get("agent_name") == kwargs["agent_name"]]
        if kwargs.get("source"):
            items = [item for item in items if item.get("source") == kwargs["source"]]
        return items[: kwargs.get("limit", 100)]


def _scenario() -> dict:
    return filter_synthetic_scenarios(agent_name="trade_decision", tag="weak_catalyst", limit=1)[0]


def _failure(**overrides) -> dict:
    scenario = _scenario()
    base = {
        "failure_id": overrides.get("failure_id", "failure-1"),
        "failure_mining_run_id": "fm-1",
        "simulation_run_id": "sim-1",
        "simulation_result_id": f"result-{overrides.get('failure_id', 'failure-1')}",
        "scenario_id": scenario["scenario_id"],
        "agent_name": "trade_decision",
        "user_question": scenario["user_question"],
        "severity": "critical",
        "failure_type": "missing_risk_control",
        "failed_dimensions": ["risk_awareness"],
        "failed_checks": [{"check_name": "risk_awareness", "passed": False, "severity": "critical", "details": {"dimension": "risk_awareness"}}],
        "judge_result": {"passed": True, "raw": {"passed": True, "overall_score": 0.9, "dimension_scores": {"risk_awareness": 0.95}, "failed_dimensions": [], "confidence": 0.9}},
        "output_excerpt": "strong buy without risk",
        "recommendation": "Tighten judge calibration.",
        "should_convert_to_eval_case": True,
        "conversion_priority": 100,
        "duplicate_key": "trade_decision:missing_risk_control:weak_catalyst",
        "metadata": {},
    }
    base.update(overrides)
    return base


def _service(failures: list[dict]) -> tuple[JudgeCalibrationService, InMemoryJudgeCalibrationRepository, FakeCaseRepository]:
    calibration_repo = InMemoryJudgeCalibrationRepository()
    failure_repo = InMemorySyntheticFailureMiningRepository()
    simulation_repo = InMemorySyntheticSimulationRepository()
    case_repo = FakeCaseRepository()
    failure_repo.save_failure_mining_run({"failure_mining_run_id": "fm-1", "simulation_run_id": "sim-1", "status": "completed"})
    simulation_repo.save_run({"simulation_run_id": "sim-1", "agent_names": ["trade_decision"], "status": "completed"})
    for failure in failures:
        failure_repo.save_failure_item(failure)
        simulation_repo.save_result({
            "simulation_result_id": failure["simulation_result_id"],
            "simulation_run_id": failure["simulation_run_id"],
            "scenario_id": failure["scenario_id"],
            "agent_name": failure["agent_name"],
            "status": "passed",
            "user_question": failure["user_question"],
            "output": {"answer": failure["output_excerpt"]},
        })
    return JudgeCalibrationService(
        calibration_repository=calibration_repo,
        failure_repository=failure_repo,
        simulation_repository=simulation_repo,
        case_repository=case_repo,
    ), calibration_repo, case_repo


def test_detects_too_lenient_missing_dimension_rule_conflict_and_suggestions() -> None:
    service, _repo, _case_repo = _service([_failure()])

    result = service.detect_calibration_signals(failure_mining_run_id="fm-1", min_priority=50)
    signal_types = {signal["signal_type"] for signal in result["signals"]}

    assert "judge_too_lenient" in signal_types
    assert "judge_missing_dimension" in signal_types
    assert "judge_rule_conflict" in signal_types
    assert result["summary"]["signal_count"] >= 3
    assert build_judge_improvement_suggestions(result["signals"])


def test_detects_too_strict_when_rules_are_clean_but_judge_failed_vaguely() -> None:
    failure = _failure(
        severity="low",
        failure_type="other",
        failed_dimensions=[],
        failed_checks=[],
        judge_result={"passed": False, "raw": {"passed": False, "overall_score": 0.4, "failure_reasons": ["bad"], "failed_dimensions": []}},
        conversion_priority=20,
    )
    service, _repo, _case_repo = _service([failure])

    result = service.detect_calibration_signals(failure_mining_run_id="fm-1", min_priority=50)

    assert any(signal["signal_type"] == "judge_too_strict" for signal in result["signals"])


def test_detects_unstable_duplicate_low_confidence_and_parse_error() -> None:
    failures = [
        _failure(failure_id="failure-a", judge_result={"passed": True, "raw": {"passed": True, "overall_score": 0.95, "confidence": 0.4}}),
        _failure(failure_id="failure-b", simulation_result_id="result-failure-b", judge_result={"passed": False, "raw": {"passed": False, "overall_score": 0.45, "confidence": 0.8}}),
        _failure(failure_id="failure-c", duplicate_key="parse", judge_result={"raw": {"parse_failed": True, "missing_required_fields": ["passed"]}}),
    ]
    service, _repo, _case_repo = _service(failures)

    result = service.detect_calibration_signals(failure_mining_run_id="fm-1", min_priority=50, deduplicate=False)
    signal_types = {signal["signal_type"] for signal in result["signals"]}

    assert "judge_unstable_on_duplicates" in signal_types
    assert "judge_low_confidence" in signal_types
    assert "judge_parse_or_schema_error" in signal_types


def test_preview_create_duplicate_and_batch_case_flow_defaults_disabled() -> None:
    service, repo, case_repo = _service([_failure()])
    run_result = service.detect_calibration_signals(failure_mining_run_id="fm-1", min_priority=80)
    signal_id = run_result["signals"][0]["signal_id"]

    preview = service.preview_calibration_case(signal_id)
    assert preview["draft"]["case_payload"]["enabled"] is False
    assert preview["draft"]["case_payload"]["source"] == "judge_calibration_mined"
    assert preview["draft"]["case_payload"]["judge_enabled"] is True
    assert case_repo.cases == {}

    created = service.create_calibration_case(signal_id)
    duplicate = service.create_calibration_case(signal_id)

    assert created["status"] == "saved"
    assert created["case_payload"]["enabled"] is False
    assert duplicate["status"] == "duplicate"
    assert len(case_repo.cases) == 1
    assert repo.get_signal(signal_id)["converted_case_id"] == created["case_id"]

    batch = service.batch_create_calibration_cases(
        calibration_run_id=run_result["calibration_run"]["calibration_run_id"],
        min_priority=70,
        max_cases=1,
    )
    assert batch["created_count"] + batch["duplicate_count"] == 1
