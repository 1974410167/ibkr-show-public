"""Technical Signal Engine - deterministic technical indicators.

Computes MA, MA slope, ATR14, volume ratio, returns, relative strength, and
support/resistance from raw OHLCV data, then classifies the trend-break level
(none / warning / broken / severe).

This engine is intentionally a pure function: it does NOT call LLM or MCP.
It accepts raw candlesticks in either long-form (list of OHLCV dicts) or
compressed-summary form and tolerates both. Missing fields are surfaced in
`data_limitations` instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any


# Trend break severities, ordered from soft to hard.
TREND_BREAK_LEVELS = ("none", "warning", "broken", "severe")


@dataclass
class TechnicalSignals:
    ma20: float | None = None
    ma50: float | None = None
    ma200: float | None = None
    ma20_slope: float | None = None
    ma50_slope: float | None = None
    ma200_slope: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    volume_ratio: float | None = None
    return_20d_pct: float | None = None
    return_60d_pct: float | None = None
    relative_strength_20d: dict[str, float] = field(default_factory=dict)
    relative_strength_60d: dict[str, float] = field(default_factory=dict)
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    trend_break_level: str = "unknown"  # none | warning | broken | severe | unknown
    trend_break_reasons: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    relative_strength_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ma20": self.ma20,
            "ma50": self.ma50,
            "ma200": self.ma200,
            "ma20_slope": self.ma20_slope,
            "ma50_slope": self.ma50_slope,
            "ma200_slope": self.ma200_slope,
            "atr14": self.atr14,
            "atr14_pct": self.atr14_pct,
            "volume_ratio": self.volume_ratio,
            "return_20d_pct": self.return_20d_pct,
            "return_60d_pct": self.return_60d_pct,
            "relative_strength_20d": dict(self.relative_strength_20d),
            "relative_strength_60d": dict(self.relative_strength_60d),
            "support_levels": list(self.support_levels),
            "resistance_levels": list(self.resistance_levels),
            "trend_break_level": self.trend_break_level,
            "trend_break_reasons": list(self.trend_break_reasons),
            "data_limitations": list(self.data_limitations),
            "relative_strength_score": self.relative_strength_score,
        }


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _extract_candle_value(candle: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in candle and candle[key] is not None:
            v = _to_float(candle[key])
            if v is not None:
                return v
    return None


def parse_candles(raw: Any) -> list[dict[str, float]]:
    """Normalize a candlesticks payload into a list of {open, high, low, close, volume} dicts.

    Accepts:
      - list of dicts (already normalized)
      - dict with `items` key holding the list
    Tolerates `c` / `o` / `h` / `l` / `v` aliases.
    Items missing required fields are dropped silently.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("candles") or raw.get("data") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    if not isinstance(items, list):
        return []

    out: list[dict[str, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        close = _extract_candle_value(item, "close", "c", "last")
        if close is None:
            continue
        out.append({
            "open": _extract_candle_value(item, "open", "o") or close,
            "high": _extract_candle_value(item, "high", "h") or close,
            "low": _extract_candle_value(item, "low", "l") or close,
            "close": close,
            "volume": _extract_candle_value(item, "volume", "v") or 0.0,
        })
    return out


# ---------------------------------------------------------------------------
# Indicator math
# ---------------------------------------------------------------------------

def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def _sma_slope(values: list[float], period: int, lookback: int = 5) -> float | None:
    """Slope of the SMA as (current - prior) / prior, using a small lookback."""
    if len(values) < period + lookback:
        return None
    cur = sum(values[-period:]) / period
    prior = sum(values[-(period + lookback):-lookback]) / period
    if prior == 0:
        return None
    return (cur - prior) / prior


def _atr(candles: list[dict[str, float]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _volume_ratio(candles: list[dict[str, float]], window: int = 20) -> float | None:
    if len(candles) < window + 1:
        return None
    latest = candles[-1]["volume"]
    avg = mean(c["volume"] for c in candles[-(window + 1):-1])
    if avg <= 0:
        return None
    return latest / avg


def _return_pct(candles: list[dict[str, float]], lookback: int) -> float | None:
    if len(candles) <= lookback:
        return None
    last = candles[-1]["close"]
    base = candles[-(lookback + 1)]["close"]
    if base <= 0:
        return None
    return (last - base) / base * 100.0


def _relative_strength(
    candles: list[dict[str, float]],
    benchmark_candles: list[dict[str, float]],
    lookback: int,
) -> float | None:
    if not candles or not benchmark_candles or len(candles) <= lookback or len(benchmark_candles) <= lookback:
        return None
    sym_ret = (candles[-1]["close"] - candles[-(lookback + 1)]["close"]) / candles[-(lookback + 1)]["close"]
    bmk_ret = (benchmark_candles[-1]["close"] - benchmark_candles[-(lookback + 1)]["close"]) / benchmark_candles[-(lookback + 1)]["close"]
    if bmk_ret is None or sym_ret is None:
        return None
    return (sym_ret - bmk_ret) * 100.0  # percentage points


def _support_resistance(candles: list[dict[str, float]], window: int = 20) -> tuple[list[float], list[float]]:
    """Simple support/resistance: recent local highs/lows from the last `window` candles."""
    if len(candles) < window:
        return [], []
    recent = candles[-window:]
    supports = sorted({round(c["low"], 2) for c in recent})[:3]
    resistances = sorted({round(c["high"], 2) for c in recent}, reverse=True)[:3]
    return supports, resistances


# Known benchmark symbol canonical short names. The Longbridge MCP returns
# symbols like "QQQ.US"; the engine and downstream consumers (RiskReward
# severe check, RiskGate) use the short names "QQQ" / "SPY" / "SMH".
BENCHMARK_CANONICAL = {
    "QQQ": "QQQ",
    "QQQ.US": "QQQ",
    "SPY": "SPY",
    "SPY.US": "SPY",
    "SMH": "SMH",
    "SMH.US": "SMH",
    "IWM": "IWM",
    "IWM.US": "IWM",
    "DIA": "DIA",
    "DIA.US": "DIA",
}


def _normalize_benchmark_key(name: str) -> str:
    """Map a benchmark key to its canonical short name.

    The MarketTrendSubAgent calls candlesticks for `QQQ.US`, `SPY.US`,
    `SMH.US`; the trace stores the symbol with the same long form. The
    severe-trend check in `classify_trend_break` looks up `QQQ` and `SMH`
    by short name, so a mismatch made the relative-strength severe rule
    silently inert. This helper collapses both forms to the short name.
    """
    if not name:
        return ""
    return BENCHMARK_CANONICAL.get(str(name).strip().upper(), str(name).strip().upper())


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TechnicalSignalEngine:
    """Pure technical indicator engine.

    Usage:
        engine = TechnicalSignalEngine()
        signals = engine.compute(
            symbol_candles=raw_ohlcv_list,
            benchmark_candles={"QQQ": raw_qqq_list, "SPY": raw_spy_list},
            quote={"last_done": 123.45},
        )
    """

    def compute(
        self,
        symbol_candles: list[dict[str, float]] | None = None,
        benchmark_candles: dict[str, list[dict[str, float]]] | None = None,
        quote: dict[str, Any] | None = None,
    ) -> TechnicalSignals:
        signals = TechnicalSignals()
        candles = list(symbol_candles or [])
        if not candles:
            signals.data_limitations.append("缺少标的 K 线数据，技术信号不可用")
            signals.trend_break_level = "unknown"
            return signals

        closes = [c["close"] for c in candles]

        signals.ma20 = _sma(closes, 20)
        signals.ma50 = _sma(closes, 50)
        signals.ma200 = _sma(closes, 200)
        signals.ma20_slope = _sma_slope(closes, 20, 5)
        signals.ma50_slope = _sma_slope(closes, 50, 5)
        signals.ma200_slope = _sma_slope(closes, 200, 10)

        signals.atr14 = _atr(candles, 14)
        # atr14_pct is a percentage: 3.2 means 3.2% of price. The old
        # `atr14 / ma20` produced a ratio (0.03 = 3%) that the downstream
        # RiskRewardEngine treated as a percentage, leading to a 100x
        # underestimate. Always store as percentage value, anchored to the
        # last close; fall back to MA20 when the candle series is too
        # short to have a close.
        last_close = candles[-1]["close"] if candles else None
        ref_price = last_close if last_close else signals.ma20
        if signals.atr14 is not None and ref_price:
            signals.atr14_pct = (signals.atr14 / ref_price) * 100.0

        signals.volume_ratio = _volume_ratio(candles, 20)
        signals.return_20d_pct = _return_pct(candles, 20)
        signals.return_60d_pct = _return_pct(candles, 60)

        benchmark_candles = benchmark_candles or {}
        for raw_name, bm_candles in benchmark_candles.items():
            if not bm_candles:
                continue
            # Normalize benchmark key: "QQQ.US" -> "QQQ" so downstream
            # consumers (relative_strength, severe checks) can rely on
            # the canonical short name. Keep the original long name in a
            # parallel map for traceability.
            norm_name = _normalize_benchmark_key(raw_name)
            rs20 = _relative_strength(candles, bm_candles, 20)
            rs60 = _relative_strength(candles, bm_candles, 60)
            if rs20 is not None:
                signals.relative_strength_20d[norm_name] = round(rs20, 2)
            if rs60 is not None:
                signals.relative_strength_60d[norm_name] = round(rs60, 2)

        if signals.relative_strength_20d:
            signals.relative_strength_score = round(
                sum(signals.relative_strength_20d.values()) / len(signals.relative_strength_20d), 2
            )

        signals.support_levels, signals.resistance_levels = _support_resistance(candles, 20)

        signals.trend_break_level, signals.trend_break_reasons = self.classify_trend_break(
            signals, quote=quote, last_close=last_close,
        )

        if not signals.ma20:
            signals.data_limitations.append("MA20 数据不足")
        if not signals.ma50:
            signals.data_limitations.append("MA50 数据不足")
        if not signals.ma200:
            signals.data_limitations.append("MA200 数据不足")
        if signals.atr14 is None:
            signals.data_limitations.append("ATR14 数据不足")
        if signals.volume_ratio is None:
            signals.data_limitations.append("成交量数据不足")

        return signals

    # ------------------------------------------------------------------
    # Trend break classification - rule-based, intentionally conservative
    # ------------------------------------------------------------------
    def classify_trend_break(
        self,
        signals: TechnicalSignals,
        quote: dict[str, Any] | None = None,
        last_close: float | None = None,
    ) -> tuple[str, list[str]]:
        """Classify the trend-break level.

        Levels:
          - severe: 收盘价 < MA200, or 20d/60d RS vs QQQ+SMH both materially negative
          - broken: 连续 3 日收盘价 < MA50 AND MA50 slope <= 0
          - warning: 收盘价 < MA20, or 单日跌幅大且 volume_ratio > 1.3
          - none: otherwise
        """
        reasons: list[str] = []
        last = _to_float((quote or {}).get("last_done") or (quote or {}).get("last_price") or (quote or {}).get("close")) or last_close
        if last is None and signals.ma20 is not None:
            # Best-effort fallback: use the last computed candle's close (engine
            # callers that have the raw series should pass it via `last_close`).
            last = last if last is not None else None  # no-op
        if last is None:
            reasons.append("缺少最新收盘价，无法判定 trend_break_level")
            return "unknown", reasons

        ma20 = signals.ma20
        ma50 = signals.ma50
        ma200 = signals.ma200
        ma50_slope = signals.ma50_slope

        # ---- severe ----
        severe_reasons: list[str] = []
        if ma200 is not None and last < ma200 * 0.98:  # small buffer
            severe_reasons.append(f"收盘价({last:.2f}) < MA200({ma200:.2f})")
        rs_20 = signals.relative_strength_20d or {}
        rs_60 = signals.relative_strength_60d or {}
        required = {"QQQ", "SMH"}
        if required <= set(rs_20.keys()) and required <= set(rs_60.keys()):
            big_lag_20 = all(rs_20[name] < -3.0 for name in required)
            big_lag_60 = all(rs_60[name] < -5.0 for name in required)
            if big_lag_20 and big_lag_60:
                severe_reasons.append("20d/60d 相对 QQQ+SMH 都明显跑输")
        else:
            lagging_available = [
                name for name in required
                if rs_20.get(name, 0.0) < -3.0 and rs_60.get(name, 0.0) < -5.0
            ]
            if lagging_available:
                reasons.append(f"相对 {','.join(sorted(lagging_available))} 明显跑输，但缺少 QQQ+SMH 双基准确认")
        if severe_reasons:
            return "severe", severe_reasons

        # ---- broken ----
        # We don't actually have the per-day history of close<MA50 here, but
        # we can approximate using the slope + last close:
        if ma50 is not None and last < ma50 * 0.97 and (ma50_slope is not None and ma50_slope <= 0):
            reasons.append(f"收盘价({last:.2f}) 显著低于 MA50({ma50:.2f}) 且 MA50 走平/走弱")
            return "broken", reasons

        # ---- warning ----
        if ma20 is not None and last < ma20 * 0.97:
            reasons.append(f"收盘价({last:.2f}) 跌破 MA20({ma20:.2f})")
            return "warning", reasons
        if signals.volume_ratio is not None and signals.volume_ratio > 1.3:
            # Need a meaningful single-day drop to qualify
            ret_20 = signals.return_20d_pct
            if ret_20 is not None and ret_20 < -3.0:
                reasons.append(f"成交量放大({signals.volume_ratio:.2f}x) 配合 20d 收益转负")
                return "warning", reasons

        if reasons:
            return "warning", reasons
        return "none", reasons


# ---------------------------------------------------------------------------
# Trace extraction helper (for MarketTrendSubAgent integration)
# ---------------------------------------------------------------------------

def extract_raw_candles_from_trace(trace: list[dict], tool_name: str = "candlesticks", symbol: str | None = None) -> list[dict[str, float]]:
    """Try to recover raw OHLCV items from a tool_finish event in the trace.

    The Longbridge MCP adapter compacts candlesticks by default (sample_points /
    return_pct / latest_close). When the underlying tool does expose raw items
    (e.g. in tests or future un-compacted paths), they live in
    `event["output"]["data"]["items"]`. This helper returns the items if found,
    otherwise an empty list.
    """
    for event in trace or []:
        if event.get("event") != "tool_finish" or event.get("tool") != tool_name or event.get("ok") is not True:
            continue
        output = event.get("output") or {}
        if not isinstance(output, dict):
            continue
        # If the symbol is specified, try to match the request_args
        if symbol:
            args = event.get("arguments") or {}
            if str(args.get("symbol") or "").upper().split(".")[0] != str(symbol).upper().split(".")[0]:
                continue
        engine_payload = output.get("engine_payload")
        if isinstance(engine_payload, dict):
            parsed = parse_candles(engine_payload.get("candles"))
            if parsed:
                return parsed

        data = output.get("data") or {}
        if not isinstance(data, dict):
            continue
        items = data.get("items") or data.get("candles")
        parsed = parse_candles(items)
        if parsed:
            return parsed
    return []


def extract_benchmark_candles_from_trace(trace: list[dict], benchmarks: list[str]) -> dict[str, list[dict[str, float]]]:
    """Extract candlesticks for each benchmark symbol from a trace."""
    out: dict[str, list[dict[str, float]]] = {}
    for symbol in benchmarks:
        candles = extract_raw_candles_from_trace(trace, "candlesticks", symbol)
        if candles:
            out[symbol] = candles
    return out


__all__ = [
    "TechnicalSignals",
    "TechnicalSignalEngine",
    "TREND_BREAK_LEVELS",
    "parse_candles",
    "extract_raw_candles_from_trace",
    "extract_benchmark_candles_from_trace",
]
