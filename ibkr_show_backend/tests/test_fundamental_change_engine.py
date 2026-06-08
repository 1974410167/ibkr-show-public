"""Tests for the FundamentalChangeEngine and its integration with the
Risk Gate and Composer.

The engine is a pure deterministic detector that consumes already-fetched
financial / valuation / segment / rating / forecast data and produces a
`FundamentalChangeResult`. It does NOT call LLM or MCP.
"""

from __future__ import annotations

import pytest

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
from app.services.fundamental_change_engine import (
    FUNDAMENTAL_STATUSES,
    FundamentalChangeEngine,
    FundamentalChangeResult,
)
from app.services.investment_thesis import get_thesis
from app.services.trade_decision_risk_gate import apply_risk_gate


# === Engine: revenue growth ===

def test_revenue_growth_slowdown_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"revenue": 100}, {"revenue": 110}, {"revenue": 105}, {"revenue": 100}, {"revenue": 95},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.revenue_growth_trend == "slowing"
    assert "revenue_growth_slowdown" in r.change_signals


def test_revenue_growth_acceleration_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"revenue": 100}, {"revenue": 102}, {"revenue": 105}, {"revenue": 109}, {"revenue": 115},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.revenue_growth_trend == "accelerating"
    assert "revenue_growth_acceleration" in r.positive_signals


def test_revenue_growth_insufficient_data_raises_limitation():
    e = FundamentalChangeEngine()
    reports = [{"revenue": 100}, {"revenue": 110}]  # only 2 quarters
    r = e.evaluate(financial_reports=reports)
    assert r.revenue_growth_trend is None
    assert any("revenue" in s.lower() for s in r.data_limitations)


# === Engine: margin ===

def test_margin_compression_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"gross_margin": 40}, {"gross_margin": 38}, {"gross_margin": 35}, {"gross_margin": 32},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.margin_trend == "compressing"
    assert "margin_compression" in r.change_signals


def test_margin_expansion_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"gross_margin": 30}, {"gross_margin": 32}, {"gross_margin": 35}, {"gross_margin": 38},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.margin_trend == "expanding"
    assert "margin_expansion" in r.positive_signals


# === Engine: cash flow ===

def test_cash_flow_deterioration_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"operating_cash_flow": 100}, {"operating_cash_flow": 90}, {"operating_cash_flow": 80}, {"operating_cash_flow": 70},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.cash_flow_trend == "deteriorating"
    assert "cash_flow_deterioration" in r.change_signals


