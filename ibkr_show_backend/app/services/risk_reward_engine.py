"""Risk Reward Engine - deterministic estimation of upside / downside / R-multiple.

This engine intentionally does NOT use the user's cost basis as a downside
proxy. Instead it derives downside from:

- distance to MA200
- distance to recent support level
- 2.5 * ATR14 (volatility)
- fundamental drawdown estimate (orange/red -> larger drawdown)

And upside from:

- analyst target price distance
- distance to resistance
- a scenario growth upside (PE re-rate + revenue growth)

The result is a `RiskRewardEstimate` with explicit upside/downside scenarios,
R-multiples, and action guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CONFIDENCE_LEVELS = ("high", "medium", "low", "unknown")


@dataclass
class RiskRewardEstimate:
    upside_potential_pct: float | None = None
    downside_risk_pct: float | None = None
    reward_risk_ratio: float | None = None
    downside_scenarios: list[dict] = field(default_factory=list)
    upside_scenarios: list[dict] = field(default_factory=list)
    stop_add_level: float | None = None
    invalidation_level: float | None = None
    trim_level: float | None = None
    wait_for_pullback: bool = False
    wait_for_pullback_pct: float | None = None
    pullback_entry_level: float | None = None
    position_size_label: str = "unknown"
    max_position_pct: float = 0.05
    confidence: str = "unknown"
    data_limitations: list[str] = field(default_factory=list)
    action_guidance: str = "wait"  # hold_no_add / wait / add_on_pullback / add_right_side / avoid / reduce_now

    def to_dict(self) -> dict[str, Any]:
        return {
            "upside_potential_pct": self.upside_potential_pct,
            "downside_risk_pct": self.downside_risk_pct,
            "reward_risk_ratio": self.reward_risk_ratio,
            "downside_scenarios": list(self.downside_scenarios),
            "upside_scenarios": list(self.upside_scenarios),
            "stop_add_level": self.stop_add_level,
            "invalidation_level": self.invalidation_level,
            "trim_level": self.trim_level,
            "wait_for_pullback": self.wait_for_pullback,
            "wait_for_pullback_pct": self.wait_for_pullback_pct,
            "pullback_entry_level": self.pullback_entry_level,
            "position_size_label": self.position_size_label,
            "max_position_pct": self.max_position_pct,
            "confidence": self.confidence,
            "data_limitations": list(self.data_limitations),
            "action_guidance": self.action_guidance,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _pct_change(from_value: float | None, to_value: float | None) -> float | None:
    """Compute percentage change from `from_value` to `to_value` (signed)."""
    if from_value is None or to_value is None or from_value == 0:
        return None
    return (to_value - from_value) / from_value * 100.0


def _abs_pct(price: float | None, reference: float | None) -> float | None:
    """Absolute percentage distance from `price` to `reference` (always positive)."""
    p = _pct_change(reference, price)
    if p is None:
        return None
    return abs(p)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RiskRewardEngine:
    """Deterministic risk/reward estimator.

    Usage:
        engine = RiskRewardEngine()
        est = engine.estimate(
            snapshot=..., account_fit=..., market_trend=...,
            fundamental=..., event=..., investment_thesis=...,
            technical_signals=signals_dict,
            last_close=150.0,
        )
    """

    def estimate(
        self,
        *,
        snapshot: Any = None,
        account_fit: Any = None,
        market_trend: Any = None,
        fundamental: Any = None,
        event: Any = None,
        investment_thesis: Any = None,
        technical_signals: dict[str, Any] | None = None,
        last_close: float | None = None,
    ) -> RiskRewardEstimate:
        est = RiskRewardEstimate()
        signals = technical_signals or {}

        # Resolve last close: prefer quote-like, then snapshot.current_price,
        # then signals.ma20, then last candle of any list.
        last = (
            _safe_float(last_close)
            or _safe_float(getattr(snapshot, "current_price", None))
            or _safe_float(signals.get("ma20"))
        )

        # --- DOWNSIDE scenarios ---
        # Each scenario is a dict with {scenario, distance_pct, ref_price}.
        downside_candidates: list[tuple[str, float]] = []

        # 1. distance to MA200
        ma200 = _safe_float(signals.get("ma200"))
        if last is not None and ma200 is not None and ma200 > 0:
            distance = (ma200 - last) / last * 100.0
            # only count if MA200 is below price (i.e. downside if we retest)
            if distance < 0:
                downside_candidates.append(("ma200_distance", abs(distance)))
                est.downside_scenarios.append({
                    "scenario": "ma200_distance",
                    "distance_pct": abs(distance),
                    "ref_price": ma200,
                })

        # 2. distance to recent support
        support_levels = signals.get("support_levels") or []
        if last is not None and support_levels and isinstance(support_levels, list):
            # pick the nearest support that is below the price
            valid = [s for s in support_levels if isinstance(s, (int, float)) and s < last]
            if valid:
                nearest_support = max(valid)  # the closest support still below price
                distance = (last - nearest_support) / last * 100.0
                if distance > 0:
                    downside_candidates.append(("support_distance", distance))
                    est.downside_scenarios.append({
                        "scenario": "support_distance",
                        "distance_pct": distance,
                        "ref_price": nearest_support,
                    })

        # 3. 2.5 * ATR14
        atr14 = _safe_float(signals.get("atr14"))
        atr14_pct = _safe_float(signals.get("atr14_pct"))
        if atr14_pct is None and atr14 is not None and last is not None and last > 0:
            atr14_pct = (atr14 / last) * 100.0
        if atr14_pct is not None:
            atr_risk = 2.5 * atr14_pct
            downside_candidates.append(("atr_2_5x", atr_risk))
            est.downside_scenarios.append({
                "scenario": "atr_2_5x",
                "distance_pct": atr_risk,
                "ref_price": last - atr14 if last is not None and atr14 is not None else None,
            })

        # 4. fundamental drawdown estimate
        fundamental_status = (getattr(fundamental, "fundamental_status", None) or "unknown") if fundamental else "unknown"
        thesis_broken = bool(getattr(fundamental, "thesis_broken", False)) if fundamental else False
        if fundamental_status == "red" or thesis_broken:
            fundamental_drawdown = 30.0
        elif fundamental_status == "orange":
            fundamental_drawdown = 20.0
        elif fundamental_status == "yellow":
            fundamental_drawdown = 10.0
        else:
            fundamental_drawdown = 0.0
        if fundamental_drawdown > 0:
            downside_candidates.append(("fundamental_drawdown", fundamental_drawdown))
            est.downside_scenarios.append({
                "scenario": "fundamental_drawdown",
                "distance_pct": fundamental_drawdown,
                "ref_price": None,
            })

        # 5. high volatility penalty for extreme risk_class
        risk_class = (investment_thesis.risk_class if investment_thesis and hasattr(investment_thesis, "risk_class")
                      else (investment_thesis.get("risk_class") if isinstance(investment_thesis, dict) else "unknown"))
        if risk_class == "extreme":
            downside_candidates.append(("extreme_risk_penalty", 15.0))
            est.downside_scenarios.append({
                "scenario": "extreme_risk_penalty",
                "distance_pct": 15.0,
                "ref_price": None,
            })

        if downside_candidates:
            est.downside_risk_pct = max(v for _, v in downside_candidates)
        else:
            est.data_limitations.append("下行风险参数不足 (缺 MA200 / 支撑 / ATR / 基本面)")

        # --- UPSIDE scenarios ---
        upside_candidates: list[tuple[str, float]] = []

        # 1. analyst target price
        target_price = _safe_float(getattr(fundamental, "target_price", None)) if fundamental else None
        if last is not None and target_price is not None and last > 0 and target_price > last:
            up = (target_price - last) / last * 100.0
            upside_candidates.append(("target_price", up))
            est.upside_scenarios.append({
                "scenario": "target_price",
                "distance_pct": up,
                "ref_price": target_price,
            })

        # 2. distance to resistance
        resistance_levels = signals.get("resistance_levels") or []
        if last is not None and resistance_levels and isinstance(resistance_levels, list):
            valid = [r for r in resistance_levels if isinstance(r, (int, float)) and r > last]
            for r in sorted(valid):
                up = (r - last) / last * 100.0
                if up > 0:
                    upside_candidates.append(("resistance", up))
                    est.upside_scenarios.append({
                        "scenario": "resistance",
                        "distance_pct": up,
                        "ref_price": r,
                    })

        # 3. scenario growth upside (PE re-rate + revenue growth)
        # Use Forward PE if available, otherwise PE TTM. Conservative.
        if fundamental is not None and last is not None and last > 0:
            fwd_pe = _safe_float(getattr(fundamental, "forward_pe", None))
            pe = _safe_float(getattr(fundamental, "pe_ttm", None))
            ref_pe = fwd_pe or pe
            if ref_pe is not None and ref_pe > 0:
                # Assume market can re-rate by 10% if fundamentals are green/yellow
                re_rate = 0.0
                if fundamental_status in {"green", "yellow"}:
                    re_rate = 10.0
                scenario_up = re_rate
                # Add a small revenue growth component (proxy)
                growth_text = str(getattr(fundamental, "revenue_growth_summary", "") or "")
                if "%" in growth_text:
                    try:
                        # crude parse "20%" -> 20
                        token = growth_text.split("%")[0].strip().split(" ")[-1]
                        g = float(token)
                        if 0 < g < 200:
                            scenario_up += min(g, 20.0)
                    except (ValueError, IndexError):
                        pass
                if scenario_up > 0:
                    upside_candidates.append(("scenario_growth", scenario_up))
                    est.upside_scenarios.append({
                        "scenario": "scenario_growth",
                        "distance_pct": scenario_up,
                        "ref_price": None,
                    })

        if upside_candidates:
            # Use the conservative median / min positive candidate
            positive = sorted(v for _, v in upside_candidates if v > 0)
            if positive:
                est.upside_potential_pct = positive[0] if len(positive) == 1 else positive[len(positive) // 2]
        else:
            est.data_limitations.append("上行空间参数不足 (缺 target_price / resistance / scenario growth)")

        # --- REWARD / RISK ratio ---
        if est.upside_potential_pct is not None and est.downside_risk_pct and est.downside_risk_pct > 0:
            est.reward_risk_ratio = round(est.upside_potential_pct / est.downside_risk_pct, 2)

        # --- POSITION SIZE / ACTION GUIDANCE ---
        est.max_position_pct = self._compute_max_position_pct(investment_thesis)
        est.position_size_label = self._size_label(est.max_position_pct)

        # Adjust based on current position
        current_pct = _safe_float(getattr(snapshot, "position_pct", None)) if snapshot else None
        trend_break_level = (getattr(market_trend, "trend_break_level", None) or "unknown") if market_trend else "unknown"
        est.wait_for_pullback = trend_break_level in {"warning", "broken", "severe"}

        # Compute action_guidance from R-multiple and trend/fundamental
        est.action_guidance = self._action_guidance(
            ratio=est.reward_risk_ratio,
            trend_break_level=trend_break_level,
            fundamental_status=fundamental_status,
            thesis_broken=thesis_broken,
            is_holding=bool(getattr(snapshot, "is_holding", False)) if snapshot else False,
        )

        # Trim/invalidation levels
        if last is not None and est.downside_risk_pct is not None:
            est.invalidation_level = round(last * (1 - est.downside_risk_pct / 100.0), 2)
            est.stop_add_level = round(last * (1 - est.downside_risk_pct / 200.0), 2)
            est.trim_level = round(last * (1 + max(est.upside_potential_pct or 0, 5.0) / 200.0), 2)
            pullback_pct = min(max(est.downside_risk_pct / 2.0, 3.0), 10.0)
            est.wait_for_pullback_pct = round(pullback_pct, 2)
            est.pullback_entry_level = round(last * (1 - pullback_pct / 100.0), 2)

        # Confidence
        est.confidence = self._compute_confidence(
            est, fundamental_status, trend_break_level, has_quote=last is not None,
        )

        return est

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _compute_max_position_pct(self, investment_thesis: Any) -> float:
        """Resolve max_position_pct from the thesis, capped by risk_class."""
        if investment_thesis is None:
            return 0.05
        if hasattr(investment_thesis, "max_position_pct"):
            base = float(investment_thesis.max_position_pct or 0.05)
            risk_class = str(getattr(investment_thesis, "risk_class", "unknown") or "unknown")
        elif isinstance(investment_thesis, dict):
            base = float(investment_thesis.get("max_position_pct") or 0.05)
            risk_class = str(investment_thesis.get("risk_class") or "unknown")
        else:
            return 0.05
        # Cap by risk_class
        cap_map = {
            "low": 0.30,
            "medium": 0.25,
            "medium_high": 0.20,
            "high_growth": 0.30,
            "extreme": 0.10,
            "unknown": 0.10,
        }
        cap = cap_map.get(risk_class, 0.10)
        return min(base, cap)

    def _size_label(self, max_pct: float) -> str:
        if max_pct <= 0.0:
            return "none"
        if max_pct < 0.03:
            return "very_small"
        if max_pct < 0.08:
            return "small"
        if max_pct < 0.15:
            return "medium"
        if max_pct < 0.25:
            return "large"
        return "very_large"

    def _action_guidance(
        self,
        ratio: float | None,
        trend_break_level: str,
        fundamental_status: str,
        thesis_broken: bool,
        is_holding: bool,
    ) -> str:
        # Strongest first: thesis broken / fundamental red
        if thesis_broken or fundamental_status == "red":
            return "reduce_now" if is_holding else "avoid"

        # Trend broken
        if trend_break_level == "severe":
            return "reduce_now" if is_holding else "avoid"
        if trend_break_level == "broken":
            return "hold_no_add" if is_holding else "wait"

        # R-multiple rules
        if ratio is None:
            return "wait"
        if ratio < 1.0:
            return "hold_no_add" if is_holding else "wait"
        if ratio < 1.5:
            return "hold_no_add" if is_holding else "wait"
        if ratio < 2.0:
            return "add_on_pullback"
        # ratio >= 2.0
        if trend_break_level == "warning":
            return "add_on_pullback"
        return "add_right_side"

    def _compute_confidence(
        self,
        est: RiskRewardEstimate,
        fundamental_status: str,
        trend_break_level: str,
        has_quote: bool,
    ) -> str:
        score = 0
        if est.upside_potential_pct is not None:
            score += 1
        if est.downside_risk_pct is not None:
            score += 1
        if est.reward_risk_ratio is not None:
            score += 1
        if fundamental_status in {"green", "yellow", "orange", "red"}:
            score += 1
        if trend_break_level in {"none", "warning", "broken", "severe"}:
            score += 1
        if has_quote:
            score += 1
        if score >= 5:
            return "high"
        if score >= 3:
            return "medium"
        if score >= 1:
            return "low"
        return "unknown"


__all__ = [
    "RiskRewardEstimate",
    "RiskRewardEngine",
    "CONFIDENCE_LEVELS",
]
