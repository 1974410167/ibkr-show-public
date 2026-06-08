from __future__ import annotations

from app.agents.eval_cases.trade_decision_cases import CASES
from app.agents.eval_domain_checks import check_trade_decision_quality
from app.agents.eval_failure_mining import classify_failure, finalize_failure_item
from app.agents.eval_harness import EvalCase
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
)
from app.services.trade_decision_composer import TradeDecisionComposer


def _snapshot(is_holding: bool = False, position_pct: float = 0.0) -> AccountFactSnapshot:
    return AccountFactSnapshot(
        decision_type="holding_decision" if is_holding else "entry_decision",
        symbol="AMD",
        normalized_symbol="AMD",
        user_question=None,
        net_liquidation=100000.0,
        cash=60000.0,
        deployable_liquidity=60000.0,
        deployable_liquidity_ratio=0.6,
        total_position_value=position_pct * 100000.0,
        top_positions=[],
        position_concentration=None,
        risk_concentration=None,
        margin_info=None,
        is_holding=is_holding,
        quantity=10.0 if is_holding else None,
        avg_cost=90.0 if is_holding else None,
        current_price=100.0,
        market_value=position_pct * 100000.0,
        position_pct=position_pct,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        realized_pnl=None,
        recent_trades=[],
        first_buy_date=None,
        last_trade_date=None,
        holding_days=None,
        latest_review=None,
        global_mistake_tags=[],
        data_quality={},
    )


def _pack(*, action_guidance: str = "add_on_pullback", weak_catalyst: bool = False, is_holding: bool = False) -> TradeDecisionCardPack:
    snapshot = _snapshot(is_holding=is_holding, position_pct=0.08 if is_holding else 0.0)
    return TradeDecisionCardPack(
        decision_type=snapshot.decision_type,
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=AccountFitCard(
            card_type="account_fit", symbol="AMD", decision_type=snapshot.decision_type,
            summary="fit", score=18, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", max_suggested_position_pct=0.20,
            suggested_cash_amount=10000.0, position_size_label="medium",
            evidence_quality="high", source_tools=[],
        ),
        market_trend_card=MarketTrendCard(
            card_type="market_trend", symbol="AMD", decision_type=snapshot.decision_type,
            summary="trend", score=12, max_score=15, stance=CardStance.BULLISH,
            price_trend="bullish", trend_break_level="none",
            resistance_levels=[105.0], evidence_quality="high", source_tools=[],
        ),
        fundamental_valuation_card=FundamentalValuationCard(
            card_type="fundamental_valuation", symbol="AMD", decision_type=snapshot.decision_type,
            summary="fund", score=25, max_score=35, stance=CardStance.BULLISH,
            fundamental_status="green", evidence_quality="high", source_tools=[],
        ),
        event_catalyst_card=EventCatalystCard(
            card_type="event_catalyst", symbol="AMD", decision_type=snapshot.decision_type,
            summary="evt", score=1 if weak_catalyst else 4, max_score=5,
            stance=CardStance.NEUTRAL if weak_catalyst else CardStance.BULLISH,
            catalyst_strength="weak" if weak_catalyst else "strong",
            sentiment="neutral" if weak_catalyst else "positive",
            key_events=[] if weak_catalyst else ["财报超预期"],
            evidence_quality="low" if weak_catalyst else "medium",
            source_tools=[],
        ),
        risk_reward_card=RiskRewardCard(
            card_type="risk_reward", symbol="AMD", decision_type=snapshot.decision_type,
            summary="rr", score=12, max_score=15, stance=CardStance.BULLISH,
            reward_risk_ratio=2.1, upside_potential_pct=21.0, downside_risk_pct=10.0,
            max_position_pct=0.20, action_guidance=action_guidance,
            wait_for_pullback_pct=5.0, pullback_entry_level=95.0,
            downside_scenarios=[{"scenario": "support_distance", "distance_pct": 10.0, "ref_price": 90.0}],
            upside_scenarios=[{"scenario": "resistance", "distance_pct": 15.0, "ref_price": 115.0}],
            stop_add_level=95.0, invalidation_level=90.0,
            evidence_quality="high", source_tools=[],
        ),
    )


def test_final_output_contains_risk_control_block() -> None:
    output = TradeDecisionComposer().compose(_pack())
    rc = output["risk_control"]
    assert rc["max_position_pct"] == 0.28  # AMD thesis override
    assert rc["position_limit_status"] == "below_limit"
    assert rc["invalidation_conditions"]
    assert rc["stop_add_conditions"]
    assert rc["recheck_triggers"]
    assert rc["batch_plan"]
    assert rc["downside_scenarios"]
    assert rc["reward_risk_ratio"] == 2.1


def test_add_on_pullback_outputs_complete_risk_control() -> None:
    output = TradeDecisionComposer().compose(_pack(action_guidance="add_on_pullback"))
    assert output["action"] == "add_on_pullback"
    step = output["execution_plan"]["plan"][0]
    assert step["wait_for_pullback_pct"] == 5.0
    assert step["pullback_entry_level"] == 95.0
    assert step["first_batch_pct"] == 0.4
    assert step["second_batch_condition"]
    assert step["invalidation_condition"]
    assert step["risk_check"]