def test_free_cash_flow_negative_detected():
    e = FundamentalChangeEngine()
    reports = [
        {"free_cash_flow": 100}, {"free_cash_flow": 50}, {"free_cash_flow": 0}, {"free_cash_flow": -20},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.cash_flow_trend in {"deteriorating", "negative"}
    assert "cash_flow_deterioration" in r.change_signals


# === Engine: guidance ===

def test_guidance_cut_detected():
    e = FundamentalChangeEngine()
    reports = [{"guidance": "公司下调全年指引，主要受需求疲软影响"}]
    r = e.evaluate(financial_reports=reports)
    assert r.guidance_change == "cut"
    assert "guidance_cut" in r.change_signals


def test_guidance_raise_detected():
    e = FundamentalChangeEngine()
    reports = [{"guidance": "公司上调全年指引，超出此前预期"}]
    r = e.evaluate(financial_reports=reports)
    assert r.guidance_change == "raised"
    assert "guidance_raise" in r.positive_signals


def test_guidance_maintained_detected_when_neutral():
    e = FundamentalChangeEngine()
    reports = [{"guidance": "公司维持全年指引不变"}]
    r = e.evaluate(financial_reports=reports)
    assert r.guidance_change == "maintained"


# === Engine: segment growth ===

def test_segment_growth_failure_detected():
    e = FundamentalChangeEngine()
    segments = [
        {"name": "Data Center", "yoy_growth": -2.0},
        {"name": "Gaming", "yoy_growth": 8.0},
    ]
    r = e.evaluate(business_segments=segments)
    assert any("Data Center" in n and "转负" in n for n in r.segment_growth_notes)
    assert "segment_growth_failure" in r.change_signals


# === Engine: rating / forecast ===

def test_rating_downgrade_detected():
    e = FundamentalChangeEngine()
    rating = {"recent_change": "downgrade from buy to hold"}
    r = e.evaluate(institution_rating=rating)
    assert "rating_downgrade" in r.change_signals


def test_forecast_eps_cut_detected():
    e = FundamentalChangeEngine()
    f = {"trend": "cut"}
    r = e.evaluate(forecast_eps=f)
    assert "forecast_eps_cut" in r.change_signals


# === Engine: thesis_broken ===

def test_thesis_broken_detected_when_sell_triggers_match_signals():
    e = FundamentalChangeEngine()
    thesis = get_thesis("AMD")
    # Configure the AMD sell_triggers to match revenue slowdown + guidance cut
    reports = [
        {"revenue": 100}, {"revenue": 110}, {"revenue": 105}, {"revenue": 100}, {"revenue": 95},
        {"guidance": "公司下调全年指引"},
    ]
    r = e.evaluate(financial_reports=reports, investment_thesis=thesis)
    assert r.thesis_broken is True
    # Red overrides
    assert r.fundamental_status == "red"


def test_thesis_intact_when_no_signals_match():
    e = FundamentalChangeEngine()
    thesis = get_thesis("AMD")
    # Healthy revenue + positive guidance
    reports = [
        {"revenue": 100}, {"revenue": 102}, {"revenue": 105}, {"revenue": 109},
        {"guidance": "公司上调全年指引"},
    ]
    r = e.evaluate(financial_reports=reports, investment_thesis=thesis)
    # thesis_broken is driven by matching sell_triggers; positive reports
    # should not flip it to True.
    assert r.thesis_broken is False


def test_thesis_broken_handles_dict_investment_thesis():
    e = FundamentalChangeEngine()
    thesis = {
        "sell_triggers": ["收入指引连续两个季度不及预期"],
        "core_thesis": [],
    }
    reports = [{"guidance": "指引连续下调"}]
    r = e.evaluate(financial_reports=reports, investment_thesis=thesis)
    assert r.thesis_broken is True


def test_thesis_broken_false_when_thesis_is_none():
    e = FundamentalChangeEngine()
    reports = [{"guidance": "指引下调"}]
    r = e.evaluate(financial_reports=reports, investment_thesis=None)
    assert r.thesis_broken is False


# === Engine: insufficient data ===

def test_unknown_status_when_no_data():
    e = FundamentalChangeEngine()
    r = e.evaluate()
    assert r.fundamental_status == "unknown"
    assert r.thesis_broken is False
    assert any("数据" in s for s in r.data_limitations)


def test_no_fabrication_when_field_missing():
    e = FundamentalChangeEngine()
    # revenue missing in some reports
    reports = [
        {"revenue": 100}, {}, {"revenue": 105}, {"revenue": 100}, {"revenue": 95},
    ]
    r = e.evaluate(financial_reports=reports)
    # The two valid later points still detect slowing (100, 105, 100, 95 = down)
    # But the engine should not error and should populate limitations.
    assert r.revenue_growth_trend in {"slowing", "stable"}


# === Status aggregation ===

def test_aggregate_status_green_with_positive_signals():
    e = FundamentalChangeEngine()
    reports = [
        {"revenue": 100}, {"revenue": 102}, {"revenue": 105}, {"revenue": 109},
        {"gross_margin": 30}, {"gross_margin": 32}, {"gross_margin": 35}, {"gross_margin": 38},
        {"guidance": "公司上调指引"},
    ]
    r = e.evaluate(financial_reports=reports)
    # Multiple positives should bring status toward green
    assert r.fundamental_status in {"green", "yellow"}


def test_aggregate_status_red_with_multiple_negatives():
    e = FundamentalChangeEngine()
    reports = [
        {"revenue": 100}, {"revenue": 110}, {"revenue": 105}, {"revenue": 100}, {"revenue": 95},
        {"gross_margin": 40}, {"gross_margin": 38}, {"gross_margin": 35}, {"gross_margin": 32},
        {"operating_cash_flow": 100}, {"operating_cash_flow": 90}, {"operating_cash_flow": 80}, {"operating_cash_flow": 70},
        {"guidance": "公司下调指引"},
    ]
    r = e.evaluate(financial_reports=reports)
    assert r.fundamental_status == "red"


# === FundamentalValuationCard carries the new fields ===

def test_fundamental_card_has_new_fields():
    from app.agents.trade_decision_cards import FundamentalValuationCard

    card = FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol="AMD",
        decision_type="entry_decision",
        summary="x",
    )
    assert card.fundamental_status == "unknown"
    assert card.thesis_broken is False
    assert card.change_signals == []
    assert card.positive_signals == []
    assert card.negative_signals == []
    assert card.revenue_growth_trend is None
    assert card.margin_trend is None
    assert card.cash_flow_trend is None
    assert card.guidance_change is None
    assert card.segment_growth_notes == []
    assert card.fundamental_change_evidence == []

    d = card.to_dict()
    assert d["fundamental_status"] == "unknown"
    assert d["thesis_broken"] is False
    assert "change_signals" in d
    assert "positive_signals" in d
    assert "guidance_change" in d
    assert "fundamental_change_evidence" in d


# === Risk Gate integration ===

def _snapshot(is_holding=False, position_pct=0.0, symbol="AMD"):
    return AccountFactSnapshot(
        decision_type="entry_decision" if not is_holding else "holding_decision",
        symbol=symbol,
        normalized_symbol=symbol,
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
        avg_cost=150.0 if is_holding else None,
        current_price=150.0,
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


def _fundamental_card(status, thesis_broken=False, score=20):
    return FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol="AMD",
        decision_type="entry_decision",
        summary="x",
        score=score,
        max_score=35,
        stance=CardStance.BULLISH,
        evidence_quality="high",
        source_tools=[],
        fundamental_status=status,
        thesis_broken=thesis_broken,
    )


