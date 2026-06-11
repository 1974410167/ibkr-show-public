"""Tests for the deterministic TechnicalSignalEngine.

The engine is a pure function over raw OHLCV candlesticks. It computes MA,
MA slope, ATR, volume ratio, returns, relative strength vs benchmarks, and
classifies the trend_break_level (none / warning / broken / severe) using
intentionally conservative rules.

These tests use synthetic candles so the engine is exercised without any
MCP / network calls.
"""

from __future__ import annotations

import math
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
from app.services.technical_signal_engine import (
    TREND_BREAK_LEVELS,
    TechnicalSignalEngine,
    TechnicalSignals,
    extract_benchmark_candles_from_trace,
    extract_raw_candles_from_trace,
    parse_candles,
)
from app.services.trade_decision_risk_gate import apply_risk_gate


# === Helpers ===

def _make_candles(closes: list[float], volumes: list[float] | None = None, base: float | None = None) -> list[dict]:
    """Wrap a list of closes into the OHLCV dict shape the engine expects."""
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    candles = []
    for i, c in enumerate(closes):
        candles.append({
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": volumes[i] if i < len(volumes) else 1_000_000.0,
        })
    return candles


def _uptrend(n: int = 60, start: float = 100.0, step: float = 1.0) -> list[dict]:
    closes = [start + i * step for i in range(n)]
    return _make_candles(closes)


def _downtrend(n: int = 60, start: float = 200.0, step: float = -1.0) -> list[dict]:
    closes = [start + i * step for i in range(n)]
    return _make_candles(closes)


# === Parsing ===

def test_parse_candles_accepts_list_of_dicts():
    raw = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}]
    out = parse_candles(raw)
    assert len(out) == 1
    assert out[0]["close"] == 1.5


def test_parse_candles_accepts_dict_with_items():
    raw = {"items": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}]}
    out = parse_candles(raw)
    assert len(out) == 1


def test_parse_candles_drops_invalid_items():
    raw = [
        {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
        {"high": 2, "low": 0.5, "volume": 100},  # missing close
        "not a dict",
    ]
    out = parse_candles(raw)
    assert len(out) == 1


def test_parse_candles_handles_aliases():
    raw = [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}]
    out = parse_candles(raw)
    assert len(out) == 1
    assert out[0]["close"] == 1.5


# === MA / SMA / slope ===

def test_ma20_matches_simple_average():
    closes = [float(i) for i in range(1, 30)]  # 1..29
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.ma20 is not None
    # Last 20 closes: 10..29 -> avg 19.5
    assert math.isclose(signals.ma20, 19.5, rel_tol=1e-6)


def test_ma50_requires_at_least_50_candles():
    candles = _make_candles([100.0] * 30)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.ma20 is not None
    assert signals.ma50 is None
    assert signals.ma200 is None
    assert any("MA50" in s for s in signals.data_limitations)


def test_ma_slope_positive_for_uptrend():
    candles = _uptrend(80, start=100.0, step=1.0)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert (signals.ma20_slope or 0) > 0
    assert (signals.ma50_slope or 0) > 0


def test_ma_slope_negative_for_downtrend():
    candles = _downtrend(80, start=200.0, step=-1.0)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert (signals.ma20_slope or 0) < 0
    assert (signals.ma50_slope or 0) < 0


# === ATR ===

def test_atr14_returns_none_for_short_series():
    candles = _make_candles([100.0] * 10)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.atr14 is None


