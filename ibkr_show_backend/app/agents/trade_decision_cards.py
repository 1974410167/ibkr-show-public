"""
Trade Decision evidence cards - high-density summary cards consumed by the Composer,
NOT directly shown to the frontend as the final report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Stance enum for all cards
class CardStance:
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    MIXED = "mixed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class EvidenceItem:
    source: str          # tool name, e.g. "mcp_get_quote"
    summary: str          # compact one-line summary of what was found
    confidence: str       # high | medium | low
    data: dict | None = None  # optional structured data snapshot

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "summary": self.summary,
            "confidence": self.confidence,
            "data": self.data,
        }


@dataclass
class TradeDecisionSubAgentTrace:
    sub_agent_name: str
    started_at: str = ""
    finished_at: str = ""
    elapsed_ms: int = 0
    status: str = "pending"  # pending | running | completed | fallback | failed
    error: str | None = None
    rounds_used: int = 0
    tools_called: list[str] = field(default_factory=list)
    tool_call_count: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    runtime_trace: list[dict] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None
    prompt_metadata: dict | None = None
    structured_output: dict | None = None

    def to_dict(self) -> dict:
        return {
            "sub_agent_name": self.sub_agent_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "status": self.status,
            "error": self.error,
            "rounds_used": self.rounds_used,
            "tools_called": self.tools_called,
            "tool_call_count": self.tool_call_count,
            "tool_calls": self.tool_calls,
            "runtime_trace": self.runtime_trace,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "prompt_metadata": self.prompt_metadata,
            "structured_output": self.structured_output,
        }


@dataclass
class AccountFactSnapshot:
    """Deterministic IBKR account data - never calls MCP, never fails."""
    decision_type: str          # "entry_decision" | "holding_decision"
    symbol: str
    normalized_symbol: str
    user_question: str | None
    # Account context
    net_liquidation: float | None
    cash: float | None
    deployable_liquidity: float | None
    deployable_liquidity_ratio: float | None
    total_position_value: float | None
    top_positions: list[dict]    # [{symbol, position_value, position_pct}]
    position_concentration: float | None
    risk_concentration: float | None
    margin_info: dict | None
    # Position context
    is_holding: bool
    quantity: float | None
    avg_cost: float | None
    current_price: float | None
    market_value: float | None
    position_pct: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    realized_pnl: float | None
    # Trade history
    recent_trades: list[dict]     # [{trade_id, date, side, quantity, price, amount, commission, realized_pnl}]
    first_buy_date: str | None
    last_trade_date: str | None
    holding_days: int | None
    # Review context
    latest_review: dict | None   # {overall_score, rating, summary, mistake_tags}
    global_mistake_tags: list[dict]  # [{tag, count}]
    # Data quality
    data_quality: dict = field(default_factory=dict)  # {warnings, missing_fields}

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type,
            "symbol": self.symbol,
            "normalized_symbol": self.normalized_symbol,
            "user_question": self.user_question,
            "account_context": {
                "net_liquidation": self.net_liquidation,
                "cash": self.cash,
                "deployable_liquidity": self.deployable_liquidity,
                "deployable_liquidity_ratio": self.deployable_liquidity_ratio,
                "total_position_value": self.total_position_value,
                "top_positions": self.top_positions,
                "position_concentration": self.position_concentration,
                "risk_position_concentration_ex_cash_equivalents": self.risk_concentration,
                "margin_info": self.margin_info,
            },
            "position_context": {
                "is_holding": self.is_holding,
                "quantity": self.quantity,
                "avg_cost": self.avg_cost,
                "current_price": self.current_price,
                "market_value": self.market_value,
                "position_pct": self.position_pct,
                "unrealized_pnl": self.unrealized_pnl,
                "unrealized_pnl_pct": self.unrealized_pnl_pct,
                "realized_pnl": self.realized_pnl,
            },
            "trade_history_context": {
                "recent_trades": self.recent_trades,
                "first_buy_date": self.first_buy_date,
                "last_trade_date": self.last_trade_date,
                "holding_days": self.holding_days,
            },
            "review_context": {
                "latest_review": self.latest_review,
                "symbol_mistake_tags": (self.latest_review.get("mistake_tags") if self.latest_review else []),
                "global_mistake_summary": self.global_mistake_tags,
            },
            "data_quality": self.data_quality,
        }


@dataclass
class BaseTradeDecisionCard:
    """Base card shared by all sub-agent cards."""
    card_type: str               # e.g. "account_fit", "market_trend", "fundamental", "event", "risk_reward"
    symbol: str
    decision_type: str           # "entry_decision" | "holding_decision"
    summary: str                # 1-3 sentence high-density summary
    score: float = 0            # 0-100 sub-score for this dimension
    max_score: float = 0        # max possible score
    stance: str = CardStance.INSUFFICIENT_DATA  # bullish|neutral|bearish|mixed|insufficient_data
    key_points: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "low"  # high | medium | low
    source_tools: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    data_quality: dict = field(default_factory=dict)
    missing_fields: list[dict] = field(default_factory=list)
    created_at: str = ""

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "symbol": self.symbol,
            "decision_type": self.decision_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "stance": self.stance,
            "key_points": self.key_points,
            "risks": self.risks,
            "opportunities": self.opportunities,
            "evidence": [e.to_dict() if isinstance(e, EvidenceItem) else e for e in self.evidence],
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "source_tools": self.source_tools,
            "tool_calls": self.tool_calls,
            "data_quality": self.data_quality,
            "missing_fields": self.missing_fields,
            "created_at": self.created_at or self._now(),
        }


@dataclass
class AccountFitCard(BaseTradeDecisionCard):
    """AccountFitSubAgent output - account suitability without calling MCP."""
    account_fit_level: str = "unknown"  # excellent | good | fair | poor | unknown
    deployable_liquidity: float | None = None
    current_position_pct: float | None = None
    max_suggested_position_pct: float | None = None
    suggested_cash_amount: float | None = None
    position_size_label: str = "unknown"
    review_warnings: list[str] = field(default_factory=list)
    historical_mistake_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "account_fit_level": self.account_fit_level,
            "deployable_liquidity": self.deployable_liquidity,
            "current_position_pct": self.current_position_pct,
            "max_suggested_position_pct": self.max_suggested_position_pct,
            "suggested_cash_amount": self.suggested_cash_amount,
            "position_size_label": self.position_size_label,
            "review_warnings": self.review_warnings,
            "historical_mistake_flags": self.historical_mistake_flags,
        })
        return base


@dataclass
class MarketTrendCard(BaseTradeDecisionCard):
    """MarketTrendSubAgent output - price trend and market context via MCP."""
    price_trend: str = "unknown"  # bullish | neutral | bearish
    relative_to_benchmark: str | None = None
    benchmark_symbols: list[str] = field(default_factory=list)
    recent_return_pct: float | None = None
    volatility_summary: str = ""
    volume_signal: str | None = None
    support_resistance: dict = field(default_factory=dict)
    sector_view: str | None = None
    # Stage 02 - TechnicalSignalEngine outputs
    technical_signals: dict = field(default_factory=dict)
    trend_break_level: str = "unknown"  # none | warning | broken | severe | unknown
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    relative_strength_score: float | None = None

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "price_trend": self.price_trend,
            "relative_to_benchmark": self.relative_to_benchmark,
            "benchmark_symbols": self.benchmark_symbols,
            "recent_return_pct": self.recent_return_pct,
            "volatility_summary": self.volatility_summary,
            "volume_signal": self.volume_signal,
            "support_resistance": self.support_resistance,
            "sector_view": self.sector_view,
            "technical_signals": self.technical_signals,
            "trend_break_level": self.trend_break_level,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "relative_strength_score": self.relative_strength_score,
        })
        return base


@dataclass
class FundamentalValuationCard(BaseTradeDecisionCard):
    """FundamentalValuationSubAgent output - fundamentals and valuation via MCP."""
    company_name: str = ""
    market_cap: float | None = None
    pe_ttm: float | None = None
    forward_pe: float | None = None
    ps_ttm: float | None = None
    ev_sales: float | None = None
    dividend_yield: float | None = None
    revenue_growth_summary: str = ""
    profitability_summary: str = ""
    valuation_summary: str = ""
    peer_relative_note: str = ""
    industry: str | None = None
    business_segments: list[dict] | dict | str | None = None
    institutional_rating: str | None = None
    target_price: float | None = None
    data_limitations: list[str] = field(default_factory=list)
    # Stage 04 - FundamentalChangeEngine outputs
    fundamental_status: str = "unknown"  # green | yellow | orange | red | unknown
    thesis_broken: bool = False
    change_signals: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    revenue_growth_trend: str | None = None  # accelerating | stable | slowing | unknown
    margin_trend: str | None = None
    cash_flow_trend: str | None = None
    guidance_change: str | None = None  # raised | maintained | cut | unknown
    segment_growth_notes: list[str] = field(default_factory=list)
    fundamental_change_evidence: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "company_name": self.company_name,
            "market_cap": self.market_cap,
            "pe_ttm": self.pe_ttm,
            "forward_pe": self.forward_pe,
            "ps_ttm": self.ps_ttm,
            "ev_sales": self.ev_sales,
            "dividend_yield": self.dividend_yield,
            "revenue_growth_summary": self.revenue_growth_summary,
            "profitability_summary": self.profitability_summary,
            "valuation_summary": self.valuation_summary,
            "peer_relative_note": self.peer_relative_note,
            "industry": self.industry,
            "business_segments": self.business_segments,
            "institutional_rating": self.institutional_rating,
            "target_price": self.target_price,
        })
        base["data_limitations"] = self.data_limitations
        base.update({
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
            "fundamental_change_evidence": list(self.fundamental_change_evidence),
        })
        return base


@dataclass
class EventCatalystCard(BaseTradeDecisionCard):
    """EventCatalystSubAgent output - catalysts and events via MCP."""
    next_earnings_date: str | None = None
    recent_news_count: int = 0
    key_events: list[str] = field(default_factory=list)
    sentiment: str = "neutral"  # positive | negative | neutral
    catalyst_strength: str = "neutral"  # strong | moderate | weak
    risk_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "next_earnings_date": self.next_earnings_date,
            "recent_news_count": self.recent_news_count,
            "key_events": self.key_events,
            "sentiment": self.sentiment,
            "catalyst_strength": self.catalyst_strength,
            "risk_events": self.risk_events,
        })
        return base


@dataclass
class RiskRewardCard(BaseTradeDecisionCard):
    """RiskRewardSubAgent output - risk/reward assessment, minimal MCP."""
    upside_potential_pct: float | None = None
    downside_risk_pct: float | None = None
    reward_risk_ratio: float | None = None
    max_position_pct: float | None = None
    wait_for_pullback: bool = False
    wait_for_pullback_pct: float | None = None
    pullback_entry_level: float | None = None
    action_guidance: str | None = None
    position_size_label: str = "unknown"
    key_risks: list[str] = field(default_factory=list)
    key_opportunities: list[str] = field(default_factory=list)
    risk_assessment_reason: str | None = None
    # Stage 05 - RiskRewardEngine outputs
    downside_scenarios: list[dict] = field(default_factory=list)
    upside_scenarios: list[dict] = field(default_factory=list)
    stop_add_level: float | None = None
    invalidation_level: float | None = None
    trim_level: float | None = None
    risk_reward_confidence: str = "unknown"  # high | medium | low | unknown
    risk_reward_thesis_broken: bool = False

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "upside_potential_pct": self.upside_potential_pct,
            "downside_risk_pct": self.downside_risk_pct,
            "reward_risk_ratio": self.reward_risk_ratio,
            "max_position_pct": self.max_position_pct,
            "wait_for_pullback": self.wait_for_pullback,
            "wait_for_pullback_pct": self.wait_for_pullback_pct,
            "pullback_entry_level": self.pullback_entry_level,
            "action_guidance": self.action_guidance,
            "position_size_label": self.position_size_label,
            "key_risks": self.key_risks,
            "key_opportunities": self.key_opportunities,
            "risk_assessment_reason": self.risk_assessment_reason,
            "downside_scenarios": list(self.downside_scenarios),
            "upside_scenarios": list(self.upside_scenarios),
            "stop_add_level": self.stop_add_level,
            "invalidation_level": self.invalidation_level,
            "trim_level": self.trim_level,
            "risk_reward_confidence": self.risk_reward_confidence,
            "risk_reward_thesis_broken": self.risk_reward_thesis_broken,
        })
        return base


@dataclass
class TradeDecisionCardPack:
    """Container for all sub-agent cards - consumed by Composer."""
    decision_type: str
    symbol: str
    account_fact_snapshot: AccountFactSnapshot
    account_fit_card: AccountFitCard | None = None
    market_trend_card: MarketTrendCard | None = None
    fundamental_valuation_card: FundamentalValuationCard | None = None
    event_catalyst_card: EventCatalystCard | None = None
    risk_reward_card: RiskRewardCard | None = None
    data_quality_summary: str = "medium"
    subagent_traces: list[TradeDecisionSubAgentTrace] = field(default_factory=list)
    # Stage 03 - per-symbol investment thesis (code-only, default if missing)
    investment_thesis: dict | None = None

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type,
            "symbol": self.symbol,
            "account_fact_snapshot": (self.account_fact_snapshot.to_dict() if isinstance(self.account_fact_snapshot, AccountFactSnapshot) else self.account_fact_snapshot),
            "account_fit_card": (self.account_fit_card.to_dict() if self.account_fit_card else None),
            "market_trend_card": (self.market_trend_card.to_dict() if self.market_trend_card else None),
            "fundamental_valuation_card": (self.fundamental_valuation_card.to_dict() if self.fundamental_valuation_card else None),
            "event_catalyst_card": (self.event_catalyst_card.to_dict() if self.event_catalyst_card else None),
            "risk_reward_card": (self.risk_reward_card.to_dict() if self.risk_reward_card else None),
            "data_quality_summary": self.data_quality_summary,
            "subagent_traces": [t.to_dict() if isinstance(t, TradeDecisionSubAgentTrace) else t for t in self.subagent_traces],
            "investment_thesis": self.investment_thesis,
        }


# --- Fallback card builders ---


def build_fallback_account_fit_card(symbol: str, decision_type: str, reason: str) -> AccountFitCard:
    return AccountFitCard(
        card_type="account_fit",
        symbol=symbol,
        decision_type=decision_type,
        summary="账户适配评估暂不可用，已基于可用信息采取保守处理。",
        score=0,
        max_score=20,
        stance=CardStance.INSUFFICIENT_DATA,
        account_fit_level="unknown",
        evidence_quality="low",
        data_limitations=["账户适配信息不足，已保守降低该维度置信度"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_fallback_market_trend_card(symbol: str, decision_type: str, reason: str) -> MarketTrendCard:
    return MarketTrendCard(
        card_type="market_trend",
        symbol=symbol,
        decision_type=decision_type,
        summary="公开行情数据不足，已基于可用信息采取保守趋势判断。",
        score=0,
        max_score=15,
        stance=CardStance.INSUFFICIENT_DATA,
        evidence_quality="low",
        data_limitations=["公开行情数据不足，已基于可用数据做保守分析"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_fallback_fundamental_card(symbol: str, decision_type: str, reason: str) -> FundamentalValuationCard:
    return FundamentalValuationCard(
        card_type="fundamental_valuation",
        symbol=symbol,
        decision_type=decision_type,
        summary="基本面和估值数据不足，已基于可用信息采取保守处理。",
        score=0,
        max_score=35,  # fundamental_quality(20) + valuation(15)
        stance=CardStance.INSUFFICIENT_DATA,
        evidence_quality="low",
        data_limitations=["基本面和估值数据不足，已保守降低该维度置信度"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_fallback_event_card(symbol: str, decision_type: str, reason: str) -> EventCatalystCard:
    return EventCatalystCard(
        card_type="event_catalyst",
        symbol=symbol,
        decision_type=decision_type,
        summary="公开新闻和事件数据不足，已基于可用新闻做保守分析。",
        score=0,
        max_score=5,
        stance=CardStance.INSUFFICIENT_DATA,
        evidence_quality="low",
        data_limitations=["公开新闻数据不足，已基于可用新闻做保守分析"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_fallback_risk_reward_card(symbol: str, decision_type: str, reason: str) -> RiskRewardCard:
    return RiskRewardCard(
        card_type="risk_reward",
        symbol=symbol,
        decision_type=decision_type,
        summary="风险收益评估信息不足，已采取保守处理。",
        score=0,
        max_score=15,
        stance=CardStance.INSUFFICIENT_DATA,
        evidence_quality="low",
        data_limitations=["风险收益数据不足，已保守降低该维度置信度"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def compute_trade_decision_card_pack_summary(card_pack: TradeDecisionCardPack) -> dict:
    """Build a compact summary of the card pack for storage/display."""
    quality_scores = []
    if card_pack.account_fit_card:
        quality_scores.append(card_pack.account_fit_card.evidence_quality)
    if card_pack.market_trend_card:
        quality_scores.append(card_pack.market_trend_card.evidence_quality)
    if card_pack.fundamental_valuation_card:
        quality_scores.append(card_pack.fundamental_valuation_card.evidence_quality)
    if card_pack.event_catalyst_card:
        quality_scores.append(card_pack.event_catalyst_card.evidence_quality)
    if card_pack.risk_reward_card:
        quality_scores.append(card_pack.risk_reward_card.evidence_quality)

    quality_map = {"high": 3, "medium": 2, "low": 1}
    avg_quality = sum(quality_map.get(q, 0) for q in quality_scores) / max(len(quality_scores), 1)
    overall_quality = "high" if avg_quality >= 2.5 else "medium" if avg_quality >= 1.5 else "low"

    total_score = 0
    total_max = 0
    for card in [card_pack.account_fit_card, card_pack.market_trend_card,
                 card_pack.fundamental_valuation_card, card_pack.event_catalyst_card,
                 card_pack.risk_reward_card]:
        if card:
            total_score += card.score
            total_max += card.max_score

    fallback_count = sum(1 for t in card_pack.subagent_traces if t.fallback_used)

    return {
        "overall_quality": overall_quality,
        "card_count": len([c for c in [
            card_pack.account_fit_card, card_pack.market_trend_card,
            card_pack.fundamental_valuation_card, card_pack.event_catalyst_card,
            card_pack.risk_reward_card
        ] if c is not None]),
        "total_score": total_score,
        "total_max_score": total_max,
        "fallback_count": fallback_count,
        "subagent_count": len(card_pack.subagent_traces),
        "traces": [t.sub_agent_name for t in card_pack.subagent_traces],
    }
