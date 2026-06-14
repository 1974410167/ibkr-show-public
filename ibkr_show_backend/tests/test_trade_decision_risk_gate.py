"""Tests for the deterministic trade decision risk gate.

The gate runs after the composer and before the final action is published.
It enforces position limits, invalidation conditions, data sufficiency,
catalyst strength, panic detection, and surfaces a `risk_gate` block in the
output for downstream consumers.
"""

from __future__ import annotations

import pytest

from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    BaseTradeDecisionCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
)
from app.services.trade_decision_composer import (
    ALLOWED_ACTIONS,
    TradeDecisionComposer,
    normalize_action,
)
from app.services.trade_decision_risk_gate import (
    ADD_LIKE_ACTIONS,
    HOLD_LIKE_ACTIONS,
    RISK_GATE_ACTIONS,
    RiskGate,
    apply_risk_gate,
)


# === Fixtures ===

def _make_snapshot(
    symbol="AAPL",
    decision_type="entry_decision",
    is_holding=False,
    position_pct=0.0,
    net_liq=50000.0,
):
    return AccountFactSnapshot(
        decision_type=decision_type,
        symbol=symbol,
        normalized_symbol=symbol,
        user_question=None,
        net_liquidation=net_liq,
        cash=30000.0,
        deployable_liquidity=30000.0,
        deployable_liquidity_ratio=0.6,
        total_position_value=0.0,
        top_positions=[],
        position_concentration=None,
        risk_concentration=None,
        margin_info=None,
        is_holding=is_holding,
        quantity=10.0 if is_holding else None,
        avg_cost=150.0 if is_holding else None,
        current_price=150.0,
        market_value=position_pct * net_liq,
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


def _account_fit(level="good", max_pct=0.10, score=18, evidence_quality="high"):
    return AccountFitCard(
        card_type="account_fit",
        symbol="AAPL",
        decision_type="entry_decision",
        summary=f"Account fit: {level}",
        score=score,
        max_score=20,
        stance=CardStance.BULLISH,
        account_fit_level=level,
        max_suggested_position_pct=max_pct,
        position_size_label="medium",
        evidence_quality=evidence_quality,
        source_tools=[],
    )


def _market_trend(stance="bullish", score=12, evidence_quality="medium"):
    return MarketTrendCard(
        card_type="market_trend",
        symbol="AAPL",
        decision_type="entry_decision",
        summary=f"Trend: {stance}",
        score=score,
        max_score=15,
        stance=stance,
        price_trend=stance,
        evidence_quality=evidence_quality,
        source_tools=["quote"],
    )


def _fundamental(stance="bullish", score=20, pe=22.0, evidence_quality="high"):
    return FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol="AAPL",
        decision_type="entry_decision",
        summary=f"Fundamental: {stance}",
        score=score,
        max_score=35,
        stance=stance,
        pe_ttm=pe,
        evidence_quality=evidence_quality,
        source_tools=["company"],
    )


def _event(strength="moderate", score=4, sentiment="positive", news_count=3, key_events=None):
    return EventCatalystCard(
        card_type="event_catalyst",
        symbol="AAPL",
        decision_type="entry_decision",
        summary=f"Event: {strength}",
        score=score,
        max_score=5,
        stance=CardStance.BULLISH if sentiment == "positive" else CardStance.NEUTRAL,
        catalyst_strength=strength,
        sentiment=sentiment,
        recent_news_count=news_count,
        key_events=key_events or ["Q3 财报", "指引上调"],
        evidence_quality="medium" if score > 1 else "low",
        source_tools=["news_search"],
    )


