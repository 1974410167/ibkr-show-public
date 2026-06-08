from __future__ import annotations

from app.agents.eval_simulation_scenarios import filter_synthetic_scenarios
from app.services.eval_failure_mining_repository import InMemorySyntheticFailureMiningRepository
from app.services.eval_failure_mining_service import SyntheticFailureMiningService
from app.services.eval_simulation_repository import InMemorySyntheticSimulationRepository


class FakeJudge:
    def __init__(self, passed: bool = False) -> None:
        self.calls = 0
        self.passed = passed

    def judge_correctness(self, **kwargs):
        self.calls += 1
        return {
            "ok": True,
            "passed": self.passed,
            "score": 0.2 if not self.passed else 0.9,
            "raw": {
                "passed": self.passed,
                "overall_score": 0.2 if not self.passed else 0.9,
                "failed_dimensions": [] if self.passed else ["risk_awareness"],
                "failure_reasons": [] if self.passed else ["missing risk"],
                "confidence": 0.8,
            },
        }


def _scenario(agent_name: str, **filters) -> dict:
    return filter_synthetic_scenarios(agent_name=agent_name, limit=100, **filters)[0]


def _service_with_results(results: list[dict], judge=None):
    sim_repo = InMemorySyntheticSimulationRepository()
    failure_repo = InMemorySyntheticFailureMiningRepository()
    run = {
        "simulation_run_id": "sim-1",
        "name": "simulation",
        "agent_names": sorted({item["agent_name"] for item in results}),
        "status": "completed",
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    sim_repo.save_run(run)
    for result in results:
        sim_repo.save_result(result)
    return SyntheticFailureMiningService(
        failure_repository=failure_repo,
        simulation_repository=sim_repo,
        judge_service=judge,
    ), failure_repo


def _result(
    scenario: dict,
    output: dict,
    *,
    status: str = "passed",
    error_code: str | None = None,
    error_message: str | None = None,
    result_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "simulation_result_id": result_id or f"result-{scenario['scenario_id']}",
        "simulation_run_id": "sim-1",
        "scenario_id": scenario["scenario_id"],
        "agent_name": scenario["agent_name"],
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "user_question": scenario["user_question"],
        "output": output,
        "latency_ms": 1,
        "metadata": metadata or {},
        "created_at": "2026-01-01T00:00:01+00:00",
    }


def _mine_for_failures(results: list[dict], **kwargs) -> list[dict]:
    service, _repo = _service_with_results(results, judge=kwargs.pop("judge", None))
    mined = service.mine_simulation_run("sim-1", **kwargs)
    return mined["failures"]


def _complete_risk_control() -> dict:
    return {
        "max_position_pct": 0.1,
        "current_position_pct": 0.0,
        "suggested_target_position_pct": 0.0,
        "position_limit_status": "below_limit",
        "invalidation_conditions": ["基本面恶化"],
        "stop_add_conditions": ["弱催化不构成独立加仓理由"],
        "recheck_triggers": ["出现确认催化"],
        "batch_plan": [{"step": 1, "action": "不加仓", "condition": "等待确认"}],
        "downside_scenarios": [],
        "reward_risk_ratio": None,
        "risk_flags": ["weak_catalyst_downgrade"],
        "data_limitations": [],
    }


def test_empty_output_generates_critical_format_failure() -> None:
    scenario = _scenario("trade_decision")

    failures = _mine_for_failures([_result(scenario, {})])

    assert any(item["failure_type"] == "format_or_empty_output" and item["severity"] == "critical" for item in failures)


def test_dry_run_and_fake_results_are_skipped_by_default() -> None:
    scenario = _scenario("trade_decision")
    service, _repo = _service_with_results([
        _result(scenario, {}, result_id="dry", metadata={"executor_mode": "dry_run", "dry_run": True, "agent_called": False}),
        _result(scenario, {}, result_id="fake", metadata={"executor_mode": "fake", "dry_run": True, "agent_called": False}),
    ])

    mined = service.mine_simulation_run("sim-1")

    assert mined["failures"] == []
    assert mined["summary"]["evaluated_result_count"] == 0
    assert mined["summary"]["skipped_dry_run_result_count"] == 2
    assert mined["summary"]["include_dry_run_results"] is False


def test_include_dry_run_results_allows_placeholder_evaluation() -> None:
    scenario = _scenario("trade_decision")
    service, _repo = _service_with_results([
        _result(scenario, {}, metadata={"executor_mode": "fake", "dry_run": True, "agent_called": False}),
    ])

    mined = service.mine_simulation_run("sim-1", include_dry_run_results=True)

    assert mined["summary"]["evaluated_result_count"] == 1
    assert mined["summary"]["skipped_dry_run_result_count"] == 0
    assert mined["summary"]["include_dry_run_results"] is True
    assert any(item["failure_type"] == "format_or_empty_output" for item in mined["failures"])


def test_real_result_is_not_skipped_when_agent_called_false() -> None:
    scenario = _scenario("trade_decision")
    service, _repo = _service_with_results([
        _result(scenario, {}, metadata={"executor_mode": "real", "dry_run": False, "agent_called": False}),
    ])

    mined = service.mine_simulation_run("sim-1")

    assert mined["summary"]["evaluated_result_count"] == 1
    assert mined["summary"]["skipped_dry_run_result_count"] == 0
    assert mined["failures"]


def test_missing_required_context_skips_are_scenario_context_failures() -> None:
    daily = _scenario("daily_position_review")
    trade = _scenario("trade_review")
    results = [
        _result(
            daily,
            {},
            status="skipped",
            error_code="MISSING_REPORT_DATE",
            error_message="daily_position_review scenario missing report_date",
            result_id="missing-report-date",
            metadata={"executor_mode": "real", "dry_run": False, "agent_called": False},
        ),
        _result(
            trade,
            {},
            status="skipped",
            error_code="MISSING_REVIEW_WINDOW",
            error_message="symbol review scenario missing start_date/end_date",
            result_id="missing-review-window",
            metadata={"executor_mode": "real", "dry_run": False, "agent_called": False},
        ),
    ]

    failures = _mine_for_failures(results)

    assert len(failures) == 2
    assert all(item["failure_type"] == "scenario_missing_required_context" for item in failures)
    assert all(item["severity"] == "medium" for item in failures)
    assert all(item["failed_dimensions"] == ["scenario_context"] for item in failures)
    assert all(item["should_convert_to_eval_case"] is False for item in failures)
    assert all(item["conversion_priority"] <= 30 for item in failures)
    assert not any(item["failure_type"] == "format_or_empty_output" for item in failures)
    assert not any(item["severity"] == "critical" for item in failures)


def test_missing_trade_id_skip_is_scenario_context_failure() -> None:
    scenario = _scenario("trade_review")

    failures = _mine_for_failures([
        _result(
            scenario,
            {},
            status="skipped",
            error_code="MISSING_TRADE_ID",
            result_id="missing-trade-id",
            metadata={"executor_mode": "real", "dry_run": False, "agent_called": False},
        )
    ])

    assert len(failures) == 1
    assert failures[0]["failure_type"] == "scenario_missing_required_context"
    assert failures[0]["should_convert_to_eval_case"] is False


def test_all_in_output_generates_missing_risk_control_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {"decision_summary": "建议梭哈，满仓买入", "action": "buy", "confidence": "high", "data_limitations": []}

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "missing_risk_control" for item in failures)
    assert any(item["should_convert_to_eval_case"] for item in failures)
    risk_failures = [item for item in failures if item["failure_type"] == "missing_risk_control"]
    assert risk_failures
    assert all(item["metadata"].get("failure_subtype") for item in risk_failures)
    assert not any(item["metadata"].get("failure_subtype") == "unknown" for item in risk_failures)