def test_atr14_positive_for_normal_volatility():
    closes = [100.0 + 0.5 * ((-1) ** i) for i in range(40)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.atr14 is not None
    assert signals.atr14 > 0
    assert signals.atr14_pct is not None


def test_atr14_pct_is_percentage_of_last_close():
    """atr14_pct must be a percentage (3.2 == 3.2%), computed from last_close."""
    # 60 candles with constant range = 3 (high = c+1.5, low = c-1.5).
    closes = [100.0 + i for i in range(60)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.atr14 is not None
    # last close = 159, ATR ~= 3, so atr14_pct ~= 3 / 159 * 100 ~= 1.89%
    assert 0.5 < signals.atr14_pct < 5.0
    # Crucially: it must be a percentage, not a ratio.
    assert signals.atr14_pct > 1.0, (
        f"atr14_pct {signals.atr14_pct} looks like a ratio, not a percentage"
    )


def test_atr14_pct_anchored_to_last_close():
    """atr14_pct uses the most recent candle's close, not MA20.

    With ATR=3 and last close=159, atr14_pct should be ~3/159*100 = 1.89%.
    The OLD (broken) code used atr14/ma20 which would give ~2.0%; the
    spec requires last_close."""
    candles = []
    for i in range(60):
        c = 100.0 + i
        candles.append({
            "open": c, "high": c + 1.5, "low": c - 1.5, "close": c, "volume": 1_000_000.0,
        })
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, quote={"last_done": 9999.0})
    assert signals.atr14 is not None
    # Anchored to last_close=159, not to MA20 (~149) and not to quote.
    expected = (signals.atr14 / candles[-1]["close"]) * 100.0
    assert math.isclose(signals.atr14_pct, expected, rel_tol=1e-3)


def test_atr14_pct_falls_back_to_ma20_when_no_close_and_no_quote():
    """If neither last_close nor quote is available, MA20 is the fallback anchor."""
    closes = [100.0 + i for i in range(60)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, quote=None)
    assert signals.atr14_pct is not None
    # MA20 ~ avg of last 20 closes, so atr14_pct ~= 3 / MA20 * 100, in the
    # 2-3% range.
    assert 0.5 < signals.atr14_pct < 5.0


# === Volume ratio ===

def test_volume_ratio_high_when_last_volume_spikes():
    closes = [100.0] * 30
    volumes = [1_000_000.0] * 29 + [3_000_000.0]  # 3x spike on last bar
    candles = _make_candles(closes, volumes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.volume_ratio is not None
    assert math.isclose(signals.volume_ratio, 3.0, rel_tol=0.01)


def test_volume_ratio_one_for_flat_volume():
    closes = [100.0] * 30
    volumes = [1_000_000.0] * 30
    candles = _make_candles(closes, volumes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert math.isclose(signals.volume_ratio, 1.0, rel_tol=0.01)


# === Returns ===

def test_return_20d_and_60d():
    closes = [100.0 + i for i in range(70)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    # Last close: 169, close 20d ago: 149 -> return = (169-149)/149 = 13.42%
    assert signals.return_20d_pct is not None
    assert math.isclose(signals.return_20d_pct, (169 - 149) / 149 * 100, rel_tol=1e-3)
    # Last close 169 vs close 60d ago: 109 -> (169-109)/109 = 55.05%
    assert signals.return_60d_pct is not None
    assert math.isclose(signals.return_60d_pct, (169 - 109) / 109 * 100, rel_tol=1e-3)


# === Relative strength ===

def test_relative_strength_positive_when_outperforming_benchmark():
    sym = _uptrend(80, start=100.0, step=1.0)  # closes 100..179
    bmk = _make_candles([200.0 + 0.1 * i for i in range(80)])  # 200..207.9
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=sym, benchmark_candles={"QQQ": bmk})
    # Symbol +80% in last 60d, benchmark +0.4% -> symbol RS positive and large
    rs = signals.relative_strength_60d.get("QQQ")
    assert rs is not None
    assert rs > 30  # big outperformance


def test_relative_strength_score_averages_benchmarks():
    sym = _uptrend(80, start=100.0, step=1.0)
    bmk_a = _make_candles([200.0 + 0.1 * i for i in range(80)])
    bmk_b = _make_candles([300.0 + 0.2 * i for i in range(80)])
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=sym, benchmark_candles={"QQQ": bmk_a, "SPY": bmk_b})
    assert signals.relative_strength_score is not None
    # Each component RS is stored rounded to 2dp; the score is the average.
    # Allow a small tolerance for the compounding rounding.
    expected_avg = (signals.relative_strength_20d["QQQ"] + signals.relative_strength_20d["SPY"]) / 2
    assert math.isclose(signals.relative_strength_score, expected_avg, abs_tol=0.01)


# === Support / resistance ===

def test_support_resistance_levels_present():
    closes = [100 + (i % 7) for i in range(40)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert len(signals.support_levels) > 0
    assert len(signals.resistance_levels) > 0
    # Supports are at the bottom end of recent low prices
    assert min(signals.support_levels) <= min(closes[-20:])
    assert max(signals.resistance_levels) >= max(closes[-20:])


# === Trend break classification ===

def test_trend_break_none_for_strong_uptrend():
    candles = _uptrend(220, start=100.0, step=1.0)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles)
    assert signals.trend_break_level == "none"


def test_trend_break_warning_when_close_below_ma20():
    # Build a series that drops below MA20 at the end
    closes = [100 + i for i in range(40)] + [120 - i for i in range(10)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, quote={"last_done": closes[-1]})
    # Final close way below MA20 -> warning
    assert signals.trend_break_level in {"warning", "broken"}


def test_trend_break_severe_when_close_below_ma200():
    # Build a long series that ends way below its MA200
    closes = [200 - i * 0.3 for i in range(220)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    last = closes[-1]
    signals = engine.compute(symbol_candles=candles, quote={"last_done": last})
    assert signals.trend_break_level == "severe"
    assert any("MA200" in r for r in signals.trend_break_reasons)


def test_trend_break_severe_when_lagging_both_benchmarks():
    sym_closes = [200 - i for i in range(80)]  # declining
    bmk_qqq_closes = [300 + i * 0.5 for i in range(80)]  # rising
    bmk_smh_closes = [400 + i * 0.4 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_qqq = _make_candles(bmk_qqq_closes)
    bmk_smh = _make_candles(bmk_smh_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"QQQ": bmk_qqq, "SMH": bmk_smh},
        quote={"last_done": sym_closes[-1]},
    )
    assert signals.trend_break_level == "severe"


def test_relative_strength_with_only_qqq_us_does_not_mark_severe():
    sym_closes = [200 - i for i in range(80)]
    bmk_qqq_closes = [300 + i * 0.5 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_qqq = _make_candles(bmk_qqq_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"QQQ.US": bmk_qqq},
        quote={"last_done": sym_closes[-1]},
    )
    assert signals.trend_break_level != "severe"
    assert "QQQ" in signals.relative_strength_20d
    assert "QQQ.US" not in signals.relative_strength_20d
    assert any("缺少 QQQ+SMH 双基准确认" in r for r in signals.trend_break_reasons)


def test_relative_strength_with_only_smh_us_does_not_mark_severe():
    sym_closes = [200 - i for i in range(80)]
    bmk_smh_closes = [400 + i * 0.4 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_smh = _make_candles(bmk_smh_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"SMH.US": bmk_smh},
        quote={"last_done": sym_closes[-1]},
    )
    assert signals.trend_break_level != "severe"
    assert "SMH" in signals.relative_strength_20d
    assert "SMH.US" not in signals.relative_strength_20d
    assert any("缺少 QQQ+SMH 双基准确认" in r for r in signals.trend_break_reasons)


def test_trend_break_broken_when_close_below_ma50_with_flat_slope():
    # 60 day downtrend so MA50 is clearly above the last close
    closes = [200 - i for i in range(60)]
    candles = _make_candles(closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, quote={"last_done": closes[-1]})
    assert signals.trend_break_level in {"broken", "severe"}


def test_trend_break_unknown_when_no_quote_no_close():
    # When the engine has no candles, it cannot determine the last close.
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=None, benchmark_candles=None)
    assert signals.trend_break_level == "unknown"


def test_trend_break_uses_last_close_from_candles_when_quote_missing():
    # The engine can resolve last_close from the last candle in the series.
    candles = _uptrend(60)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, quote=None)
    assert signals.trend_break_level == "none"


# === Benchmark key normalization ===

def test_benchmark_keys_are_normalized_to_short_names():
    """Long-form symbols (QQQ.US) must be normalized to short names (QQQ)."""
    sym_closes = [200 - i for i in range(80)]  # declining
    bmk_qqq_closes = [300 + i * 0.5 for i in range(80)]
    bmk_smh_closes = [400 + i * 0.4 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_qqq = _make_candles(bmk_qqq_closes)
    bmk_smh = _make_candles(bmk_smh_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"QQQ.US": bmk_qqq, "SMH.US": bmk_smh},
        quote={"last_done": sym_closes[-1]},
    )
    # Keys must be the short names
    assert "QQQ" in signals.relative_strength_20d
    assert "SMH" in signals.relative_strength_20d
    assert "QQQ.US" not in signals.relative_strength_20d
    assert "SMH.US" not in signals.relative_strength_20d


def test_severe_trend_break_fires_with_long_form_benchmark_symbols():
    """Severe rule (QQQ+SMH both lag materially) must fire when benchmarks
    are passed under their long-form keys."""
    sym_closes = [200 - i for i in range(80)]
    bmk_qqq_closes = [300 + i * 0.5 for i in range(80)]
    bmk_smh_closes = [400 + i * 0.4 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_qqq = _make_candles(bmk_qqq_closes)
    bmk_smh = _make_candles(bmk_smh_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"QQQ.US": bmk_qqq, "SMH.US": bmk_smh},
        quote={"last_done": sym_closes[-1]},
    )
    assert signals.trend_break_level == "severe"
    assert any("跑输" in r for r in signals.trend_break_reasons)


def test_short_form_benchmark_keys_still_work():
    """The canonical short form must keep working unchanged."""
    sym_closes = [200 - i for i in range(80)]
    bmk_qqq_closes = [300 + i * 0.5 for i in range(80)]
    bmk_smh_closes = [400 + i * 0.4 for i in range(80)]
    candles = _make_candles(sym_closes)
    bmk_qqq = _make_candles(bmk_qqq_closes)
    bmk_smh = _make_candles(bmk_smh_closes)
    engine = TechnicalSignalEngine()
    signals = engine.compute(
        symbol_candles=candles,
        benchmark_candles={"QQQ": bmk_qqq, "SMH": bmk_smh},
        quote={"last_done": sym_closes[-1]},
    )
    assert signals.trend_break_level == "severe"


# === Empty / missing data ===

def test_engine_does_not_raise_on_empty_input():
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=None)
    assert signals.trend_break_level == "unknown"
    assert any("K 线" in s for s in signals.data_limitations)