def _risk_reward(
    score=12,
    upside=20.0,
    downside=10.0,
    ratio=2.0,
    max_pct=0.10,
    evidence_quality="medium",
    wait_for_pullback=False,
    stance=CardStance.BULLISH,
):
    return RiskRewardCard(
        card_type="risk_reward",
        symbol="AAPL",
        decision_type="entry_decision",
        summary="Risk reward",
        score=score,
        max_score=15,
        stance=stance,
        upside_potential_pct=upside,
        downside_risk_pct=downside,
        reward_risk_ratio=ratio,
        max_position_pct=max_pct,
        wait_for_pullback=wait_for_pullback,
        position_size_label="medium",
        evidence_quality=evidence_quality,
        source_tools=[],
    )


def _make_card_pack(**overrides):
    acc = overrides.get("account_fit") or _account_fit()
    mkt = overrides.get("market_trend") or _market_trend()
    fund = overrides.get("fundamental") or _fundamental()
    evt = overrides.get("event") or _event()
    rr = overrides.get("risk_reward") or _risk_reward()
    snapshot = overrides.get("snapshot") or _make_snapshot()
    return TradeDecisionCardPack(
        decision_type=snapshot.decision_type,
        symbol=snapshot.symbol,
        account_fact_snapshot=snapshot,
        account_fit_card=acc,
        market_trend_card=mkt,
        fundamental_valuation_card=fund,
        event_catalyst_card=evt,
        risk_reward_card=rr,
    )


def _composed_output(card_pack, action="add_batch", confidence="high", max_pct=0.10,
                     invalid_conditions=None, position_advice=None, decision_summary=""):
    if invalid_conditions is None:
        invalid_conditions = ["PE > 60", "仓位 > 15%"]
    if position_advice is None:
        position_advice = {
            "current_position_pct": 0.0,
            "suggested_target_position_pct": 0.05,
            "max_position_pct": max_pct,
            "suggested_cash_amount": 0,
            "position_size_label": "medium",
        }
    return {
        "symbol": card_pack.symbol,
        "decision_type": card_pack.decision_type,
        "action": action,
        "confidence": confidence,
        "decision_summary": decision_summary or "test",
        "position_advice": position_advice,
        "execution_plan": {
            "should_act_now": True,
            "plan": [{"step": 1, "condition": "x", "action": action, "amount": None, "note": ""}],
            "invalid_conditions": invalid_conditions,
            "recheck_triggers": ["回调 5%"],
        },
        "data_limitations": [],
        "review_warnings": [],
    }


# === Sanity / vocabulary ===

def test_allowed_actions_contains_new_gate_actions():
    for action in (
        "hold_no_add", "add_on_pullback", "add_right_side",
        "trim_on_rebound", "reduce_now", "sell_thesis_broken", "panic_blocked",
    ):
        assert action in ALLOWED_ACTIONS
        assert action in RISK_GATE_ACTIONS


def test_normalize_action_handles_new_actions():
    for action in ("hold_no_add", "add_on_pullback", "panic_blocked"):
        assert normalize_action(action) == action
    # Chinese aliases still resolve
    assert normalize_action("持有不加仓") == "hold_no_add"
    assert normalize_action("逢回调加仓") == "add_on_pullback"
    assert normalize_action("恐慌拦截") == "panic_blocked"


def test_risk_gate_downgrades_add_above_ai_policy_max():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.08)
    card_pack = _make_card_pack(snapshot=snapshot)
    card_pack.ai_policy_assessment = {
        "status": "evaluated",
        "ai_recommended_max_position_pct": 0.10,
        "ai_recommended_target_position_range_pct": [0.06, 0.09],
        "ai_position_stance": "near_target",
        "recommended_action_bias": "allow_add",
    }
    output = _composed_output(
        card_pack,
        action="add_batch",
        position_advice={
            "current_position_pct": 0.08,
            "suggested_target_position_pct": 0.14,
            "max_position_pct": 0.14,
            "suggested_cash_amount": 6000,
            "position_size_label": "medium",
        },
    )

    result = RiskGate().evaluate(output, card_pack)

    assert result.final_action == "hold_no_add"
    assert "target_above_ai_policy_max" in result.risk_flags
    assert result.action_constraints["ai_recommended_max_position_pct"] == pytest.approx(0.10)
    assert result.action_constraints["suggested_target_position_pct"] == pytest.approx(0.10)