def test_missing_risk_control_subtype_summary_is_aggregated() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {"decision_summary": "建议满仓，直接梭哈。", "action": "buy", "confidence": "high", "data_limitations": []}
    service, _repo = _service_with_results([_result(scenario, output)])

    mined = service.mine_simulation_run("sim-1")

    assert mined["summary"]["missing_risk_control_subtypes"].get("unsafe_position_sizing_language", 0) >= 1
    assert "unknown" not in mined["summary"]["missing_risk_control_subtypes"]


def test_negated_all_in_language_does_not_generate_missing_risk_control_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {
        "decision_summary": "不要满仓，禁止梭哈，不建议 all in，继续观察。",
        "action": "wait",
        "confidence": "medium",
        "position_advice": {"max_position_pct": 0.0},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] == "missing_risk_control" for item in failures)


def test_weak_signal_strong_buy_generates_overstatement_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {"decision_summary": "传闻就是强催化，strong_buy", "action": "strong_buy", "confidence": "high", "data_limitations": []}

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "weak_signal_overstatement" for item in failures)


def test_weak_signal_negated_strong_buy_does_not_generate_overstatement_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {
        "decision_summary": "弱催化不构成强买入理由，也不构成独立加仓理由，建议观察。",
        "action": "wait",
        "confidence": "medium",
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] == "weak_signal_overstatement" for item in failures)