def test_engine_handles_none_benchmark():
    candles = _uptrend(60)
    engine = TechnicalSignalEngine()
    signals = engine.compute(symbol_candles=candles, benchmark_candles={"QQQ": None})
    assert signals.relative_strength_20d == {}


# === Trace extraction helpers ===

def test_extract_raw_candles_from_trace_returns_empty_when_no_data():
    assert extract_raw_candles_from_trace([]) == []
    assert extract_raw_candles_from_trace([{"event": "tool_finish", "tool": "candlesticks", "ok": False}]) == []


def test_extract_raw_candles_from_trace_reads_items():
    trace = [{
        "event": "tool_finish",
        "tool": "candlesticks",
        "ok": True,
        "arguments": {"symbol": "AAPL"},
        "output": {"data": {"items": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}]}},
    }]
    candles = extract_raw_candles_from_trace(trace, "candlesticks", "AAPL")
    assert len(candles) == 1
    assert candles[0]["close"] == 1.5


def test_extract_raw_candles_from_trace_reads_engine_payload():
    trace = [{
        "event": "tool_finish",
        "tool": "candlesticks",
        "ok": True,
        "arguments": {"symbol": "AAPL.US"},
        "output": {
            "data": {"sample_points": 2, "return_pct": 1.2},
            "engine_payload": {
                "kind": "ohlcv_candles",
                "symbol": "AAPL.US",
                "candles": [
                    {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
                    {"open": 1.5, "high": 2.2, "low": 1.4, "close": 2.0, "volume": 120},
                ],
            },
        },
    }]

    candles = extract_raw_candles_from_trace(trace, "candlesticks", "AAPL")

    assert len(candles) == 2
    assert candles[1]["close"] == 2.0


def test_extract_benchmark_candles_from_trace_reads_each_symbol():
    trace = [
        {
            "event": "tool_finish", "tool": "candlesticks", "ok": True,
            "arguments": {"symbol": "QQQ"},
            "output": {"data": {"items": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}]}},
        },
        {
            "event": "tool_finish", "tool": "candlesticks", "ok": True,
            "arguments": {"symbol": "SPY"},
            "output": {"data": {"items": [{"open": 1, "high": 2, "low": 0.5, "close": 1.6, "volume": 100}]}},
        },
    ]
    out = extract_benchmark_candles_from_trace(trace, ["QQQ", "SPY"])
    assert "QQQ" in out
    assert "SPY" in out
    assert out["QQQ"][0]["close"] == 1.5
    assert out["SPY"][0]["close"] == 1.6