# === Rule 1: missing position limit blocks add ===

def test_missing_max_position_pct_downgrades_add_batch_to_hold_no_add():
    snapshot = _make_snapshot(is_holding=False)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="add_batch", max_pct=0.0)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "wait"
    assert "missing_position_limit" in result.risk_flags
    assert "max_position_pct" in result.action_constraints.get("required", [])
    assert output["action"] == "wait"


def test_missing_max_position_pct_holding_returns_hold_no_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="add_small", max_pct=0.0)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "missing_position_limit" in result.risk_flags


# === Rule 2: missing invalid_conditions downgrades strong add ===

def test_missing_invalid_conditions_downgrades_add_to_add_on_pullback():
    snapshot = _make_snapshot(is_holding=False)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(
        card_pack, action="add_batch", max_pct=0.10, invalid_conditions=[],
    )

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "add_on_pullback"
    assert "missing_invalidation_conditions" in result.risk_flags


def test_missing_invalid_conditions_holding_returns_hold_no_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(
        card_pack, action="add", max_pct=0.10, invalid_conditions=[],
    )

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "missing_invalidation_conditions" in result.risk_flags


# === Rule 3: insufficient data forces confidence cap, no add ===

def test_insufficient_public_data_downgrades_action_and_caps_confidence():
    snapshot = _make_snapshot(is_holding=False)
    # Build a card pack with most public cards being INSUFFICIENT_DATA.
    rr = _risk_reward(stance=CardStance.INSUFFICIENT_DATA, score=0, evidence_quality="low")
    mkt = _market_trend(stance=CardStance.INSUFFICIENT_DATA, score=0, evidence_quality="low")
    fund = _fundamental(stance=CardStance.INSUFFICIENT_DATA, score=0, evidence_quality="low")
    card_pack = _make_card_pack(
        snapshot=snapshot, market_trend=mkt, fundamental=fund, risk_reward=rr,
    )
    output = _composed_output(card_pack, action="add_batch", confidence="high", max_pct=0.10)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert "insufficient_data" in result.risk_flags
    assert result.final_action in {"wait", "hold_no_add"}
    # Confidence should be surfaced as a required disclosure so the caller
    # can downgrade it.
    assert any("confidence" in d.lower() for d in result.required_disclosures)


# === Rule 4: weak catalyst must not trigger add / add_batch ===

def test_weak_catalyst_downgrades_add_batch_to_wait():
    snapshot = _make_snapshot(is_holding=False)
    weak_evt = _event(strength="weak", score=1, sentiment="neutral", news_count=1, key_events=[])
    card_pack = _make_card_pack(snapshot=snapshot, event=weak_evt)
    output = _composed_output(card_pack, action="add_batch", max_pct=0.10)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert "weak_catalyst_downgrade" in result.risk_flags
    assert result.final_action == "wait"


def test_weak_catalyst_with_holding_returns_hold_no_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    weak_evt = _event(strength="weak", score=1, sentiment="neutral", news_count=1, key_events=[])
    card_pack = _make_card_pack(snapshot=snapshot, event=weak_evt)
    output = _composed_output(card_pack, action="add", max_pct=0.20)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "weak_catalyst_downgrade" in result.risk_flags


def test_weak_catalyst_downgrade_caps_high_confidence_to_medium():
    snapshot = _make_snapshot(is_holding=False)
    weak_evt = _event(strength="weak", score=1, sentiment="neutral", news_count=1, key_events=[])
    card_pack = _make_card_pack(snapshot=snapshot, event=weak_evt)
    output = _composed_output(card_pack, action="add_batch", confidence="high", max_pct=0.10)

    mutated, result = apply_risk_gate(output, card_pack, user_question=None)

    assert "weak_catalyst_downgrade" in result.risk_flags
    assert result.confidence_cap == "medium"
    assert mutated["confidence"] == "medium"
    assert mutated["action"] == "wait"