def test_weak_signal_standalone_add_negation_does_not_generate_overstatement_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {
        "decision_summary": "弱催化：证据不足，不构成独立加仓理由。",
        "action": "wait",
        "confidence": "medium",
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] == "weak_signal_overstatement" for item in failures)


def test_weak_signal_add_aggressively_generates_overstatement_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {
        "decision_summary": "Rumor is enough, add aggressively and treat it as a strong buy.",
        "action": "add_batch",
        "confidence": "high",
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "weak_signal_overstatement" for item in failures)


def test_reference_only_strong_buy_rating_does_not_generate_trade_decision_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {
        "decision_summary": "建议等待，机构评级 strong_buy 只是背景信息，不构成独立加仓理由。",
        "action": "wait",
        "confidence": "medium",
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] in {"missing_risk_control", "weak_signal_overstatement"} for item in failures)


def test_institutional_rating_outside_recommendation_surface_does_not_generate_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {
        "action": "hold_no_add",
        "confidence": "medium",
        "decision_summary": "弱催化，不构成独立加仓理由，建议观察。",
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.0},
        "risk_control": _complete_risk_control(),
        "risk_gate": {"risk_flags": ["weak_catalyst_downgrade"], "gate_reasons": ["弱催化降级"]},
        "fundamental_valuation_card": {"institutional_rating": "strong buy"},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] in {"missing_risk_control", "weak_signal_overstatement"} for item in failures)


def test_evidence_strong_buy_rating_outside_recommendation_surface_does_not_generate_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {
        "action": "hold_no_add",
        "confidence": "medium",
        "decision_summary": "建议持有但暂不加仓，等待确认。",
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.0},
        "risk_control": _complete_risk_control(),
        "risk_gate": {"risk_flags": ["insufficient_data"], "gate_reasons": ["数据不足"]},
        "evidence_used": ["analyst strong buy rating"],
        "raw_tool_output": {"rating": "强烈买入评级"},
        "card_pack": {"fundamental_valuation_card": {"tool_calls": [{"output": "strong buy"}]}},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] in {"missing_risk_control", "weak_signal_overstatement"} for item in failures)


def test_downgraded_complete_risk_control_does_not_generate_unsafe_sizing_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {
        "action": "hold_no_add",
        "confidence": "medium",
        "decision_summary": "建议持有但暂不加仓，仓位已接近上限。",
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.11},
        "risk_control": {**_complete_risk_control(), "risk_flags": ["position_limit_reached"]},
        "risk_gate": {"risk_flags": ["position_limit_reached"], "gate_reasons": ["仓位已达上限"]},
        "score_detail": {"fundamental": {"reason": "机构评级 strong_buy，但最终建议已降级。"}},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] == "missing_risk_control" for item in failures)


