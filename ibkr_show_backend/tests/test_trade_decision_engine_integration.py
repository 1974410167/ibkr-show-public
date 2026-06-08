"""Integration tests for the optimization engines wired into the
trade decision sub-agents, composer, and risk gate.

Covers:
- TechnicalSignalEngine integration in MarketTrendSubAgent._parse_card
- FundamentalChangeEngine integration in FundamentalValuationSubAgent._parse_card
- RiskRewardEngine integration in RiskRewardSubAgent._build_card
- RiskGate fail-safe
- RiskGate confidence cap
- thesis vs gate order consistency
- full composer integration (technical_signals / fundamental_status /
  downside_scenarios / investment_thesis / risk_gate all present)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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
    TradeDecisionSubAgentTrace,
    build_fallback_account_fit_card,
    build_fallback_event_card,
    build_fallback_fundamental_card,
    build_fallback_market_trend_card,
    build_fallback_risk_reward_card,
)
from app.services.investment_thesis import get_thesis
from app.services.trade_decision_composer import TradeDecisionComposer
from app.services.trade_decision_risk_gate import apply_risk_gate, make_fail_safe_result
from app.services.trade_decision_sub_agents import (
    FundamentalValuationSubAgent,
    MarketTrendSubAgent,
    RiskRewardSubAgent,
)
from app.services.technical_signal_engine import (
    TechnicalSignalEngine,
    extract_benchmark_candles_from_trace,
    extract_raw_candles_from_trace,
)


# === Shared fixtures ===

def _snapshot(symbol="AMD", is_holding=False, position_pct=0.0, current_price=150.0):
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
        avg_cost=100.0 if is_holding else None,
        current_price=current_price,
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


def _candles_tool_event(symbol: str, items: list[dict]) -> dict:
    return {
        "event": "tool_finish",
        "tool": "candlesticks",
        "ok": True,
        "arguments": {"symbol": symbol, "period": "day"},
        "output": {"data": {"items": items}},
    }


def _quote_event(symbol: str, price: float) -> dict:
    return {
        "event": "tool_finish",
        "tool": "quote",
        "ok": True,
        "arguments": {"symbol": symbol},
        "output": {"data": {"last_done": price, "price": price}},
    }


def _make_uptrend_candles(n: int = 220, start: float = 100.0, step: float = 1.0) -> list[dict]:
    return [
        {
            "open": start + i * step,
            "high": (start + i * step) * 1.01,
            "low": (start + i * step) * 0.99,
            "close": start + i * step,
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]


# ====================================================================
# TechnicalSignalEngine integration in MarketTrendSubAgent._parse_card
# ====================================================================

def test_market_trend_subagent_wires_technical_signals_into_card():
    """MarketTrendSubAgent._parse_card must populate technical_signals,
    trend_break_level, support/resistance levels, and relative_strength_score
    from the candlesticks in the runtime trace."""
    sub_agent = MarketTrendSubAgent.__new__(MarketTrendSubAgent)
    sub_agent.llm_service = MagicMock()
    sub_agent.prompt_service = None
    sub_agent.monitoring_service = None
    sub_agent._last_prompt_metadata = None
    sub_agent.adapter = None

    # Build a fake trace with raw candlesticks for the symbol + benchmarks
    symbol_candles = _make_uptrend_candles(220, start=100.0, step=1.0)
    qqq_candles = _make_uptrend_candles(220, start=200.0, step=0.1)
    spy_candles = _make_uptrend_candles(220, start=300.0, step=0.2)
    smh_candles = _make_uptrend_candles(220, start=400.0, step=0.15)

    trace = [
        _candles_tool_event("AMD.US", symbol_candles),
        _candles_tool_event("QQQ.US", qqq_candles),
        _candles_tool_event("SPY.US", spy_candles),
        _candles_tool_event("SMH.US", smh_candles),
        _quote_event("AMD.US", 320.0),  # close of the 220-step uptrend
    ]

    snapshot = _snapshot(symbol="AMD", current_price=320.0)
    parsed = {"price_trend": "bullish", "score": 12, "summary": "bullish"}

    card = sub_agent._parse_card(parsed, "raw text", snapshot, trace)

    # Required Stage 02 fields
    assert isinstance(card, MarketTrendCard)
    assert card.technical_signals, "technical_signals must be populated"
    assert card.trend_break_level in {"none", "warning", "broken", "severe", "unknown"}
    assert isinstance(card.support_levels, list)
    assert isinstance(card.resistance_levels, list)
    # Strong uptrend: trend_break should be none
    assert card.trend_break_level in {"none", "warning"}
    # With benchmarks in the trace, relative_strength_score should exist
    assert card.relative_strength_score is not None or any(
        card.technical_signals.get("data_limitations") or []
    )


def test_market_trend_subagent_works_without_raw_candles():
    """When only the compact summary is in the trace (the common MCP path),
    the subagent must not raise; technical_signals carries a data_limitation
    and trend_break_level is 'unknown'."""
    sub_agent = MarketTrendSubAgent.__new__(MarketTrendSubAgent)
    sub_agent.llm_service = MagicMock()
    sub_agent.prompt_service = None
    sub_agent.monitoring_service = None
    sub_agent._last_prompt_metadata = None
    sub_agent.adapter = None

    # Compact summary only - no items
    trace = [
        {
            "event": "tool_finish",
            "tool": "candlesticks",
            "ok": True,
            "arguments": {"symbol": "AMD.US", "period": "day"},
            "output": {"data": {"sample_points": 220, "return_pct": 5.0, "latest_close": 150.0}},
        },
        _quote_event("AMD.US", 150.0),
    ]
    snapshot = _snapshot(symbol="AMD", current_price=150.0)
    parsed = {"price_trend": "bullish", "score": 8, "summary": "bullish"}

    card = sub_agent._parse_card(parsed, "raw text", snapshot, trace)

    # Must not crash; trend_break_level must be 'unknown' when no raw data
    assert card.trend_break_level == "unknown"
    # The data_limitations should explain why
    sigs = card.technical_signals or {}
    limitations = sigs.get("data_limitations") or []
    assert any("K 线" in s or "原始" in s or "data" in s.lower() for s in limitations)


# ====================================================================
# FundamentalChangeEngine integration
# ====================================================================

def _financial_report_event(items: list[dict]) -> dict:
    return {
        "event": "tool_finish",
        "tool": "financial_report",
        "ok": True,
        "arguments": {"symbol": "AMD", "kind": "ALL", "period": "qf", "count": 4},
        "output": {"data": {"items": items}},
    }


def test_fundamental_subagent_wires_change_engine_into_card():
    """FundamentalValuationSubAgent._parse_card must populate
    fundamental_status / thesis_broken / change_signals / margin_trend /
    cash_flow_trend / guidance_change from the trace."""
    sub_agent = FundamentalValuationSubAgent.__new__(FundamentalValuationSubAgent)
    sub_agent.llm_service = MagicMock()
    sub_agent.prompt_service = None
    sub_agent.monitoring_service = None
    sub_agent._last_prompt_metadata = None
    sub_agent.adapter = None

    # Build a 4-quarter series showing declining revenue + margin compression
    # + negative FCF in the latest quarter. The engine should pick this up.
    reports = [
        {"revenue": 1000, "gross_margin": 45.0, "operating_cash_flow": 200, "free_cash_flow": 100},
        {"revenue": 1050, "gross_margin": 44.0, "operating_cash_flow": 180, "free_cash_flow": 80},
        {"revenue": 1020, "gross_margin": 42.0, "operating_cash_flow": 150, "free_cash_flow": 50},
        {"revenue": 980,  "gross_margin": 40.0, "operating_cash_flow": 100, "free_cash_flow": 10},
    ]
    trace = [
        _financial_report_event(reports),
        {
            "event": "tool_finish",
            "tool": "valuation",
            "ok": True,
            "arguments": {"symbol": "AMD"},
            "output": {"data": {"pe_ttm": 22.0, "forward_pe": 18.0, "target_price": 150.0}},
        },
    ]
    snapshot = _snapshot(symbol="AMD", current_price=130.0)
    parsed = {
        "price_trend": "neutral",
        "score": 10,
        "summary": "mixed",
        "company_name": "AMD",
    }

    card = sub_agent._parse_card(parsed, "raw text", snapshot, trace)

    assert isinstance(card, FundamentalValuationCard)
    # Engine must have run; fundamental_status must be in our enum (not empty)
    assert card.fundamental_status in {"green", "yellow", "orange", "red", "unknown"}
    # With multiple negatives (revenue slowdown, margin compression,
    # cash flow deterioration), the engine should report at least yellow.
    assert card.fundamental_status in {"yellow", "orange", "red"}
    # The change_signals list must be populated with the actual signals
    assert isinstance(card.change_signals, list)
    assert isinstance(card.positive_signals, list)
    assert isinstance(card.negative_signals, list)
    # The trend fields should be set
    assert card.margin_trend in {"compressing", "stable", "expanding", None}
    assert card.cash_flow_trend in {"deteriorating", "stable", "improving", "negative", None}


def test_fundamental_subagent_handles_compact_financial_data():
    """When financial_report is compacted to a summary (sample_points etc.)
    the engine must not fabricate signals; status should be 'unknown'."""
    sub_agent = FundamentalValuationSubAgent.__new__(FundamentalValuationSubAgent)
    sub_agent.llm_service = MagicMock()
    sub_agent.prompt_service = None
    sub_agent.monitoring_service = None
    sub_agent._last_prompt_metadata = None
    sub_agent.adapter = None

    # Compact summary - the engine should not produce change_signals
    trace = [
        {
            "event": "tool_finish",
            "tool": "financial_report",
            "ok": True,
            "arguments": {"symbol": "AMD"},
            "output": {"data": {"sample_points": 4, "return_pct": 5.0}},
        },
    ]
    snapshot = _snapshot(symbol="AMD", current_price=150.0)
    parsed = {"price_trend": "neutral", "score": 10, "summary": "x"}

    card = sub_agent._parse_card(parsed, "raw text", snapshot, trace)

    # With no raw revenue/margin series, fundamental_status must be 'unknown'
    assert card.fundamental_status == "unknown"
    # And the change_signals must NOT be fabricated
    assert card.change_signals == []
    assert card.negative_signals == []


# ====================================================================
# RiskRewardEngine integration
# ====================================================================

def test_risk_reward_subagent_uses_engine_not_cost_basis():
    """RiskRewardSubAgent._build_card must produce a downside NOT derived
    from avg_cost * 0.85. The downside_scenarios should reference
    MA200/support/ATR, not 'cost'."""
    mock_llm = MagicMock()
    sub_agent = RiskRewardSubAgent(mock_llm)

    snapshot = _snapshot(symbol="AMD", is_holding=True, position_pct=0.10,
                         current_price=150.0)
    # Avg cost is intentionally very low so the OLD algorithm would say
    # downside is huge (and upside fixed at +30%).
    snapshot.avg_cost = 50.0

    market_trend = build_fallback_market_trend_card("AMD", "entry_decision", "x")
    market_trend.technical_signals = {
        "resistance_levels": [165, 180],
        "support_levels": [140, 130],
        "ma200": 145,
        "ma50": 148,
        "ma20": 150,
        "atr14": 4.0,
        "atr14_pct": 2.7,
        "volume_ratio": 1.0,
        "return_20d_pct": 3.5,
        "relative_strength_20d": {},
        "relative_strength_60d": {},
        "trend_break_level": "none",
        "trend_break_reasons": [],
        "data_limitations": [],
        "relative_strength_score": None,
    }
    fund = build_fallback_fundamental_card("AMD", "entry_decision", "x")
    fund.target_price = 180.0
    fund.fundamental_status = "green"
    account_fit = build_fallback_account_fit_card("AMD", "entry_decision", "x")
    account_fit.max_suggested_position_pct = 0.10
    evt = build_fallback_event_card("AMD", "entry_decision", "x")

    card = sub_agent._build_card(snapshot, account_fit, market_trend, fund, evt)

    # Downside must NOT be derived from avg_cost. The scenarios should
    # reference structural inputs.
    assert card.downside_scenarios
    for s in card.downside_scenarios:
        scen = str(s.get("scenario") or "").lower()
        assert "cost" not in scen, f"cost-based downside still present: {s}"
    # The seeded risk_assessment_reason references the engine, not cost.
    assert "RiskRewardEngine" in (card.risk_assessment_reason or "")
    # And the new structural fields are populated
    assert card.stop_add_level is not None
    assert card.invalidation_level is not None
    assert card.trim_level is not None
    assert card.risk_reward_confidence in {"high", "medium", "low", "unknown"}


def test_risk_reward_subagent_action_guidance_tends_to_wait_when_data_missing():
    """When no technical_signals and no target_price are available, the
    engine should not fabricate a positive reward_risk_ratio; the sub-agent
    should land in a conservative state."""
    mock_llm = MagicMock()
    sub_agent = RiskRewardSubAgent(mock_llm)

    snapshot = _snapshot(symbol="UNKNOWN_X", is_holding=False,
                         current_price=None)
    market_trend = build_fallback_market_trend_card("UNKNOWN_X", "entry_decision", "x")
    market_trend.technical_signals = {}  # no inputs
    fund = build_fallback_fundamental_card("UNKNOWN_X", "entry_decision", "x")
    account_fit = build_fallback_account_fit_card("UNKNOWN_X", "entry_decision", "x")
    evt = build_fallback_event_card("UNKNOWN_X", "entry_decision", "x")

    card = sub_agent._build_card(snapshot, account_fit, market_trend, fund, evt)

    # reward_risk_ratio must not be a fabricated high number
    if card.reward_risk_ratio is not None:
        assert card.reward_risk_ratio < 5.0  # sanity: not absurdly high
    # The risk_assessment_reason should reference the engine's action_guidance
    assert "action_guidance" in (card.risk_assessment_reason or "")
    assert card.action_guidance == "wait"


# ====================================================================
# RiskGate fail-safe
# ====================================================================

def test_risk_gate_fail_safe_action_hold_no_add_for_holding():
    """When apply_risk_gate raises, the composer must:
    - attach risk_gate.status=failed
    - downgrade action to hold_no_add (if holding) or wait
    - set confidence=low
    - surface 'risk_gate_failed' in review_warnings
    """
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    card_pack = TradeDecisionCardPack(
        decision_type="holding_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "holding_decision", "x"),
        market_trend_card=build_fallback_market_trend_card("AMD", "holding_decision", "x"),
        fundamental_valuation_card=build_fallback_fundamental_card("AMD", "holding_decision", "x"),
        event_catalyst_card=build_fallback_event_card("AMD", "holding_decision", "x"),
        risk_reward_card=build_fallback_risk_reward_card("AMD", "holding_decision", "x"),
    )

    composer = TradeDecisionComposer()
    with patch("app.services.trade_decision_risk_gate.apply_risk_gate",
               side_effect=RuntimeError("synthetic gate failure")):
        output = composer.compose(card_pack)

    # action must be hold_no_add (we are holding)
    assert output["action"] == "hold_no_add"
    # confidence must be low
    assert output["confidence"] == "low"
    # risk_gate block must be present and failed
    assert "risk_gate" in output
    assert output["risk_gate"].get("failed") is True
    assert output["risk_gate"].get("error")
    # review_warnings must contain risk_gate:risk_gate_failed
    assert any("risk_gate_failed" in s for s in output.get("review_warnings") or [])
    # data_limitations must mention the failure
    assert any("RiskGate" in s and ("失败" in s or "fail" in s.lower()) for s in output.get("data_limitations") or [])


def test_risk_gate_fail_safe_action_wait_for_non_holding():
    snapshot = _snapshot(is_holding=False)
    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "entry_decision", "x"),
        market_trend_card=build_fallback_market_trend_card("AMD", "entry_decision", "x"),
        fundamental_valuation_card=build_fallback_fundamental_card("AMD", "entry_decision", "x"),
        event_catalyst_card=build_fallback_event_card("AMD", "entry_decision", "x"),
        risk_reward_card=build_fallback_risk_reward_card("AMD", "entry_decision", "x"),
    )
    composer = TradeDecisionComposer()
    with patch("app.services.trade_decision_risk_gate.apply_risk_gate",
               side_effect=ValueError("boom")):
        output = composer.compose(card_pack)
    assert output["action"] == "wait"
    assert output["confidence"] == "low"
    assert output["risk_gate"]["failed"] is True


def test_make_fail_safe_result_helper_outputs_conservative_defaults():
    snapshot = _snapshot(is_holding=True, position_pct=0.20)
    res = make_fail_safe_result("add_batch", snapshot, "boom")
    assert res.failed is True
    assert res.final_action == "hold_no_add"
    assert res.confidence_cap == "low"
    assert "risk_gate_failed" in res.risk_flags

    snapshot2 = _snapshot(is_holding=False)
    res2 = make_fail_safe_result("add_batch", snapshot2, "boom")
    assert res2.final_action == "wait"
    assert res2.confidence_cap == "low"


# ====================================================================
# RiskGate confidence cap (P2)
# ====================================================================

def test_risk_gate_caps_confidence_when_public_data_broadly_fallback():
    """When 3+ public cards are INSUFFICIENT_DATA, the gate must cap
    confidence at 'low' regardless of what the composer picked."""
    snapshot = _snapshot(is_holding=False)
    snapshot.user_question = None
    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "entry_decision", "x"),
        # All public cards marked insufficient
        market_trend_card=_make_fallback_market_trend("AMD", "entry_decision", "x", fallback=True),
        fundamental_valuation_card=_make_fallback_fundamental("AMD", "entry_decision", "x", fallback=True),
        event_catalyst_card=_make_fallback_event("AMD", "entry_decision", "x", fallback=True),
        risk_reward_card=build_fallback_risk_reward_card("AMD", "entry_decision", "x"),
    )
    decision_output = {
        "action": "add_batch",
        "confidence": "high",
        "decision_summary": "test",
        "position_advice": {"max_position_pct": 0.10, "current_position_pct": 0.0,
                            "suggested_target_position_pct": 0.05,
                            "suggested_cash_amount": 0, "position_size_label": "medium"},
        "execution_plan": {"invalid_conditions": ["PE>60"]},
        "data_limitations": [],
        "review_warnings": [],
    }
    output, gate = apply_risk_gate(decision_output, card_pack, user_question=None)

    # Confidence must be capped at low when 3+ public cards are fallback
    assert output["confidence"] == "low"
    assert gate.confidence_cap == "low"


def test_risk_gate_caps_confidence_at_medium_on_insufficient_data():
    """insufficient_data flag (set when public_fallback_count >= 2) caps
    confidence at medium but not lower than the existing confidence."""
    snapshot = _snapshot(is_holding=False)
    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "entry_decision", "x"),
        # 2 of 3 public cards fallback
        market_trend_card=_make_fallback_market_trend("AMD", "entry_decision", "x", fallback=True),
        fundamental_valuation_card=_make_fallback_fundamental("AMD", "entry_decision", "x", fallback=True),
        event_catalyst_card=build_fallback_event_card("AMD", "entry_decision", "x"),
        risk_reward_card=build_fallback_risk_reward_card("AMD", "entry_decision", "x"),
    )
    decision_output = {
        "action": "add_batch",
        "confidence": "high",
        "decision_summary": "test",
        "position_advice": {"max_position_pct": 0.10, "current_position_pct": 0.0,
                            "suggested_target_position_pct": 0.05,
                            "suggested_cash_amount": 0, "position_size_label": "medium"},
        "execution_plan": {"invalid_conditions": ["PE>60"]},
        "data_limitations": [],
        "review_warnings": [],
    }
    output, gate = apply_risk_gate(decision_output, card_pack, user_question=None)

    # Should be capped at medium (or lower if other rules also fire)
    assert output["confidence"] in {"medium", "low"}
    assert gate.confidence_cap in {"medium", "low"}


def test_risk_gate_does_not_raise_confidence():
    """If the original confidence is already low, the gate must not raise it."""
    snapshot = _snapshot(is_holding=False)
    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "entry_decision", "x"),
        market_trend_card=build_fallback_market_trend_card("AMD", "entry_decision", "x"),
        fundamental_valuation_card=build_fallback_fundamental_card("AMD", "entry_decision", "x"),
        event_catalyst_card=build_fallback_event_card("AMD", "entry_decision", "x"),
        risk_reward_card=build_fallback_risk_reward_card("AMD", "entry_decision", "x"),
    )
    decision_output = {
        "action": "hold",
        "confidence": "low",
        "decision_summary": "test",
        "position_advice": {"max_position_pct": 0.10, "current_position_pct": 0.0,
                            "suggested_target_position_pct": 0.0,
                            "suggested_cash_amount": 0, "position_size_label": "none"},
        "execution_plan": {"invalid_conditions": []},
        "data_limitations": [],
        "review_warnings": [],
    }
    output, _gate = apply_risk_gate(decision_output, card_pack, user_question=None)
    assert output["confidence"] == "low"


# ====================================================================
# thesis vs gate order consistency (P3)
# ====================================================================

def test_thesis_max_position_pct_applied_before_risk_gate():
    """After composer.compose, the final position_advice.max_position_pct
    should reflect the thesis (e.g. AMD's 0.28) and the risk_gate
    action_constraints.snapshot.max_position_pct should agree.

    We use a healthy card pack so the composer picks an add-like action
    that triggers _apply_thesis_to_position."""
    snapshot = _snapshot(is_holding=False, position_pct=0.0, current_price=320.0)
    snapshot.user_question = "AMD 现在该不该加仓？"

    # Build a healthy, high-score card pack so the composer picks an add-like action
    market_trend = _attach_technical(
        build_fallback_market_trend_card("AMD", "entry_decision", "x"),
        level="none",
    )
    market_trend.score = 12
    market_trend.stance = CardStance.BULLISH
    market_trend.evidence_quality = "high"
    market_trend.summary = "uptrend"

    fund = _make_fundamental_with_status("AMD", "entry_decision", "green")
    fund.score = 28
    fund.stance = CardStance.BULLISH
    fund.evidence_quality = "high"
    fund.pe_ttm = 22.0
    fund.target_price = 380.0

    account_fit = build_fallback_account_fit_card("AMD", "entry_decision", "x")
    account_fit.score = 18
    account_fit.max_suggested_position_pct = 0.10
    account_fit.account_fit_level = "good"
    account_fit.deployable_liquidity = 60000.0
    account_fit.deployable_liquidity_ratio = 0.6

    evt = build_fallback_event_card("AMD", "entry_decision", "x")
    evt.score = 4
    evt.stance = CardStance.BULLISH
    evt.catalyst_strength = "strong"
    evt.sentiment = "positive"
    evt.key_events = ["Q3 财报超预期", "指引上调"]
    evt.key_events = ["Q3 财报超预期", "指引上调"]
    evt.recent_news_count = 5

    rr = build_fallback_risk_reward_card("AMD", "entry_decision", "x")
    rr.score = 12
    rr.stance = CardStance.BULLISH
    rr.reward_risk_ratio = 2.5
    rr.upside_potential_pct = 20.0
    rr.downside_risk_pct = 8.0
    rr.max_position_pct = 0.20
    rr.invalidation_level = 290.0

    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=account_fit,
        market_trend_card=market_trend,
        fundamental_valuation_card=fund,
        event_catalyst_card=evt,
        risk_reward_card=rr,
        investment_thesis=get_thesis("AMD").to_dict(),
    )
    output = TradeDecisionComposer().compose(card_pack)

    # Final action should be add-like (not wait/avoid)
    assert output["action"] in {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side", "hold"}, (
        f"expected add-like action, got {output['action']}"
    )
    # Final position_advice.max_position_pct should equal the AMD thesis max (0.28)
    final_max = float(output["position_advice"]["max_position_pct"] or 0)
    assert final_max == 0.28, f"expected thesis max 0.28, got {final_max}"
    # risk_gate block (if present) should also reflect the thesis max
    rg = output.get("risk_gate") or {}
    snapshot_block = (rg.get("action_constraints") or {}).get("snapshot") or {}
    if snapshot_block.get("max_position_pct") is not None:
        gate_max = float(snapshot_block["max_position_pct"])
        # Gate may have applied a smaller cap, but it should never be
        # higher than the thesis max
        assert gate_max <= 0.28 + 1e-6


# ====================================================================
# Full composer integration
# ====================================================================

def test_full_composer_integration_carries_all_optimization_signals():
    """The composed decision output must include all optimization signals:
    - risk_gate block
    - investment_thesis / thesis_status / thesis_constraints
    - The underlying cards' new fields (when cards are present)
    """
    snapshot = _snapshot(is_holding=True, position_pct=0.05)
    snapshot.user_question = "AMD 现在该不该加仓？"

    market_trend = _attach_technical(
        build_fallback_market_trend_card("AMD", "holding_decision", "x"),
        level="none",
    )
    fund = _make_fundamental_with_status("AMD", "holding_decision", "green")
    rr = build_fallback_risk_reward_card("AMD", "holding_decision", "x")
    # Give the rr card structural fields so we can assert they survive compose
    rr.reward_risk_ratio = 1.8
    rr.upside_potential_pct = 20.0
    rr.downside_risk_pct = 11.0
    rr.downside_scenarios = [{"scenario": "ma200_distance", "distance_pct": 6.0, "ref_price": 140}]
    rr.upside_scenarios = [{"scenario": "resistance", "distance_pct": 15.0, "ref_price": 170}]
    rr.invalidation_level = 135.0

    card_pack = TradeDecisionCardPack(
        decision_type="holding_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=build_fallback_account_fit_card("AMD", "holding_decision", "x"),
        market_trend_card=market_trend,
        fundamental_valuation_card=fund,
        event_catalyst_card=build_fallback_event_card("AMD", "holding_decision", "x"),
        risk_reward_card=rr,
        investment_thesis=get_thesis("AMD").to_dict(),
    )
    output = TradeDecisionComposer().compose(card_pack)

    # Risk gate present
    assert "risk_gate" in output
    rg = output["risk_gate"]
    assert rg.get("failed") is not True
    assert "original_action" in rg
    assert "final_action" in rg
    assert "confidence_cap" in rg
    assert "risk_flags" in rg

    # Investment thesis present
    assert "investment_thesis" in output
    assert output["investment_thesis"].get("role") == "core_growth"
    assert "thesis_status" in output
    assert "thesis_constraints" in output
    assert "thesis_risks" in output

    # Risk reward structural fields preserved
    final_rr = (output.get("score_detail") or {}).get("risk_reward_score") or {}
    assert final_rr.get("max_score") == 15

    # Position advice has the thesis max
    pa = output.get("position_advice") or {}
    final_max = float(pa.get("max_position_pct") or 0)
    # Thesis max 0.28; the gate may have lowered it but should not have raised
    assert final_max <= 0.28 + 1e-6


def test_composer_uses_risk_reward_action_guidance_for_pullback_plan():
    snapshot = _snapshot(is_holding=False, current_price=100.0)
    account_fit = build_fallback_account_fit_card("AMD", "entry_decision", "x")
    account_fit.account_fit_level = "good"
    account_fit.max_suggested_position_pct = 0.20
    account_fit.suggested_cash_amount = 10000.0
    market_trend = _attach_technical(
        build_fallback_market_trend_card("AMD", "entry_decision", "x"),
        level="none",
    )
    market_trend.score = 12
    market_trend.stance = CardStance.BULLISH
    market_trend.evidence_quality = "medium"
    fund = _make_fundamental_with_status("AMD", "entry_decision", "green")
    fund.score = 26
    fund.stance = CardStance.BULLISH
    fund.evidence_quality = "high"
    evt = build_fallback_event_card("AMD", "entry_decision", "x")
    evt.score = 4
    evt.stance = CardStance.BULLISH
    evt.evidence_quality = "medium"
    evt.catalyst_strength = "strong"
    evt.sentiment = "positive"
    evt.key_events = ["Q3 财报超预期", "指引上调"]
    rr = build_fallback_risk_reward_card("AMD", "entry_decision", "x")
    rr.score = 12
    rr.stance = CardStance.BULLISH
    rr.reward_risk_ratio = 1.8
    rr.downside_risk_pct = 12.0
    rr.upside_potential_pct = 22.0
    rr.max_position_pct = 0.20
    rr.action_guidance = "add_on_pullback"
    rr.wait_for_pullback_pct = 6.0
    rr.pullback_entry_level = 94.0

    card_pack = TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=account_fit,
        market_trend_card=market_trend,
        fundamental_valuation_card=fund,
        event_catalyst_card=evt,
        risk_reward_card=rr,
        investment_thesis=get_thesis("AMD").to_dict(),
    )
    output = TradeDecisionComposer().compose(card_pack)

    assert output["risk_gate"]["original_action"] == "add_on_pullback"
    assert output["action"] == "add_on_pullback"
    plan = output["execution_plan"]["plan"]
    assert "6.0%" in plan[0]["condition"]
    assert "94.00" in plan[0]["condition"]


# === Helpers for integration tests ===

def _make_fallback_market_trend(symbol, decision_type, reason, fallback=False):
    card = build_fallback_market_trend_card(symbol, decision_type, reason)
    if fallback:
        card.stance = CardStance.INSUFFICIENT_DATA
        card.evidence_quality = "low"
        card.score = 0
        card.trend_break_level = "unknown"
    return card


def _make_fallback_fundamental(symbol, decision_type, reason, fallback=False):
    card = build_fallback_fundamental_card(symbol, decision_type, reason)
    if fallback:
        card.stance = CardStance.INSUFFICIENT_DATA
        card.evidence_quality = "low"
        card.score = 0
        card.fundamental_status = "unknown"
    return card


def _make_fallback_event(symbol, decision_type, reason, fallback=False):
    card = build_fallback_event_card(symbol, decision_type, reason)
    if fallback:
        card.stance = CardStance.INSUFFICIENT_DATA
        card.evidence_quality = "low"
        card.score = 0
    return card


def _attach_technical(card: MarketTrendCard, level: str = "none") -> MarketTrendCard:
    """Inject a deterministic technical_signals block so the engine has
    stable inputs when the RiskRewardSubAgent re-reads the market card."""
    card.technical_signals = {
        "ma20": 150.0, "ma50": 148.0, "ma200": 145.0,
        "ma20_slope": 0.005, "ma50_slope": 0.004, "ma200_slope": 0.002,
        "atr14": 4.0, "atr14_pct": 2.7,
        "volume_ratio": 1.0,
        "return_20d_pct": 3.5, "return_60d_pct": 8.0,
        "relative_strength_20d": {"QQQ": 1.2, "SPY": 1.0, "SMH": 0.8},
        "relative_strength_60d": {"QQQ": 3.5, "SPY": 2.8, "SMH": 2.0},
        "support_levels": [140, 130],
        "resistance_levels": [165, 180],
        "trend_break_level": level,
        "trend_break_reasons": [],
        "data_limitations": [],
        "relative_strength_score": 1.0,
    }
    return card


def _make_fundamental_with_status(symbol, decision_type, status: str) -> FundamentalValuationCard:
    card = build_fallback_fundamental_card(symbol, decision_type, "x")
    card.fundamental_status = status
    return card