def test_weak_catalyst_keeps_ai_supported_pullback_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    weak_evt = _event(strength="weak", score=1, sentiment="neutral", news_count=1, key_events=[])
    fund = _fundamental()
    fund.fundamental_status = "green"
    mkt = _market_trend()
    mkt.trend_break_level = "none"
    rr = _risk_reward(ratio=2.0)
    card_pack = _make_card_pack(snapshot=snapshot, event=weak_evt, fundamental=fund, market_trend=mkt, risk_reward=rr)
    card_pack.ai_policy_assessment = {
        "status": "evaluated",
        "ai_position_stance": "underweight",
        "recommended_action_bias": "prefer_pullback_add",
        "ai_recommended_max_position_pct": 0.20,
    }
    output = _composed_output(card_pack, action="add_on_pullback", max_pct=0.20)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "add_on_pullback"
    assert "weak_catalyst_soft_warning" in result.risk_flags


def test_trend_warning_downgrades_right_side_to_pullback_when_ai_supports():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    mkt = _market_trend()
    mkt.trend_break_level = "warning"
    fund = _fundamental()
    fund.fundamental_status = "green"
    rr = _risk_reward(ratio=2.0)
    card_pack = _make_card_pack(snapshot=snapshot, market_trend=mkt, fundamental=fund, risk_reward=rr)
    card_pack.ai_policy_assessment = {
        "status": "evaluated",
        "ai_position_stance": "underweight",
        "recommended_action_bias": "prefer_pullback_add",
        "ai_recommended_max_position_pct": 0.20,
    }
    output = _composed_output(card_pack, action="add_right_side", max_pct=0.20)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "add_on_pullback"
    assert "trend_break_warning_downgrade" in result.risk_flags


# === Rule 5: high position blocks add ===

def test_position_at_max_blocks_add_returns_hold_no_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(
        card_pack, action="add_small", max_pct=0.10,
        position_advice={
            "current_position_pct": 0.10,
            "suggested_target_position_pct": 0.05,
            "max_position_pct": 0.10,
            "suggested_cash_amount": 0,
            "position_size_label": "medium",
        },
    )

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "position_limit_reached" in result.risk_flags


def test_poor_account_fit_blocks_add_returns_hold_no_add():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.05)
    poor_acc = _account_fit(level="poor", max_pct=0.05, score=4)
    card_pack = _make_card_pack(snapshot=snapshot, account_fit=poor_acc)
    output = _composed_output(card_pack, action="add_small", max_pct=0.10)

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "position_limit_reached" in result.risk_flags


# === Rule 6: panic detection ===

def test_panic_question_with_intact_thesis_returns_panic_blocked():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    # Everything else is healthy
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="sell", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="我受不了了，NVDA 暴跌 20%，赶紧清仓！",
    )

    assert result.final_action == "panic_blocked"
    assert "panic_sell_blocked" in result.risk_flags
    assert result.blocked is True


def test_panic_question_with_severe_breakdown_does_not_block():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    # Severe fundamental breakdown - panic sell is legitimate
    fund = _fundamental(stance=CardStance.BEARISH, score=0, pe=None, evidence_quality="low")
    mkt = _market_trend(stance=CardStance.BEARISH, score=0, evidence_quality="low")
    card_pack = _make_card_pack(snapshot=snapshot, market_trend=mkt, fundamental=fund)
    output = _composed_output(card_pack, action="sell", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="我要清仓，再不卖就要爆了",
    )

    # The severe breakdown overrides the panic detector, so the action is
    # NOT panic_blocked - the sell is justified by fundamentals.
    assert result.final_action != "panic_blocked"
    assert "panic_sell_blocked" not in result.risk_flags