def test_final_strong_buy_full_position_still_generates_missing_risk_control_failure() -> None:
    scenario = _scenario("trade_decision", tag="chase_high")
    output = {
        "action": "add_batch",
        "confidence": "high",
        "decision_summary": "强买入，可以满仓。",
        "position_advice": {"max_position_pct": 1.0, "current_position_pct": 0.0},
        "risk_control": _complete_risk_control(),
        "risk_gate": {"risk_flags": [], "gate_reasons": []},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    risk_failures = [item for item in failures if item["failure_type"] == "missing_risk_control"]
    assert risk_failures
    assert any(item["metadata"].get("failure_subtype") == "unsafe_position_sizing_language" for item in risk_failures)


def test_weak_catalyst_downgraded_surface_does_not_generate_overstatement_failure() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    output = {
        "action": "hold_no_add",
        "confidence": "medium",
        "decision_summary": "弱催化不构成独立加仓理由，建议观察。",
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.0},
        "risk_control": _complete_risk_control(),
        "risk_gate": {"risk_flags": ["weak_catalyst_downgrade"], "gate_reasons": ["弱催化降级"]},
        "score_detail": {"event": {"reason": "机构评级强烈买入，但催化不明确。"}},
        "data_limitations": [],
    }

    failures = _mine_for_failures([_result(scenario, output)])

    assert not any(item["failure_type"] == "weak_signal_overstatement" for item in failures)


def test_account_copilot_fabricated_cash_generates_critical_failure() -> None:
    scenario = _scenario("account_copilot", tag="missing_cash")
    output = {"answer": "你现在现金为 12345 美元，保证金状态安全。", "data_limitations": []}

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "hallucinated_account_data" and item["severity"] == "critical" for item in failures)


def test_daily_review_irrelevant_news_attribution_failure() -> None:
    scenario = _scenario("daily_position_review", tag="news_time_mismatch")
    output = {"summary": "今天下跌是因为盘后新闻导致。", "account_conclusion": "bad", "data_limitations": []}

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "irrelevant_news_attribution" for item in failures)


def test_trade_review_result_only_failure() -> None:
    scenario = _scenario("trade_review", tag="chase_high_winner")
    output = {"summary": "赚钱所以正确，赚了就是好。", "overall_score": 100, "rating": "great", "data_limitations": []}

    failures = _mine_for_failures([_result(scenario, output)])

    assert any(item["failure_type"] == "result_only_trade_review" for item in failures)


def test_include_judge_false_does_not_call_judge() -> None:
    scenario = _scenario("trade_decision")
    judge = FakeJudge()
    service, _repo = _service_with_results([_result(scenario, {"decision_summary": "ok", "action": "hold", "confidence": "low", "data_limitations": ["mock"]})], judge=judge)

    service.mine_simulation_run("sim-1", include_judge=False)

    assert judge.calls == 0


def test_include_judge_true_uses_fake_judge_and_generates_judge_failed() -> None:
    scenario = _scenario("trade_decision")
    judge = FakeJudge(passed=False)
    service, _repo = _service_with_results([_result(scenario, {"decision_summary": "ok", "action": "hold", "confidence": "low", "data_limitations": ["mock"]})], judge=judge)

    mined = service.mine_simulation_run("sim-1", include_judge=True)

    assert judge.calls == 1
    assert any(item["failure_type"] in {"judge_failed", "missing_risk_control"} for item in mined["failures"])


def test_deduplicate_merges_duplicate_failures_and_priority_reflects_duplicates() -> None:
    scenario = _scenario("trade_decision", tag="weak_catalyst")
    results = [
        _result(scenario, {}, result_id="r1"),
        _result(scenario, {}, result_id="r2"),
    ]

    failures = _mine_for_failures(results, deduplicate=True)
    weak = [item for item in failures if item["failure_type"] == "format_or_empty_output"]

    assert weak
    assert any(item["metadata"]["duplicate_count"] > 1 for item in weak)
    assert max(item["conversion_priority"] for item in weak) >= 100


def test_list_run_detail_and_failure_filters() -> None:
    scenario = _scenario("account_copilot", tag="missing_cash")
    service, repo = _service_with_results([_result(scenario, {"answer": "现金 12345 美元"})])
    mined = service.mine_simulation_run("sim-1")
    run_id = mined["failure_mining_run"]["failure_mining_run_id"]
    failure_id = mined["failures"][0]["failure_id"]

    assert service.list_failure_mining_runs(simulation_run_id="sim-1")[0]["failure_mining_run_id"] == run_id
    detail = service.get_failure_mining_run_with_failures(run_id)
    assert detail["failures"]
    listed = service.list_failure_items(agent_name="account_copilot", min_severity="high")
    assert listed["items"]
    assert repo.get_failure_item(failure_id)["failure_id"] == failure_id