def _pack(snapshot, fund, mkt=None, evt=None, rr=None, acc=None, thesis=None):
    return TradeDecisionCardPack(
        decision_type=snapshot.decision_type,
        symbol=snapshot.symbol,
        account_fact_snapshot=snapshot,
        account_fit_card=acc or AccountFitCard(
            card_type="account_fit", symbol="AMD", decision_type="entry_decision",
            summary="fit", score=15, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", max_suggested_position_pct=0.10,
            evidence_quality="high", source_tools=[],
        ),
        market_trend_card=mkt or MarketTrendCard(
            card_type="market_trend", symbol="AMD", decision_type="entry_decision",
            summary="trend", score=10, max_score=15, stance=CardStance.BULLISH,
            evidence_quality="medium", trend_break_level="none", source_tools=[],
        ),
        fundamental_valuation_card=fund,
        event_catalyst_card=evt or EventCatalystCard(
            card_type="event_catalyst", symbol="AMD", decision_type="entry_decision",
            summary="evt", score=4, max_score=5, stance=CardStance.BULLISH,
            catalyst_strength="strong", sentiment="positive",
            recent_news_count=4, key_events=["Q3 财报"],
            evidence_quality="medium", source_tools=[],
        ),
        risk_reward_card=rr or RiskRewardCard(
            card_type="risk_reward", symbol="AMD", decision_type="entry_decision",
            summary="rr", score=12, max_score=15, stance=CardStance.BULLISH,
            evidence_quality="medium", source_tools=[],
        ),
        investment_thesis=thesis,
    )


def _output(action, max_pct=0.10, invalid_conditions=None):
    if invalid_conditions is None:
        invalid_conditions = ["PE>60"]
    return {
        "action": action,
        "confidence": "high",
        "decision_summary": "test",
        "position_advice": {
            "current_position_pct": 0.0,
            "suggested_target_position_pct": 0.05,
            "max_position_pct": max_pct,
            "suggested_cash_amount": 0,
            "position_size_label": "medium",
        },
        "execution_plan": {
            "should_act_now": True,
            "plan": [{"step": 1, "condition": "x", "action": action, "amount": None, "note": ""}],
            "invalid_conditions": invalid_conditions,
            "recheck_triggers": [],
        },
        "data_limitations": [],
        "review_warnings": [],
    }


def test_risk_gate_red_fundamental_emits_reduce_now_for_holding():
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    fund = _fundamental_card("red")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("hold", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action in {"reduce_now", "sell_thesis_broken"}
    assert "fundamental_red_action" in result.risk_flags


def test_risk_gate_thesis_broken_emits_sell_thesis_broken_for_holding():
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    fund = _fundamental_card("orange", thesis_broken=True)
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("hold", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action == "sell_thesis_broken"
    assert "thesis_broken_detected" in result.risk_flags


def test_risk_gate_red_fundamental_blocks_entry_for_non_holding():
    snapshot = _snapshot(is_holding=False)
    fund = _fundamental_card("red")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("add_batch", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    # Not holding yet — must not enter; wait / hold_no_add acceptable
    assert result.final_action in {"wait", "hold_no_add", "add_on_pullback"}
    # Red block flag should be present (one of these is allowed)
    assert (
        "fundamental_red_blocked" in result.risk_flags
        or "fundamental_red_action" in result.risk_flags
    )


def test_risk_gate_orange_fundamental_blocks_add():
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    fund = _fundamental_card("orange")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("add_batch", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action == "hold_no_add"
    assert "fundamental_orange_blocked" in result.risk_flags


def test_risk_gate_yellow_fundamental_blocks_strong_add():
    snapshot = _snapshot(is_holding=False)
    fund = _fundamental_card("yellow")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("add_batch", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action == "add_on_pullback"
    assert "fundamental_yellow_downgrade" in result.risk_flags


def test_risk_gate_green_fundamental_does_not_block():
    snapshot = _snapshot(is_holding=False)
    fund = _fundamental_card("green")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("add_batch", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    # No fundamental_* flag should fire on green
    assert "fundamental_red_action" not in result.risk_flags
    assert "fundamental_orange_blocked" not in result.risk_flags
    assert "fundamental_yellow_downgrade" not in result.risk_flags


def test_risk_gate_unknown_fundamental_does_not_block():
    snapshot = _snapshot(is_holding=False)
    fund = _fundamental_card("unknown")
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    out = _output("add_batch", max_pct=0.20)

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert "fundamental_red_action" not in result.risk_flags
    assert "fundamental_orange_blocked" not in result.risk_flags
    assert "fundamental_yellow_downgrade" not in result.risk_flags


# === Composer integration ===

def test_composer_keeps_fundamental_status_in_output():
    from app.services.trade_decision_composer import TradeDecisionComposer

    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    fund = _fundamental_card("red", thesis_broken=True)
    pack = _pack(snapshot, fund, thesis=get_thesis("AMD").to_dict())
    composer = TradeDecisionComposer()
    output = composer.compose(pack)
    # The card_pack's fund card has red/thesis_broken, which the gate
    # should have used to downgrade the action.
    assert "risk_gate" in output
    assert output["action"] in {"reduce_now", "sell_thesis_broken"}
    # thesis_status reflects broken
    assert output.get("thesis_status") == "broken"