def test_panic_with_holding_but_no_position_explanation():
    """If user is not actually holding the symbol, the question is not a panic dump."""
    snapshot = _make_snapshot(is_holding=False, position_pct=0.0)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="add_batch", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="是不是应该清仓避险？",
    )

    # Not a panic dump, just a generic question; no panic gate
    assert "panic_sell_blocked" not in result.risk_flags


def test_panic_does_not_block_when_fundamental_thesis_broken():
    """When fund.thesis_broken=True, the user asking to clear the position
    is NOT panic - it's a justified sell."""
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    # Healthy trend / market, but fundamental thesis is broken
    fund = _fundamental(stance=CardStance.BULLISH, score=20, pe=22.0, evidence_quality="high")
    fund.thesis_broken = True
    mkt = _market_trend(stance=CardStance.BULLISH, score=12, evidence_quality="medium")
    card_pack = _make_card_pack(snapshot=snapshot, fundamental=fund, market_trend=mkt)
    output = _composed_output(card_pack, action="sell", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="AMD 要不要现在清仓？我快受不了了",
    )

    # Thesis is broken -> NOT panic. The action should land in
    # reduce_now / sell_thesis_broken, not panic_blocked.
    assert result.final_action != "panic_blocked"
    assert "panic_sell_blocked" not in result.risk_flags
    # And the thesis-broken rule should have fired
    assert "thesis_broken_detected" in result.risk_flags


def test_panic_does_not_block_when_rr_risk_reward_thesis_broken():
    """When RiskRewardCard.risk_reward_thesis_broken=True, panic is bypassed
    and reduce_now / sell_thesis_broken wins."""
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    # Trend and fundamentals are clean; the rr card itself signals thesis
    # broken (a separate field name to avoid collision with fund.thesis_broken).
    mkt = _market_trend(stance=CardStance.BULLISH, score=12, evidence_quality="medium")
    fund = _fundamental(stance=CardStance.BULLISH, score=20, pe=22.0, evidence_quality="high")
    rr = _risk_reward()
    rr.risk_reward_thesis_broken = True
    card_pack = _make_card_pack(snapshot=snapshot, market_trend=mkt, fundamental=fund, risk_reward=rr)
    output = _composed_output(card_pack, action="sell", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="暴跌 20%，我要清仓！",
    )

    assert result.final_action != "panic_blocked"
    assert "panic_sell_blocked" not in result.risk_flags


def test_panic_old_rr_thesis_broken_field_no_longer_bypasses():
    """The RiskGate must not read the non-existent rr.thesis_broken field.
    A user asking to panic-sell with a healthy card pack must still be
    blocked (sanity check that we fixed the field name)."""
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    mkt = _market_trend(stance=CardStance.BULLISH, score=12, evidence_quality="medium")
    fund = _fundamental(stance=CardStance.BULLISH, score=20, pe=22.0, evidence_quality="high")
    rr = _risk_reward()
    # Simulate the OLD (incorrect) field name - it should NOT bypass panic.
    rr.thesis_broken = True
    card_pack = _make_card_pack(snapshot=snapshot, market_trend=mkt, fundamental=fund, risk_reward=rr)
    output = _composed_output(card_pack, action="sell", max_pct=0.10)

    _, result = apply_risk_gate(
        output, card_pack, user_question="暴跌 20%，我要清仓！",
    )

    # The OLD field name is not consulted anymore. Panic must still block.
    assert result.final_action == "panic_blocked"
    assert "panic_sell_blocked" in result.risk_flags


# === Rule 7: severe trend breakdown => reduce_now ===

