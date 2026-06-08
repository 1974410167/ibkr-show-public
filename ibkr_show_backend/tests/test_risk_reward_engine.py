"""Tests for the RiskRewardEngine.

The engine computes upside / downside / R-multiple from deterministic
indicators (MA200, support, 2.5*ATR, fundamental drawdown, target price,
resistance) and never uses the user's cost basis as a downside proxy.
"""

from __future__ import annotations

import math
import pytest

from app.services.investment_thesis import get_thesis
from app.services.risk_reward_engine import (
    CONFIDENCE_LEVELS,
    RiskRewardEngine,
    RiskRewardEstimate,
)


def _engine() -> RiskRewardEngine:
    return RiskRewardEngine()


# === Downside scenarios ===

def test_downside_uses_ma200_not_cost_basis():
    """Engine must not use the user's avg_cost as the downside proxy."""
    e = _engine()
    est = e.estimate(
        last_close=150.0,
        technical_signals={"ma200": 140, "atr14": 4.0, "support_levels": [145]},
    )
    # MA200 is at 140, distance is (140-150)/150 = -6.67% -> abs 6.67%
    scenarios_names = [s["scenario"] for s in est.downside_scenarios]
    assert "ma200_distance" in scenarios_names
    # No scenario called "cost_basis" or "avg_cost"
    assert all("cost" not in n for n in scenarios_names)


def test_downside_includes_support_distance():
    e = _engine()
    est = e.estimate(
        last_close=150.0,
        technical_signals={"support_levels": [140]},
    )
    distances = [s for s in est.downside_scenarios if s["scenario"] == "support_distance"]
    assert distances, "expected support_distance scenario"
    assert math.isclose(distances[0]["distance_pct"], (150 - 140) / 150 * 100, rel_tol=1e-3)


def test_downside_includes_atr_2_5x():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={"atr14": 2.0},  # 2% of price
    )
    atr_scenario = [s for s in est.downside_scenarios if s["scenario"] == "atr_2_5x"]
    assert atr_scenario
    assert math.isclose(atr_scenario[0]["distance_pct"], 5.0, abs_tol=0.01)


def test_downside_fundamental_drawdown_for_red_status():
    from app.agents.trade_decision_cards import FundamentalValuationCard, CardStance

    fund = FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol="AMD",
        decision_type="entry_decision",
        summary="red",
        score=0,
        max_score=35,
        stance=CardStance.BEARISH,
        fundamental_status="red",
    )
    e = _engine()
    est = e.estimate(fundamental=fund, last_close=100.0)
    fd = [s for s in est.downside_scenarios if s["scenario"] == "fundamental_drawdown"]
    assert fd
    assert fd[0]["distance_pct"] == 30.0


def test_downside_extreme_risk_penalty():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        investment_thesis=get_thesis("MSTR"),  # risk_class=extreme
    )
    pen = [s for s in est.downside_scenarios if s["scenario"] == "extreme_risk_penalty"]
    assert pen
    assert pen[0]["distance_pct"] == 15.0


def test_downside_risk_pct_is_max_of_candidates():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "ma200": 90,  # -10% downside
            "support_levels": [85],  # 15% downside
            "atr14": 1.0,  # 2.5% downside
        },
    )
    # Max of |10|, 15, 2.5 = 15
    assert est.downside_risk_pct is not None
    assert math.isclose(est.downside_risk_pct, 15.0, abs_tol=0.01)


# === Upside scenarios ===

def test_upside_includes_target_price_distance():
    from app.agents.trade_decision_cards import FundamentalValuationCard, CardStance

    fund = FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol="AMD",
        decision_type="entry_decision",
        summary="bull",
        score=25,
        max_score=35,
        stance=CardStance.BULLISH,
        target_price=180.0,
    )
    e = _engine()
    est = e.estimate(fundamental=fund, last_close=150.0)
    tp = [s for s in est.upside_scenarios if s["scenario"] == "target_price"]
    assert tp
    assert math.isclose(tp[0]["distance_pct"], 20.0, abs_tol=0.01)


def test_upside_includes_resistance_distance():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={"resistance_levels": [120, 130]},
    )
    res = [s for s in est.upside_scenarios if s["scenario"] == "resistance"]
    assert res
    # Nearest resistance above 100 is 120
    assert math.isclose(res[0]["distance_pct"], 20.0, abs_tol=0.01)


def test_upside_uses_median_for_conservative_estimate():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={"resistance_levels": [110, 130, 200]},
    )
    # Candidates: 10, 30, 100. Median of sorted = 30.
    assert est.upside_potential_pct is not None
    assert math.isclose(est.upside_potential_pct, 30.0, abs_tol=0.01)


# === R-multiple ===

def test_reward_risk_ratio_computed():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "resistance_levels": [130],   # 30% up
            "ma200": 90,                  # 10% down
            "support_levels": [85],       # 15% down (max)
            "atr14": 1.0,                 # 2.5% down
        },
    )
    assert est.upside_potential_pct is not None
    assert est.downside_risk_pct is not None
    assert est.reward_risk_ratio is not None
    # upside 30, downside 15 -> 2.0
    assert math.isclose(est.reward_risk_ratio, 2.0, abs_tol=0.01)