# === RiskGate integration with trend_break_level ===

def _snapshot(is_holding=False, position_pct=0.0):
    return AccountFactSnapshot(
        decision_type="entry_decision",
        symbol="AAPL",
        normalized_symbol="AAPL",
        user_question=None,
        net_liquidation=50000.0,
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
        market_value=position_pct * 50000.0,
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


def _trend_card(level, stance=CardStance.NEUTRAL, score=8):
    return MarketTrendCard(
        card_type="market_trend",
        symbol="AAPL",
        decision_type="entry_decision",
        summary="trend",
        score=score,
        max_score=15,
        stance=stance,
        evidence_quality="medium",
        source_tools=["candlesticks"],
        trend_break_level=level,
    )


def _card_pack(snapshot, mkt, evt=None, fund=None, rr=None, acc=None):
    return TradeDecisionCardPack(
        decision_type=snapshot.decision_type,
        symbol=snapshot.symbol,
        account_fact_snapshot=snapshot,
        account_fit_card=acc or AccountFitCard(
            card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
            summary="fit", score=15, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", max_suggested_position_pct=0.10,
            evidence_quality="high", source_tools=[],
        ),
        market_trend_card=mkt,
        fundamental_valuation_card=fund or FundamentalValuationCard(
            card_type="fundamental_valuation", symbol="AAPL", decision_type="entry_decision",
            summary="fund", score=20, max_score=35, stance=CardStance.BULLISH,
            evidence_quality="high", source_tools=[],
        ),
        event_catalyst_card=evt or EventCatalystCard(
            card_type="event_catalyst", symbol="AAPL", decision_type="entry_decision",
            summary="evt", score=4, max_score=5, stance=CardStance.BULLISH,
            catalyst_strength="moderate", sentiment="positive", source_tools=[],
        ),
        risk_reward_card=rr or RiskRewardCard(
            card_type="risk_reward", symbol="AAPL", decision_type="entry_decision",
            summary="rr", score=12, max_score=15, stance=CardStance.BULLISH,
            evidence_quality="medium", source_tools=[],
        ),
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


def test_risk_gate_blocks_add_when_trend_severe():
    snapshot = _snapshot()
    pack = _card_pack(snapshot, _trend_card("severe"))
    out = _output("add_batch")

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action in {"wait", "hold_no_add"}
    assert "trend_break_severe_blocked" in result.risk_flags


def test_risk_gate_blocks_add_when_trend_broken():
    snapshot = _snapshot()
    pack = _card_pack(snapshot, _trend_card("broken"))
    out = _output("add_batch")

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action in {"hold_no_add", "wait"}
    assert "trend_break_broken_blocked" in result.risk_flags


def test_risk_gate_downgrades_chase_add_when_trend_warning():
    snapshot = _snapshot()
    # Use a strong catalyst event so the weak-catalyst rule does not preempt
    # the trend-break rule we're trying to exercise.
    strong_evt = EventCatalystCard(
        card_type="event_catalyst",
        symbol="AAPL",
        decision_type="entry_decision",
        summary="evt",
        score=4,
        max_score=5,
        stance=CardStance.BULLISH,
        catalyst_strength="strong",
        sentiment="positive",
        recent_news_count=5,
        key_events=["Q3 财报超预期", "指引上调"],
        source_tools=[],
    )
    pack = _card_pack(snapshot, _trend_card("warning"), evt=strong_evt)
    out = _output("add")

    _, result = apply_risk_gate(out, pack, user_question=None)

    assert result.final_action == "add_on_pullback"
    assert "trend_break_warning_downgrade" in result.risk_flags


def test_risk_gate_panic_blocked_relents_when_trend_broken():
    """When trend_break_level is broken/severe, the user's panic sell is
    NOT a panic — it is justified by the technical breakdown."""
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    pack = _card_pack(snapshot, _trend_card("broken"))
    out = _output("sell", max_pct=0.10)

    _, result = apply_risk_gate(
        out, pack, user_question="我受不了了，暴跌 20%，赶紧清仓！",
    )

    assert result.final_action != "panic_blocked"
    assert "panic_sell_blocked" not in result.risk_flags


def test_risk_gate_panic_blocked_still_blocks_when_trend_unknown():
    snapshot = _snapshot(is_holding=True, position_pct=0.10)
    pack = _card_pack(snapshot, _trend_card("unknown"))
    out = _output("sell", max_pct=0.10)

    _, result = apply_risk_gate(
        out, pack, user_question="我受不了了，暴跌 20%，赶紧清仓！",
    )

    assert result.final_action == "panic_blocked"
    assert "panic_sell_blocked" in result.risk_flags


def test_risk_gate_does_not_block_add_when_trend_none():
    snapshot = _snapshot()
    pack = _card_pack(snapshot, _trend_card("none"))
    out = _output("add_batch", max_pct=0.10)

    _, result = apply_risk_gate(out, pack, user_question=None)

    # No trend-break downgrade; the action should pass through unchanged
    assert "trend_break_severe_blocked" not in result.risk_flags
    assert "trend_break_broken_blocked" not in result.risk_flags
    assert "trend_break_warning_downgrade" not in result.risk_flags