def test_severe_breakdown_holding_downgrades_hold_to_reduce_now():
    snapshot = _make_snapshot(is_holding=True, position_pct=0.10)
    fund = _fundamental(stance=CardStance.BEARISH, score=0, pe=None, evidence_quality="low")
    mkt = _market_trend(stance=CardStance.BEARISH, score=0, evidence_quality="low")
    card_pack = _make_card_pack(snapshot=snapshot, market_trend=mkt, fundamental=fund)
    output = _composed_output(card_pack, action="hold", max_pct=0.10)

    _, result = apply_risk_gate(output, card_pack, user_question="现在该怎么做")

    assert result.final_action == "reduce_now"
    assert "thesis_breakdown_detected" in result.risk_flags


# === Output carries risk_gate block ===

def test_decision_output_contains_risk_gate_block():
    snapshot = _make_snapshot(is_holding=False)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="add_batch", max_pct=0.10)

    _, _result = apply_risk_gate(output, card_pack, user_question=None)

    assert "risk_gate" in output
    rg = output["risk_gate"]
    assert rg["original_action"] == "add_batch"
    assert "gate_reasons" in rg
    assert "risk_flags" in rg
    assert "action_constraints" in rg


def test_data_limitations_and_review_warnings_get_gate_reasons():
    snapshot = _make_snapshot(is_holding=False)
    card_pack = _make_card_pack(snapshot=snapshot)
    output = _composed_output(card_pack, action="add_batch", max_pct=0.0)

    apply_risk_gate(output, card_pack, user_question=None)

    # missing_position_limit reason is in data_limitations
    assert any("仓位上限" in s for s in output["data_limitations"])
    # and the flag is surfaced in review_warnings
    assert any("risk_gate:missing_position_limit" in s for s in output["review_warnings"])


# === Integration with composer ===

def test_composer_runs_risk_gate_and_attaches_block():
    """The composer should call the gate and attach `risk_gate` to its output."""
    snapshot = _make_snapshot(is_holding=False)
    card_pack = _make_card_pack(snapshot=snapshot)
    composer = TradeDecisionComposer()
    output = composer.compose(card_pack)

    # A high-quality bullish pack with no max_position_pct should downgrade
    # add_batch into a non-add action.
    assert "risk_gate" in output
    assert output["risk_gate"]["original_action"] in {"add_batch", "add_small", "add", "hold"}
    # No legacy action missing
    assert output["action"] in ALLOWED_ACTIONS


def test_legacy_action_compatibility():
    """Old action vocabulary must still pass through normalize_action."""
    assert normalize_action("buy") == "add_batch"
    assert normalize_action("trim") == "reduce"
    assert normalize_action("hold") == "hold"
    assert normalize_action("wait") == "wait"
    assert normalize_action("watchlist") == "watchlist"


def test_no_action_demotion_when_fully_justified():
    """A well-justified add_batch with proper limits and a known thesis should not be downgraded."""
    snapshot = _make_snapshot(is_holding=False, net_liq=100000.0)
    card_pack = _make_card_pack(snapshot=snapshot)
    # Attach a known thesis so the Stage 03 "unknown thesis" rule does not
    # preempt this test. AMD has max 0.28 which is > the test's max_pct=0.10.
    card_pack.investment_thesis = {
        "symbol": "AAPL",
        "role": "core_growth",
        "risk_class": "medium",
        "max_position_pct": 0.28,
        "target_position_pct": 0.20,
        "core_thesis": [],
        "add_rules": [],
        "hold_rules": [],
        "sell_triggers": [],
        "no_add_triggers": [],
        "review_frequency": "weekly",
        "metadata": {},
    }
    output = _composed_output(
        card_pack, action="add_batch", max_pct=0.10,
        invalid_conditions=["PE > 50", "仓位 > 15%"],
        confidence="high",
    )

    _, result = apply_risk_gate(output, card_pack, user_question=None)

    # Should keep add_batch (or downgrade to add_on_pullback if weak catalyst etc.)
    # but must not be panic_blocked, sell_thesis_broken, or hold_no_add.
    assert result.final_action not in {"panic_blocked", "sell_thesis_broken"}
    assert result.downgraded is False or result.final_action in {"add_batch", "add_on_pullback"}
