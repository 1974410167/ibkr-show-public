"""Compatibility RiskRewardCard builder derived from TradePlanCard.

The graph no longer runs an independent risk_reward LLM node. This module keeps
the existing Composer and Risk Gate contract stable by deriving a RiskRewardCard
from trade_plan.risk_reward_assessment without calling tools or LLMs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.trade_decision_cards import (
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketEventContextCard,
    MarketTrendCard,
    RiskRewardCard,
    TradePlanCard,
    build_fallback_risk_reward_card,
)


def build_risk_reward_card_from_trade_plan(
    symbol: str,
    decision_type: str,
    trade_plan_card: TradePlanCard,
    account_fit_card: AccountFitCard | None = None,
    market_trend_card: MarketTrendCard | None = None,
    fundamental_valuation_card: FundamentalValuationCard | None = None,
    event_catalyst_card: EventCatalystCard | None = None,
    market_event_context_card: MarketEventContextCard | None = None,
) -> RiskRewardCard:
    try:
        assessment = trade_plan_card.risk_reward_assessment
        if not isinstance(assessment, dict):
            assessment = {}

        ratio = _to_float(assessment.get("reward_risk_ratio"))
        entry_quality = str(assessment.get("entry_quality") or "unknown").lower()
        score = _score_from_ratio_or_quality(ratio, entry_quality)
        upside = _clean_text(assessment.get("upside_scenario"))
        downside = _clean_text(assessment.get("downside_scenario"))
        event_window = str(assessment.get("event_risk_window") or "").lower()
        summary_parts = [part for part in (upside, downside) if part]
        summary = "；".join(summary_parts) or _clean_text(trade_plan_card.summary)
        if not summary:
            summary = "交易计划 Agent 已生成风险收益兼容卡。"
        summary = f"风险收益评估来自交易计划 Agent：{summary}"

        data_limitations = _dedupe(_list(getattr(trade_plan_card, "data_limitations", [])) + ["risk_reward_derived_from_trade_plan"])
        evidence_quality = _evidence_quality(trade_plan_card, entry_quality)
        key_risks = _dedupe(
            ([downside] if downside else [])
            + _event_risk_notes(event_window)
            + _list(getattr(trade_plan_card, "invalidation_conditions", []), 4)
        )
        key_opportunities = _dedupe(
            ([upside] if upside else [])
            + _list(getattr(trade_plan_card, "execution_conditions", []), 4)
        )

        return RiskRewardCard(
            card_type="risk_reward",
            symbol=symbol,
            decision_type=decision_type,
            summary=summary[:1200],
            score=score,
            max_score=15,
            stance=_stance_from_asset_stance(getattr(trade_plan_card, "asset_stance", None)),
            key_points=[],
            risks=key_risks,
            opportunities=key_opportunities,
            evidence=[],
            data_limitations=data_limitations,
            evidence_quality=evidence_quality,
            source_tools=[],
            tool_calls=[],
            data_quality={"source": "trade_plan", "standalone_node_enabled": False},
            missing_fields=[],
            created_at=datetime.now(timezone.utc).isoformat(),
            upside_potential_pct=_to_float(assessment.get("upside_potential_pct")),
            downside_risk_pct=_to_float(assessment.get("downside_risk_pct")),
            reward_risk_ratio=ratio,
            max_position_pct=_to_float(getattr(trade_plan_card, "max_position_pct", None)),
            wait_for_pullback=bool(assessment.get("wait_for_pullback", False)),
            wait_for_pullback_pct=_to_float(assessment.get("wait_for_pullback_pct")),
            pullback_entry_level=_to_float(assessment.get("pullback_entry_level")),
            action_guidance=str(getattr(trade_plan_card, "portfolio_action", "") or ""),
            position_size_label=_position_size_label(_to_float(getattr(trade_plan_card, "target_position_pct", None))),
            key_risks=key_risks,
            key_opportunities=key_opportunities,
            risk_assessment_reason=_clean_text(getattr(trade_plan_card, "summary", "")),
            downside_scenarios=[],
            upside_scenarios=[],
            stop_add_level=None,
            invalidation_level=_to_float(assessment.get("invalidation_level")),
            trim_level=_to_float(assessment.get("trim_level")),
            risk_reward_confidence=evidence_quality,
            risk_reward_thesis_broken=str(getattr(trade_plan_card, "portfolio_action", "")) == "sell_thesis_broken",
        )
    except Exception as exc:
        return build_fallback_risk_reward_card(symbol, decision_type, f"trade_plan_compat_failed: {str(exc)[:120]}")


def _score_from_ratio_or_quality(ratio: float | None, entry_quality: str) -> int:
    if ratio is not None and ratio >= 0:
        if ratio < 1.0:
            return max(0, int(ratio * 6))
        if ratio < 2.0:
            return min(10, int(6 + (ratio - 1.0) * 4))
        if ratio < 3.0:
            return min(13, int(11 + (ratio - 2.0) * 2))
        return 15 if ratio >= 4.0 else 14
    return {"high": 12, "medium": 8, "low": 4}.get(entry_quality, 0)


def _stance_from_asset_stance(asset_stance: Any) -> str:
    value = str(asset_stance or "").lower()
    if value == "bullish":
        return CardStance.BULLISH
    if value == "bearish":
        return CardStance.BEARISH
    if value == "neutral":
        return CardStance.NEUTRAL
    return CardStance.INSUFFICIENT_DATA


def _evidence_quality(trade_plan_card: TradePlanCard, entry_quality: str) -> str:
    limitations = " ".join(_list(getattr(trade_plan_card, "data_limitations", []))).lower()
    if (
        "structured_output_failed" in limitations
        or "trade_plan_agent_not_wired" in limitations
        or "insufficient_data" in limitations
        or str(getattr(trade_plan_card, "asset_stance", "")) == "insufficient_data"
    ):
        return "low"
    if entry_quality == "high":
        return "high"
    if entry_quality == "medium":
        return "medium"
    return "medium"


def _position_size_label(target_pct: float | None) -> str:
    if target_pct is None or target_pct <= 0:
        return "none"
    if target_pct <= 0.03:
        return "starter"
    if target_pct <= 0.08:
        return "small"
    if target_pct <= 0.15:
        return "medium"
    return "large"


def _event_risk_notes(event_window: str) -> list[str]:
    if event_window in {"critical", "high"}:
        return ["重点事件风险窗口较高，执行前需要重新确认风险收益"]
    return []


def _clean_text(value: Any) -> str:
    return strip_thinking_tags(str(value or "").strip())[:1200]


def _list(value: Any, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = [str(value)]
    return [_clean_text(item) for item in items if item is not None and _clean_text(item)][:limit]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