def test_ratio_below_one_triggers_wait_or_reduce():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "resistance_levels": [105],  # 5% up
            "ma200": 70,                 # 30% down
            "support_levels": [80],      # 20% down
        },
    )
    assert est.reward_risk_ratio is not None
    assert est.reward_risk_ratio < 1.0
    # Not holding -> wait
    assert est.action_guidance == "wait"


# === Position size ===

def test_mstr_extreme_risk_caps_max_position():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        investment_thesis=get_thesis("MSTR"),  # risk_class=extreme, base 0.10
    )
    # extreme cap is 0.10; MSTR base is 0.10
    assert est.max_position_pct == 0.10
    assert est.position_size_label in {"small", "medium"}


def test_amd_thesis_caps_at_0_28():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        investment_thesis=get_thesis("AMD"),  # risk_class=high_growth, base 0.28
    )
    # high_growth cap is 0.30; AMD base is 0.28
    assert est.max_position_pct == 0.28


def test_unknown_thesis_default_position_5pct():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        investment_thesis={"role": "unknown", "risk_class": "unknown", "max_position_pct": 0.05},
    )
    assert est.max_position_pct == 0.05


# === Action guidance ===

def test_trend_broken_sets_wait_for_pullback_and_hold_no_add():
    from app.agents.trade_decision_cards import MarketTrendCard, CardStance

    mkt = MarketTrendCard(
        card_type="market_trend", symbol="AMD", decision_type="entry_decision",
        summary="x", score=8, max_score=15, stance=CardStance.BEARISH,
        trend_break_level="broken",
    )
    e = _engine()
    est = e.estimate(market_trend=mkt, last_close=100.0)
    assert est.wait_for_pullback is True
    # trend broken => hold_no_add when ratio is decent
    assert est.action_guidance in {"hold_no_add", "wait"}


def test_fundamental_red_downgrades_action():
    from app.agents.trade_decision_cards import FundamentalValuationCard, CardStance

    fund = FundamentalValuationCard(
        card_type="fundamental_valuation", symbol="AMD", decision_type="entry_decision",
        summary="red", score=0, max_score=35, stance=CardStance.BEARISH,
        fundamental_status="red",
    )
    e = _engine()
    est = e.estimate(fundamental=fund, last_close=100.0)
    # Red => avoid or reduce_now
    assert est.action_guidance in {"avoid", "reduce_now"}


def test_high_ratio_no_thesis_broken_suggests_add_right_side():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "resistance_levels": [200],   # 100% up
            "ma200": 95,                  # 5% down
            "support_levels": [90],       # 10% down
        },
        investment_thesis=get_thesis("AMD"),
    )
    assert est.reward_risk_ratio is not None
    assert est.reward_risk_ratio >= 2.0
    # No trend/fundamental issues => add_right_side
    assert est.action_guidance in {"add_right_side", "add_on_pullback"}


def test_pullback_entry_level_uses_half_downside_clamped():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "support_levels": [88],      # 12% down; half clamps to 6%
            "resistance_levels": [125],  # enough upside for R/R
        },
    )
    assert est.downside_risk_pct == 12.0
    assert est.wait_for_pullback_pct == 6.0
    assert est.pullback_entry_level == 94.0
    d = est.to_dict()
    assert d["wait_for_pullback_pct"] == 6.0
    assert d["pullback_entry_level"] == 94.0


# === Confidence ===

def test_confidence_high_with_full_inputs():
    e = _engine()
    est = e.estimate(
        last_close=100.0,
        technical_signals={
            "ma200": 95, "support_levels": [90], "atr14": 1.0,
            "resistance_levels": [120],
        },
        investment_thesis=get_thesis("AMD"),
    )
    assert est.confidence in {"high", "medium"}


def test_confidence_low_with_no_inputs():
    e = _engine()
    est = e.estimate(last_close=None)
    assert est.confidence in {"low", "unknown"}


# === Data limitations ===

def test_data_limitations_when_no_inputs():
    e = _engine()
    est = e.estimate()
    assert any("下行" in s or "上行" in s for s in est.data_limitations)


# === RiskRewardCard carries the new fields ===

def test_risk_reward_card_has_new_fields():
    from app.agents.trade_decision_cards import RiskRewardCard

    card = RiskRewardCard(
        card_type="risk_reward",
        symbol="AMD",
        decision_type="entry_decision",
        summary="x",
    )
    assert card.downside_scenarios == []
    assert card.upside_scenarios == []
    assert card.stop_add_level is None
    assert card.invalidation_level is None
    assert card.trim_level is None
    assert card.risk_reward_confidence == "unknown"
    assert card.risk_reward_thesis_broken is False
    assert card.action_guidance is None
    assert card.wait_for_pullback_pct is None
    assert card.pullback_entry_level is None

    d = card.to_dict()
    assert "downside_scenarios" in d
    assert "upside_scenarios" in d
    assert "stop_add_level" in d
    assert "invalidation_level" in d
    assert "trim_level" in d
    assert "risk_reward_confidence" in d
    assert "action_guidance" in d
    assert "wait_for_pullback_pct" in d
    assert "pullback_entry_level" in d
