from __future__ import annotations

from app.agents.eval_failure_to_case import build_eval_case_payload_from_failure, score_failure_case_quality
from app.agents.eval_simulation_scenarios import filter_synthetic_scenarios
from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository
from app.services.eval_failure_to_case_service import FailureToEvalCaseService
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository


class FakeCaseRepository:
    def __init__(self) -> None:
        self.cases: dict[str, dict] = {}

    def save_case(self, case: dict) -> dict:
        self.cases[case["case_id"]] = dict(case)
        return case

    def get_case(self, case_id: str) -> dict | None:
        return self.cases.get(case_id)

    def list_cases(self, **kwargs) -> list[dict]:
        items = list(self.cases.values())
        if kwargs.get("agent_name"):
            items = [item for item in items if item.get("agent_name") == kwargs["agent_name"]]
        if kwargs.get("source"):
            items = [item for item in items if item.get("source") == kwargs["source"]]
        return items[: kwargs.get("limit", 100)]


def _scenario() -> dict:
    return filter_synthetic_scenarios(agent_name="trade_decision", tag="weak_catalyst", limit=1)[0]


def _failure(
    *,
    failure_id: str = "failure-1",
    severity: str = "high",
    priority: int = 90,
    should_convert: bool = True,
    failure_type: str = "weak_signal_overstatement",
) -> dict:
    scenario = _scenario()
    return {
        "failure_id": failure_id,
        "failure_mining_run_id": "fm-run-1",
        "simulation_run_id": "sim-run-1",
        "simulation_result_id": f"result-{failure_id}",
        "scenario_id": scenario["scenario_id"],
        "agent_name": "trade_decision",
        "user_question": scenario["user_question"],
        "severity": severity,
        "failure_type": failure_type,
        "failure_tags": ["synthetic", "p3_5", failure_type],
        "failed_dimensions": ["risk_awareness"],
        "failed_checks": [{"check_name": "investment_safety", "passed": False, "severity": "fatal"}],
        "judge_result": {},
        "output_excerpt": "strong_buy",
        "evidence": {},
        "recommendation": "Downgrade weak catalysts and require evidence.",
        "should_convert_to_eval_case": should_convert,
        "conversion_priority": priority,
        "duplicate_key": f"trade_decision:catalyst:{failure_type}:risk_awareness",
        "metadata": {"duplicate_count": 2},
    }


def _simulation_result(failure: dict, output: dict | None = None) -> dict:
    scenario = _scenario()
    return {
        "simulation_result_id": failure["simulation_result_id"],
        "simulation_run_id": failure["simulation_run_id"],
        "scenario_id": scenario["scenario_id"],
        "agent_name": "trade_decision",
        "status": "passed",
        "user_question": scenario["user_question"],
        "output": output or {"decision_summary": "strong_buy", "action": "strong_buy"},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _make_service(failures: list[dict] | None = None) -> tuple[FailureToEvalCaseService, FakeCaseRepository, InMemorySyntheticFailureMiningRepository]:
    failure_repo = InMemorySyntheticFailureMiningRepository()
    simulation_repo = InMemorySyntheticSimulationRepository()
    case_repo = FakeCaseRepository()
    simulation_repo.save_run({"simulation_run_id": "sim-run-1", "agent_names": ["trade_decision"], "status": "completed"})
    for failure in failures or [_failure()]:
        failure_repo.save_failure_item(failure)
        simulation_repo.save_result(_simulation_result(failure))
    return FailureToEvalCaseService(
        failure_repository=failure_repo,
        simulation_repository=simulation_repo,
        case_repository=case_repo,
    ), case_repo, failure_repo


def test_preview_case_from_failure_returns_payload_without_saving() -> None:
    service, case_repo, _failure_repo = _make_service()

    result = service.preview_case_from_failure("failure-1")

    payload = result["draft"]["case_payload"]
    assert payload["enabled"] is False
    assert payload["source"] == "synthetic_failure"
    assert result["quality"]["eligible"] is True
    assert case_repo.cases == {}


def test_convert_failure_to_case_defaults_disabled_and_contains_required_metadata() -> None:
    service, case_repo, failure_repo = _make_service()

    result = service.convert_failure_to_case("failure-1")

    assert result["status"] == "saved"
    saved = case_repo.get_case(result["case_id"])
    assert saved["enabled"] is False
    assert {"synthetic", "p3_5", "failure_mined", "correctness", "regression"}.issubset(set(saved["tags"]))
    assert saved["metadata"]["failure_id"] == "failure-1"
    assert saved["metadata"]["simulation_run_id"] == "sim-run-1"
    assert saved["metadata"]["simulation_result_id"] == "result-failure-1"
    assert saved["metadata"]["synthetic_scenario_id"] == _scenario()["scenario_id"]
    assert saved["forbidden_behavior"]
    assert "recommendation" in saved["expected_behavior"]
    assert failure_repo.get_failure_item("failure-1")["converted_case_id"] == result["case_id"]


def test_low_quality_failure_is_skipped() -> None:
    low = _failure(severity="low", priority=20, should_convert=False, failure_type="other")
    service, case_repo, _failure_repo = _make_service([low])

    result = service.convert_failure_to_case("failure-1")

    assert result["status"] == "skipped"
    assert case_repo.cases == {}


def test_duplicate_failure_returns_duplicate_without_new_case() -> None:
    service, case_repo, _failure_repo = _make_service()
    first = service.convert_failure_to_case("failure-1")
    second = service.convert_failure_to_case("failure-1")

    assert first["status"] == "saved"
    assert second["status"] == "duplicate"
    assert len(case_repo.cases) == 1


def test_force_can_bypass_quality_gate() -> None:
    low = _failure(severity="low", priority=20, should_convert=False, failure_type="other")
    service, case_repo, _failure_repo = _make_service([low])

    result = service.convert_failure_to_case("failure-1", force=True)

    assert result["status"] == "saved"
    assert len(case_repo.cases) == 1


def test_batch_convert_failures_sorts_by_priority_and_obeys_max_cases() -> None:
    failures = [
        _failure(failure_id="failure-low", priority=80),
        _failure(failure_id="failure-high", priority=110),
    ]
    service, _case_repo, _failure_repo = _make_service(failures)

    result = service.batch_convert_failures(failure_ids=["failure-low", "failure-high"], min_priority=80, max_cases=1)

    assert result["converted_count"] == 1
    assert result["results"][0]["failure_id"] == "failure-high"


def test_build_payload_and_quality_helpers() -> None:
    failure = _failure()
    scenario = _scenario()
    simulation_result = _simulation_result(failure)

    payload = build_eval_case_payload_from_failure(failure, scenario, simulation_result)
    quality = score_failure_case_quality(failure, scenario, simulation_result)

    assert payload["metadata"]["failure_id"] == failure["failure_id"]
    assert payload["input"]["original_agent_output"] == simulation_result["output"]
    assert quality["eligible"] is True
    assert quality["quality_score"] >= 0.6