def test_hold_no_add_outputs_reason_and_recheck_trigger() -> None:
    output = TradeDecisionComposer().compose(_pack(action_guidance="hold_no_add", is_holding=True))
    assert output["action"] == "hold_no_add"
    step = output["execution_plan"]["plan"][0]
    assert step["no_add_reason"]
    assert step["recheck_trigger"]
    assert step["what_would_change_decision"]


def test_weak_catalyst_downgrades_action_confidence_and_language() -> None:
    output = TradeDecisionComposer().compose(_pack(action_guidance="add_batch", weak_catalyst=True))
    assert output["action"] not in {"add_batch", "add_right_side"}
    assert output["confidence"] != "high"
    assert "weak_catalyst_downgrade" in output["risk_gate"]["risk_flags"]
    assert "弱催化" in output["decision_summary"]
    assert "不构成独立加仓理由" in output["decision_summary"]


def test_missing_risk_control_subtypes_are_detected() -> None:
    case = EvalCase(
        case_id="rc",
        agent_name="trade_decision",
        title="rc",
        tags=["risk_control_hardening"],
    )
    output = {
        "action": "add_on_pullback",
        "confidence": "high",
        "decision_summary": "建议回调加仓",
        "major_risks": ["risk"],
        "position_advice": {"current_position_pct": 0.0, "max_position_pct": 0.1, "suggested_target_position_pct": 0.05},
        "execution_plan": {"invalid_conditions": [], "recheck_triggers": [], "plan": []},
        "risk_control": {
            "max_position_pct": 0.1,
            "current_position_pct": 0.0,
            "suggested_target_position_pct": 0.05,
            "position_limit_status": "below_limit",
            "invalidation_conditions": [],
            "stop_add_conditions": [],
            "recheck_triggers": [],
            "batch_plan": [],
            "downside_scenarios": [],
            "reward_risk_ratio": None,
            "risk_flags": [],
            "data_limitations": [],
        },
        "risk_gate": {"risk_flags": []},
    }
    failed = [c.to_dict() for c in check_trade_decision_quality(output, case) if not c.passed]
    assert any(c["details"].get("failure_subtype") == "missing_invalidation_condition" for c in failed)
    assert any(c["details"].get("failure_subtype") == "missing_batch_plan" for c in failed)

    scenario = {"scenario_id": "s1", "agent_name": "trade_decision", "category": "risk_control", "severity": "high"}
    result = {"simulation_run_id": "sim", "simulation_result_id": "res", "status": "failed", "output": output}
    seeds = classify_failure(scenario=scenario, simulation_result=result, checks=failed)
    items = [finalize_failure_item(seed, failure_mining_run_id="fm") for seed in seeds]
    assert any(item["failure_type"] == "missing_risk_control" for item in items)
    assert any(item["metadata"].get("failure_subtype") in {"missing_invalidation_condition", "missing_batch_plan"} for item in items)


def test_weak_signal_overstatement_is_detected() -> None:
    case = EvalCase(case_id="weak", agent_name="trade_decision", title="weak", tags=["weak_catalyst"])
    output = {
        "action": "add_batch",
        "confidence": "high",
        "decision_summary": "强催化，建议买入",
        "major_risks": ["risk"],
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.0},
        "execution_plan": {"invalid_conditions": ["x"]},
        "risk_gate": {"risk_flags": []},
    }
    checks = check_trade_decision_quality(output, case)
    assert any(c.check_name == "weak_catalyst_not_strong_buy" and not c.passed for c in checks)
    assert any(c.check_name == "weak_signal_requires_downgraded_language" and not c.passed for c in checks)


def test_weak_catalyst_eval_check_passes_after_downgrade() -> None:
    case = EvalCase(case_id="weak-pass", agent_name="trade_decision", title="weak", tags=["weak_catalyst"])
    output = {
        "action": "wait",
        "confidence": "medium",
        "decision_summary": "弱催化不构成独立加仓理由，建议观察",
        "major_risks": ["risk"],
        "position_advice": {"max_position_pct": 0.1, "current_position_pct": 0.0},
        "execution_plan": {"invalid_conditions": ["x"]},
        "risk_gate": {"risk_flags": ["weak_catalyst_downgrade"]},
    }
    checks = {c.check_name: c for c in check_trade_decision_quality(output, case)}
    assert checks["weak_catalyst_not_strong_buy"].passed is True
    assert checks["weak_signal_requires_downgraded_language"].passed is True


def test_risk_control_hardening_cases_are_loaded_disabled() -> None:
    cases = [c for c in CASES if "risk_control_hardening" in c.tags]
    assert len(cases) >= 10
    assert all(c.enabled is False for c in cases)
    assert all("correctness" in c.tags for c in cases)
    assert all(c.metadata.get("case_tag") == "correctness/risk_control_hardening" for c in cases)
    assert all(c.metadata.get("expected_check_names") for c in cases)


def test_no_over_conservative_hold_no_add_false_positive() -> None:
    output = TradeDecisionComposer().compose(_pack(action_guidance="add_on_pullback"))
    assert output["action"] == "add_on_pullback"
    assert "over_conservative_hold_no_add" not in output.get("review_warnings", [])
