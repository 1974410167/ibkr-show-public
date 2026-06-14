"""Trade decision graph state definition."""

from __future__ import annotations

from typing import TypedDict

from app.agents.graph.base_state import BaseGraphState
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    DebateJudgeCard,
    DebateRebuttalCard,
    DebateThesisCard,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketEventContextCard,
    MarketTrendCard,
    RiskRewardCard,
    TradePlanCard,
    TradeDecisionCardPack,
)


class TradeDecisionGraphState(BaseGraphState, total=False):
    decision_type: str
    symbol: str
    normalized_symbol: str
    user_question: str | None

    account_fact_snapshot: AccountFactSnapshot | dict | None
    user_investment_policy: dict | None
    ai_policy_assessment: dict | None

    account_fit_card: AccountFitCard | None
    market_trend_card: MarketTrendCard | None
    fundamental_valuation_card: FundamentalValuationCard | None
    event_catalyst_card: EventCatalystCard | None
    market_event_context_card: MarketEventContextCard | None
    risk_reward_card: RiskRewardCard | None
    bull_thesis_card: DebateThesisCard | dict | None
    bear_thesis_card: DebateThesisCard | dict | None
    bull_rebuttal_card: DebateRebuttalCard | dict | None
    bear_rebuttal_card: DebateRebuttalCard | dict | None
    debate_judge_card: DebateJudgeCard | dict | None
    trade_plan_card: TradePlanCard | dict | None

    card_pack: TradeDecisionCardPack | None
    decision_output: dict | None
    saved_document: dict | None

    mcp_available: bool | None

    # Per-node public data mode — parallel-safe, no shared single-value write
    market_public_data_mode: str | None
    fundamental_public_data_mode: str | None
    event_public_data_mode: str | None
    market_trend_prompt_metadata: dict | None
    fundamental_valuation_prompt_metadata: dict | None
    event_catalyst_prompt_metadata: dict | None
    bull_thesis_prompt_metadata: dict | None
    bear_thesis_prompt_metadata: dict | None
    bull_rebuttal_prompt_metadata: dict | None
    bear_rebuttal_prompt_metadata: dict | None
    debate_judge_prompt_metadata: dict | None
    trade_plan_prompt_metadata: dict | None
    ai_policy_assessment_prompt_metadata: dict | None
