"""Fundamental Change Engine - deterministic detection of material fundamental
deterioration vs the configured InvestmentThesis.

This engine is intentionally rule-based and does NOT call LLM / MCP. It
accepts already-fetched financial / valuation / segment / rating / forecast
data and produces a `FundamentalChangeResult` with:

- fundamental_status: green / yellow / orange / red / unknown
- thesis_broken: bool
- change_signals: list[str]
- positive_signals / negative_signals
- revenue_growth_trend / margin_trend / cash_flow_trend / guidance_change
- segment_growth_notes
- evidence / data_limitations

Per-symbol attention is controlled by the `InvestmentThesis.core_thesis` and
`InvestmentThesis.sell_triggers`; the engine text-matches the configured
sell_triggers against observed change_signals to decide if the thesis is
broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FUNDAMENTAL_STATUSES = ("green", "yellow", "orange", "red", "unknown")

# Mapping of change signal -> weight. Higher weight pushes the fundamental
# status toward red. Positive signals are subtracted.
_SIGNAL_WEIGHTS: dict[str, int] = {
    # Negative
    "revenue_growth_slowdown": 2,
    "margin_compression": 2,
    "cash_flow_deterioration": 2,
    "guidance_cut": 3,
    "segment_growth_failure": 2,
    "rating_downgrade": 1,
    "forecast_eps_cut": 2,
    # Positive
    "revenue_growth_acceleration": -2,
    "margin_expansion": -2,
    "guidance_raise": -3,
    "rating_upgrade": -1,
    "forecast_eps_raise": -2,
}


@dataclass
class FundamentalChangeResult:
    fundamental_status: str = "unknown"
    thesis_broken: bool = False
    change_signals: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    revenue_growth_trend: str | None = None
    margin_trend: str | None = None
    cash_flow_trend: str | None = None
    guidance_change: str | None = None
    segment_growth_notes: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fundamental_status": self.fundamental_status,
            "thesis_broken": self.thesis_broken,
            "change_signals": list(self.change_signals),
            "positive_signals": list(self.positive_signals),
            "negative_signals": list(self.negative_signals),
            "revenue_growth_trend": self.revenue_growth_trend,
            "margin_trend": self.margin_trend,
            "cash_flow_trend": self.cash_flow_trend,
            "guidance_change": self.guidance_change,
            "segment_growth_notes": list(self.segment_growth_notes),
            "evidence": list(self.evidence),
            "data_limitations": list(self.data_limitations),
        }


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _extract_quarterly_series(reports: list[dict], field_name: str) -> list[float]:
    """Pull a numeric field from a list of financial reports in chronological order.

    Each report is expected to carry either:
      - the field at top level (e.g. {"revenue": 1000.0})
      - or under nested keys like {"data": {...}} / {"summary": {...}}
    """
    series: list[float] = []
    for rep in reports or []:
        if not isinstance(rep, dict):
            continue
        candidates = [rep]
        for nested_key in ("data", "summary", "metrics", "financials"):
            nested = rep.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        value: Any = None
        for cand in candidates:
            if field_name in cand and cand[field_name] is not None:
                value = cand[field_name]
                break
            # Common aliases
            aliases = {
                "revenue": ["total_revenue", "revenues", "sales", "net_revenue"],
                "gross_margin": ["gross_margin_pct", "gross_margin_percent"],
                "operating_margin": ["op_margin", "operating_margin_pct"],
                "operating_cash_flow": ["cfo", "ocf", "cash_from_operations"],
                "free_cash_flow": ["fcf"],
            }
            for alias in aliases.get(field_name, []):
                if alias in cand and cand[alias] is not None:
                    value = cand[alias]
                    break
            if value is not None:
                break
        f = _safe_float(value)
        if f is not None:
            series.append(f)
    return series


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FundamentalChangeEngine:
    """Deterministic change detector.

    Usage:
        engine = FundamentalChangeEngine()
        result = engine.evaluate(
            financial_reports=[...],
            valuation={...},
            business_segments=[...],
            institution_rating={...},
            forecast_eps={...},
            investment_thesis=thesis_or_dict_or_none,
        )
    """

    def evaluate(
        self,
        financial_reports: list[dict] | None = None,
        valuation: dict | None = None,
        business_segments: list[dict] | list | dict | None = None,
        institution_rating: dict | None = None,
        forecast_eps: dict | None = None,
        investment_thesis: Any = None,
    ) -> FundamentalChangeResult:
        result = FundamentalChangeResult()

        # ---- 1. revenue growth trend ----
        revenue_series = _extract_quarterly_series(financial_reports or [], "revenue")
        if len(revenue_series) >= 3:
            # Use the last 4 data points (or fewer if not available) to compute QoQ
            window = revenue_series[-min(4, len(revenue_series)):]
            deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
            positives = sum(1 for d in deltas if d > 0)
            negatives = sum(1 for d in deltas if d < 0)
            if negatives >= 2 and positives == 0:
                result.revenue_growth_trend = "slowing"
                result.change_signals.append("revenue_growth_slowdown")
                result.negative_signals.append("revenue_growth_slowdown")
                result.evidence.append({"signal": "revenue_growth_slowdown", "window": window})
            elif positives >= 2 and negatives == 0:
                result.revenue_growth_trend = "accelerating"
                result.positive_signals.append("revenue_growth_acceleration")
                result.evidence.append({"signal": "revenue_growth_acceleration", "window": window})
            else:
                result.revenue_growth_trend = "stable"
        else:
            result.data_limitations.append("revenue 系列数据不足 (<3 季度)")

        # ---- 2. margin trend ----
        gm_series = _extract_quarterly_series(financial_reports or [], "gross_margin")
        om_series = _extract_quarterly_series(financial_reports or [], "operating_margin")
        margin_series = gm_series or om_series
        if len(margin_series) >= 3:
            window = margin_series[-min(4, len(margin_series)):]
            deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
            compressions = sum(1 for d in deltas if d < 0)
            expansions = sum(1 for d in deltas if d > 0)
            if compressions >= 2 and expansions == 0:
                result.margin_trend = "compressing"
                result.change_signals.append("margin_compression")
                result.negative_signals.append("margin_compression")
                result.evidence.append({"signal": "margin_compression", "window": window})
            elif expansions >= 2 and compressions == 0:
                result.margin_trend = "expanding"
                result.positive_signals.append("margin_expansion")
            else:
                result.margin_trend = "stable"
        else:
            result.data_limitations.append("margin 系列数据不足")

        # ---- 3. cash flow trend ----
        cfo_series = _extract_quarterly_series(financial_reports or [], "operating_cash_flow")
        fcf_series = _extract_quarterly_series(financial_reports or [], "free_cash_flow")
        cf_series = cfo_series or fcf_series
        if len(cf_series) >= 3:
            window = cf_series[-min(4, len(cf_series)):]
            deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
            declines = sum(1 for d in deltas if d < 0)
            improvements = sum(1 for d in deltas if d > 0)
            if declines >= 2 and improvements == 0:
                result.cash_flow_trend = "deteriorating"
                result.change_signals.append("cash_flow_deterioration")
                result.negative_signals.append("cash_flow_deterioration")
                result.evidence.append({"signal": "cash_flow_deterioration", "window": window})
            elif window[-1] < 0:
                result.cash_flow_trend = "negative"
                result.change_signals.append("cash_flow_deterioration")
                result.negative_signals.append("cash_flow_deterioration")
                result.evidence.append({"signal": "free_cash_flow_negative", "last": window[-1]})
            elif improvements >= 2 and declines == 0:
                result.cash_flow_trend = "improving"
            else:
                result.cash_flow_trend = "stable"
        else:
            result.data_limitations.append("现金流系列数据不足")

        # ---- 4. guidance change ----
        guidance_text = self._extract_guidance_text(financial_reports, institution_rating, forecast_eps)
        if guidance_text:
            lowered = guidance_text.lower()
            if any(kw in guidance_text for kw in ("下调", "指引下调", "cut", "lowered", "lowered guidance", "guidance cut", "below")):
                result.guidance_change = "cut"
                result.change_signals.append("guidance_cut")
                result.negative_signals.append("guidance_cut")
                result.evidence.append({"signal": "guidance_cut", "excerpt": guidance_text[:200]})
            elif any(kw in guidance_text for kw in ("上调", "指引上调", "raised", "raise", "above", "beat")):
                result.guidance_change = "raised"
                result.positive_signals.append("guidance_raise")
                result.evidence.append({"signal": "guidance_raise", "excerpt": guidance_text[:200]})
            else:
                result.guidance_change = "maintained"
        else:
            result.data_limitations.append("无 guidance / forecast 数据")

        # ---- 5. segment growth ----
        seg_notes = self._evaluate_segments(business_segments)
        result.segment_growth_notes = seg_notes
        if any("放缓" in n or "转负" in n or "下滑" in n for n in seg_notes):
            result.change_signals.append("segment_growth_failure")
            result.negative_signals.append("segment_growth_failure")
            result.evidence.append({"signal": "segment_growth_failure", "notes": seg_notes})

        # ---- 6. rating / forecast change ----
        if isinstance(institution_rating, dict):
            rating_change = str(institution_rating.get("recent_change") or "").lower()
            if "downgrade" in rating_change or "降级" in rating_change:
                result.change_signals.append("rating_downgrade")
                result.negative_signals.append("rating_downgrade")
            elif "upgrade" in rating_change or "上调" in rating_change:
                result.positive_signals.append("rating_upgrade")
        if isinstance(forecast_eps, dict):
            eps_trend = str(forecast_eps.get("trend") or "").lower()
            if "cut" in eps_trend or "下调" in eps_trend:
                result.change_signals.append("forecast_eps_cut")
                result.negative_signals.append("forecast_eps_cut")
            elif "raise" in eps_trend or "上调" in eps_trend:
                result.positive_signals.append("forecast_eps_raise")

        # ---- aggregate fundamental_status ----
        result.fundamental_status = self._aggregate_status(result)

        # ---- 7. thesis_broken check against configured sell_triggers ----
        result.thesis_broken, broken_rules = self._check_thesis_broken(
            change_signals=result.change_signals,
            guidance_change=result.guidance_change,
            investment_thesis=investment_thesis,
        )
        if result.thesis_broken:
            # Red overrides any earlier aggregate
            result.fundamental_status = "red"
            result.evidence.append({"signal": "thesis_broken", "rules": broken_rules})

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _extract_guidance_text(
        self,
        financial_reports: list[dict] | None,
        institution_rating: dict | None,
        forecast_eps: dict | None,
    ) -> str:
        chunks: list[str] = []
        for rep in financial_reports or []:
            if not isinstance(rep, dict):
                continue
            for key in ("guidance", "guidance_text", "outlook", "summary_text", "summary", "remarks"):
                val = rep.get(key)
                if isinstance(val, str) and val.strip():
                    chunks.append(val)
        if isinstance(institution_rating, dict):
            for key in ("recent_change", "consensus_note", "summary"):
                val = institution_rating.get(key)
                if isinstance(val, str) and val.strip():
                    chunks.append(val)
        if isinstance(forecast_eps, dict):
            for key in ("trend_note", "summary", "consensus_note"):
                val = forecast_eps.get(key)
                if isinstance(val, str) and val.strip():
                    chunks.append(val)
        return " ".join(chunks)[:1000]

    def _evaluate_segments(self, segments: Any) -> list[str]:
        notes: list[str] = []
        if not segments:
            return notes
        items = segments if isinstance(segments, list) else [segments]
        for seg in items:
            if not isinstance(seg, dict):
                continue
            name = seg.get("name") or seg.get("segment") or "segment"
            growth = _safe_float(seg.get("yoy_growth") or seg.get("growth") or seg.get("growth_pct"))
            if growth is None:
                continue
            if growth < 0:
                notes.append(f"{name} 同比转负({growth:.1f}%)")
            elif growth < 5:
                notes.append(f"{name} 增速放缓({growth:.1f}%)")
        return notes

    def _aggregate_status(self, result: FundamentalChangeResult) -> str:
        """Aggregate the change signals into a fundamental status.

        Score = sum of signal weights. Thresholds:
          <= -3: green
          -2..2: yellow
          3..5: orange
          >= 6: red
        No data: unknown
        """
        if not result.change_signals and not result.positive_signals:
            return "unknown"

        score = 0
        for sig in result.change_signals:
            score += _SIGNAL_WEIGHTS.get(sig, 1)
        for sig in result.positive_signals:
            score += _SIGNAL_WEIGHTS.get(sig, -1)

        if score <= -3:
            return "green"
        if score >= 6:
            return "red"
        if score >= 3:
            return "orange"
        return "yellow"

    def _check_thesis_broken(
        self,
        change_signals: list[str],
        guidance_change: str | None,
        investment_thesis: Any,
    ) -> tuple[bool, list[str]]:
        """Return (thesis_broken, matched_rule_strings)."""
        sell_triggers: list[str] = []
        if investment_thesis is None:
            return False, []
        # Accept either a dataclass or a dict
        if hasattr(investment_thesis, "sell_triggers"):
            sell_triggers = list(getattr(investment_thesis, "sell_triggers") or [])
        elif isinstance(investment_thesis, dict):
            sell_triggers = list(investment_thesis.get("sell_triggers") or [])
        if not sell_triggers:
            return False, []

        matched: list[str] = []
        signal_text = " ".join(change_signals) + " " + (guidance_change or "")
        # Naive keyword matching: if a sell_trigger contains a token that
        # appears in any change_signal, the rule is considered hit.
        token_map = {
            "revenue_growth_slowdown": ["收入", "增长", "growth", "revenue"],
            "margin_compression": ["毛利", "利润率", "margin"],
            "cash_flow_deterioration": ["现金流", "cash"],
            "guidance_cut": ["指引", "guidance", "指引下调"],
            "segment_growth_failure": ["分部", "segment"],
        }
        tokens_matched: set[str] = set()
        for sig in change_signals:
            for token in token_map.get(sig, [sig]):
                tokens_matched.add(token)
        for rule in sell_triggers:
            rule_low = rule.lower()
            for token in tokens_matched:
                if token.lower() in rule_low:
                    matched.append(rule)
                    break
        return (len(matched) > 0), matched


__all__ = [
    "FUNDAMENTAL_STATUSES",
    "FundamentalChangeResult",
    "FundamentalChangeEngine",
]
