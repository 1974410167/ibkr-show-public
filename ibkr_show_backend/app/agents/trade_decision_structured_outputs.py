from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.structured_output import StructuredOutputContract


class MarketTrendLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    price_trend: Literal["bullish", "neutral", "bearish"]
    recent_return_pct: float = 0.0
    volatility_summary: Literal["high", "medium", "low"] = "medium"
    relative_to_benchmark: str | None = None
    score: float = Field(ge=0, le=15)
    key_points: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class FundamentalValuationLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    company_name: str | None = None
    pe_ttm: float | None = None
    forward_pe: float | None = None
    market_cap: float | None = None
    ps_ttm: float | None = None
    dividend_yield: float | None = None
    revenue_growth_summary: str | None = None
    profitability_summary: str | None = None
    valuation_summary: str | None = None
    industry: str | None = None
    business_segments: Any | None = None
    institutional_rating: str | None = None
    target_price: float | None = None
    peer_relative_note: str | None = None
    score: float = Field(ge=0, le=35)
    key_points: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class EventCatalystLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    next_earnings_date: str | None = None
    recent_news_count: int = Field(default=0, ge=0)
    sentiment: Literal["positive", "neutral", "negative"]
    catalyst_strength: Literal["strong", "moderate", "weak"]
    key_events: list[str] = Field(default_factory=list)
    risk_events: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=5)
    data_limitations: list[str] = Field(default_factory=list)


class RiskRewardLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    key_risks: list[str] = Field(default_factory=list)
    key_opportunities: list[str] = Field(default_factory=list)
    risk_assessment_reason: str | None = None
    data_limitations: list[str] = Field(default_factory=list)


class DebateThesisLLMOutput(BaseModel):
    agent_name: Literal["bull_thesis", "bear_thesis"]
    stance: Literal["bullish", "bearish"]
    conviction: Literal["high", "medium", "low"] = "low"
    summary: str = Field(min_length=1)
    core_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class DebateRebuttalLLMOutput(BaseModel):
    agent_name: Literal["bull_rebuttal", "bear_rebuttal"]
    summary: str = Field(min_length=1)
    accepted_opponent_points: list[str] = Field(default_factory=list)
    rejected_opponent_points: list[str] = Field(default_factory=list)
    reinforced_arguments: list[str] = Field(default_factory=list)
    final_conviction: Literal["high", "medium", "low"] = "low"
    data_limitations: list[str] = Field(default_factory=list)


class DebateJudgeLLMOutput(BaseModel):
    asset_stance: Literal["bullish", "neutral", "bearish", "insufficient_data"]
    conviction: Literal["high", "medium", "low"] = "low"
    winner: Literal["bull", "bear", "balanced", "insufficient_data"]
    accepted_bull_points: list[str] = Field(default_factory=list)
    accepted_bear_points: list[str] = Field(default_factory=list)
    key_uncertainties: list[str] = Field(default_factory=list)
    reasoning_summary: str = Field(min_length=1)
    data_limitations: list[str] = Field(default_factory=list)


class TradePlanLLMOutput(BaseModel):
    asset_stance: Literal["bullish", "neutral", "bearish", "insufficient_data"]
    portfolio_action: str = Field(min_length=1)
    action_reason_type: str = Field(min_length=1)
    current_position_pct: float | None = None
    target_position_pct: float | None = None
    adjustment_pct: float | None = None
    suggested_cash_amount: float | None = None
    max_position_pct: float | None = None
    execution_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    recheck_triggers: list[str] = Field(default_factory=list)
    risk_reward_assessment: dict = Field(default_factory=dict)
    data_limitations: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class AiPolicyRiskBudget(BaseModel):
    estimated_downside_pct: float | None = Field(default=None, ge=0, le=1)
    max_account_loss_pct: float | None = Field(default=None, ge=0, le=1)
    reason: str = ""


class AiPolicyAssessmentOutput(BaseModel):
    status: Literal["evaluated", "fallback", "not_evaluated"] = "evaluated"
    ai_assessed_asset_role: Literal[
        "core_growth",
        "faith_holding",
        "satellite_growth",
        "speculative",
        "btc_proxy",
        "cash_like",
        "index_etf",
        "watchlist",
        "forbidden",
        "unknown",
    ] = "unknown"
    ai_role_confidence: Literal["high", "medium", "low"] = "low"
    ai_recommended_min_position_pct: float | None = Field(default=None, ge=0, le=1)
    ai_recommended_target_position_pct: float | None = Field(default=None, ge=0, le=1)
    ai_recommended_max_position_pct: float | None = Field(default=None, ge=0, le=1)
    ai_recommended_target_position_range_pct: list[float] | None = Field(default=None, min_length=2, max_length=2)
    ai_position_stance: Literal["no_position", "underweight", "near_target", "overweight", "over_limit", "forbidden", "unknown"] = "unknown"
    current_position_pct: float = Field(default=0.0, ge=0, le=1)
    gap_to_ai_target_pct: float | None = None
    gap_to_ai_max_pct: float | None = None
    challenge_level: Literal[
        "agree",
        "mild_disagreement",
        "strong_disagreement",
        "risk_warning",
        "not_evaluated",
    ] = "not_evaluated"
    challenge_reason: str | None = None
    preference_alignment_summary: str = ""
    recommended_action_bias: Literal[
        "allow_add",
        "prefer_pullback_add",
        "hold_no_add",
        "prefer_reduce",
        "avoid",
        "unknown",
    ] = "unknown"
    risk_budget: AiPolicyRiskBudget = Field(default_factory=AiPolicyRiskBudget)
    key_reasons: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    prompt_key: str = "trade_decision_ai_policy_assessment"
    prompt_source: Literal["admin_config", "default_fallback"] = "default_fallback"
    prompt_version: str | None = None
    prompt_updated_at: str | None = None
    prompt_template_name: str | None = None
    prompt_content_hash: str | None = None

    @field_validator("ai_recommended_target_position_range_pct")
    @classmethod
    def _validate_range_values(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        low, high = float(value[0]), float(value[1])
        if low < 0 or high < 0 or low > 1 or high > 1:
            raise ValueError("ai_recommended_target_position_range_pct values must be between 0 and 1")
        if low > high:
            raise ValueError("target position range lower bound cannot exceed upper bound")
        return [low, high]

    @field_validator(
        "challenge_reason",
        "preference_alignment_summary",
        "key_reasons",
        "key_risks",
        "data_limitations",
        mode="after",
    )
    @classmethod
    def _ban_guaranteed_profit_language(cls, value: Any) -> Any:
        banned = ("保证收益", "必涨", "一定盈利")
        texts = value if isinstance(value, list) else [value]
        for item in texts:
            text = str(item or "")
            if any(token in text for token in banned):
                raise ValueError("AI policy assessment cannot promise guaranteed gains")
        return value

    @model_validator(mode="after")
    def _validate_position_order_and_status(self) -> "AiPolicyAssessmentOutput":
        ordered = [
            self.ai_recommended_min_position_pct,
            self.ai_recommended_target_position_pct,
            self.ai_recommended_max_position_pct,
        ]
        if all(value is not None for value in ordered):
            assert self.ai_recommended_min_position_pct is not None
            assert self.ai_recommended_target_position_pct is not None
            assert self.ai_recommended_max_position_pct is not None
            if not (
                self.ai_recommended_min_position_pct
                <= self.ai_recommended_target_position_pct
                <= self.ai_recommended_max_position_pct
            ):
                raise ValueError("AI recommended position order must be min <= target <= max")
        if self.ai_recommended_target_position_range_pct is not None:
            low, high = self.ai_recommended_target_position_range_pct
            if self.ai_recommended_target_position_pct is not None and not (low <= self.ai_recommended_target_position_pct <= high):
                raise ValueError("AI recommended target must be inside target range")
            if self.ai_recommended_min_position_pct is not None and self.ai_recommended_min_position_pct > low:
                raise ValueError("AI recommended min cannot exceed range lower bound")
            if self.ai_recommended_max_position_pct is not None and self.ai_recommended_max_position_pct < high:
                raise ValueError("AI recommended max cannot be below range upper bound")
        if self.status == "fallback" and self.challenge_level not in {"not_evaluated", "risk_warning"}:
            raise ValueError("fallback assessment must use not_evaluated or risk_warning challenge level")
        if self.data_limitations and self.ai_role_confidence == "high":
            raise ValueError("high confidence is not allowed when data limitations are present")
        return self


def build_ai_policy_assessment_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_ai_policy_assessment",
        agent_name="trade_decision",
        node_name="ai_policy_assessment",
        output_model=AiPolicyAssessmentOutput,
        schema_hint=AiPolicyAssessmentOutput.model_json_schema(),
        examples=[AI_POLICY_ASSESSMENT_EVALUATED_EXAMPLE, AI_POLICY_ASSESSMENT_FALLBACK_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_market_trend_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_market_trend",
        agent_name="trade_decision",
        node_name="market_trend",
        output_model=MarketTrendLLMOutput,
        schema_hint=MarketTrendLLMOutput.model_json_schema(),
        examples=[MARKET_TREND_NORMAL_EXAMPLE, MARKET_TREND_INSUFFICIENT_DATA_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_fundamental_valuation_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_fundamental_valuation",
        agent_name="trade_decision",
        node_name="fundamental_valuation",
        output_model=FundamentalValuationLLMOutput,
        schema_hint=FundamentalValuationLLMOutput.model_json_schema(),
        examples=[FUNDAMENTAL_NORMAL_EXAMPLE, FUNDAMENTAL_LOSS_COMPANY_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_event_catalyst_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_event_catalyst",
        agent_name="trade_decision",
        node_name="event_catalyst",
        output_model=EventCatalystLLMOutput,
        schema_hint=EventCatalystLLMOutput.model_json_schema(),
        examples=[EVENT_NORMAL_EXAMPLE, EVENT_INSUFFICIENT_DATA_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_risk_reward_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_risk_reward",
        agent_name="trade_decision",
        node_name="risk_reward",
        output_model=RiskRewardLLMOutput,
        schema_hint=RiskRewardLLMOutput.model_json_schema(),
        examples=[RISK_REWARD_NORMAL_EXAMPLE, RISK_REWARD_INSUFFICIENT_DATA_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_debate_thesis_contract(node_name: str) -> StructuredOutputContract:
    examples = [BULL_THESIS_EXAMPLE] if node_name == "bull_thesis" else [BEAR_THESIS_EXAMPLE]
    return StructuredOutputContract(
        name=f"trade_decision_{node_name}",
        agent_name="trade_decision",
        node_name=node_name,
        output_model=DebateThesisLLMOutput,
        schema_hint=DebateThesisLLMOutput.model_json_schema(),
        examples=examples,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_debate_rebuttal_contract(node_name: str) -> StructuredOutputContract:
    examples = [BULL_REBUTTAL_EXAMPLE] if node_name == "bull_rebuttal" else [BEAR_REBUTTAL_EXAMPLE]
    return StructuredOutputContract(
        name=f"trade_decision_{node_name}",
        agent_name="trade_decision",
        node_name=node_name,
        output_model=DebateRebuttalLLMOutput,
        schema_hint=DebateRebuttalLLMOutput.model_json_schema(),
        examples=examples,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_debate_judge_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_debate_judge",
        agent_name="trade_decision",
        node_name="debate_judge",
        output_model=DebateJudgeLLMOutput,
        schema_hint=DebateJudgeLLMOutput.model_json_schema(),
        examples=[DEBATE_JUDGE_BALANCED_EXAMPLE, DEBATE_JUDGE_INSUFFICIENT_DATA_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


def build_trade_plan_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_decision_trade_plan",
        agent_name="trade_decision",
        node_name="trade_plan",
        output_model=TradePlanLLMOutput,
        schema_hint=TradePlanLLMOutput.model_json_schema(),
        examples=[TRADE_PLAN_ENTRY_WATCHLIST_EXAMPLE, TRADE_PLAN_HOLDING_HOLD_NO_ADD_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
    )


MARKET_TREND_NORMAL_EXAMPLE = {
    "summary": "价格站上短期均线且相对 QQQ/SPY/SMH 表现略强，但波动仍偏高。",
    "price_trend": "bullish",
    "recent_return_pct": 6.2,
    "volatility_summary": "high",
    "relative_to_benchmark": "近一个月相对 QQQ 和 SMH 略强，相对 SPY 明显更强。",
    "score": 12,
    "key_points": ["近期价格动能改善", "相对半导体基准表现偏强"],
    "risks": ["短期波动较高", "若成交量无法延续，趋势可能回落"],
    "data_limitations": [],
}

MARKET_TREND_INSUFFICIENT_DATA_EXAMPLE = {
    "summary": "行情或 benchmark 数据不足，短期趋势信号不完整，暂按中性处理。",
    "price_trend": "neutral",
    "recent_return_pct": 0.0,
    "volatility_summary": "medium",
    "relative_to_benchmark": None,
    "score": 7,
    "key_points": [],
    "risks": ["缺少足够行情或基准数据，趋势判断置信度较低"],
    "data_limitations": ["benchmark 数据缺失，无法确认相对强弱"],
}

FUNDAMENTAL_NORMAL_EXAMPLE = {
    "summary": "公司盈利能力稳定，估值处于成长股可接受区间，但仍需关注增长兑现。",
    "company_name": "Example Corp",
    "pe_ttm": 28.5,
    "forward_pe": 24.0,
    "market_cap": 250000000000.0,
    "ps_ttm": 8.2,
    "dividend_yield": 0.0,
    "revenue_growth_summary": "收入保持双位数增长。",
    "profitability_summary": "毛利率和经营利润率保持稳定。",
    "valuation_summary": "PE 和 forward PE 反映成长预期，不宜简单视为便宜。",
    "industry": "Semiconductors",
    "business_segments": [{"name": "Data Center", "share": "high"}],
    "institutional_rating": "buy",
    "target_price": 150.0,
    "peer_relative_note": "估值略高于同业，但增长预期也更高。",
    "score": 26,
    "key_points": ["盈利质量较好", "增长预期仍是估值支撑"],
    "risks": ["估值对增长放缓敏感"],
    "data_limitations": [],
}

FUNDAMENTAL_LOSS_COMPANY_EXAMPLE = {
    "summary": "公司仍处亏损或利润波动期，传统 PE 指标不适用，应更多参考收入、现金流和业务进展。",
    "company_name": None,
    "pe_ttm": None,
    "forward_pe": None,
    "market_cap": None,
    "ps_ttm": None,
    "dividend_yield": None,
    "revenue_growth_summary": None,
    "profitability_summary": "利润为负或波动较大。",
    "valuation_summary": "PE / forward PE 不适用，不能用低 PE 或高 PE 机械判断贵便宜。",
    "industry": None,
    "business_segments": None,
    "institutional_rating": None,
    "target_price": None,
    "peer_relative_note": None,
    "score": 12,
    "key_points": [],
    "risks": ["亏损公司估值置信度较低"],
    "data_limitations": ["pe_ttm / forward_pe 缺失或不适用"],
}

EVENT_NORMAL_EXAMPLE = {
    "summary": "近期有财报窗口和机构评级变化，存在中等事件催化，但需结合实际结果验证。",
    "next_earnings_date": "2026-07-25",
    "recent_news_count": 6,
    "sentiment": "positive",
    "catalyst_strength": "moderate",
    "key_events": ["即将进入财报窗口", "机构上调目标价"],
    "risk_events": ["财报不及预期可能压制估值"],
    "score": 4,
    "data_limitations": [],
}

EVENT_INSUFFICIENT_DATA_EXAMPLE = {
    "summary": "新闻和财报日历信息不足，无法确认强催化，暂按弱催化处理。",
    "next_earnings_date": None,
    "recent_news_count": 0,
    "sentiment": "neutral",
    "catalyst_strength": "weak",
    "key_events": [],
    "risk_events": [],
    "score": 2,
    "data_limitations": ["财经日历暂未返回下一次财报日期", "部分新闻缺少摘要或发布时间"],
}

RISK_REWARD_NORMAL_EXAMPLE = {
    "summary": "基于当前估值和市场趋势，风险收益比尚可，但下行风险需关注。",
    "key_risks": ["估值偏高，回调空间较大", "若行业景气度下降，可能面临戴维斯双杀"],
    "key_opportunities": ["业绩增长预期支撑估值", "技术面短期动能偏强"],
    "risk_assessment_reason": "风险收益比 1.8x，上行空间有限但下行风险可控。",
    "data_limitations": [],
}

RISK_REWARD_INSUFFICIENT_DATA_EXAMPLE = {
    "summary": "公开市场数据不足，无法可靠评估风险收益，建议等待更多信息。",
    "key_risks": ["数据不足，风险评估置信度低"],
    "key_opportunities": [],
    "risk_assessment_reason": None,
    "data_limitations": ["行情或基本面数据不完整，风险收益评估受限"],
}

BULL_THESIS_EXAMPLE = {
    "agent_name": "bull_thesis",
    "stance": "bullish",
    "conviction": "medium",
    "summary": "趋势证据改善且基本面质量仍有支撑，但事件窗口和估值风险使看多置信度保持中等。",
    "core_claims": ["市场趋势卡显示相对基准表现转强", "基本面估值卡显示盈利质量稳定"],
    "evidence_refs": ["market_trend_card", "fundamental_valuation_card"],
    "weak_points": ["估值仍依赖增长兑现", "近期事件风险可能放大波动"],
    "risk_flags": ["event_risk_window", "valuation_sensitivity"],
    "data_limitations": [],
}

BEAR_THESIS_EXAMPLE = {
    "agent_name": "bear_thesis",
    "stance": "bearish",
    "conviction": "medium",
    "summary": "虽然趋势有改善，但估值安全边际不足且事件催化不确定，不应把短期动能直接等同于可靠上行。",
    "core_claims": ["估值对业绩兑现敏感", "事件催化强度不足以抵消回撤风险"],
    "evidence_refs": ["fundamental_valuation_card", "event_catalyst_card", "market_event_context_card"],
    "weak_points": ["若财报或评级明显超预期，谨慎观点可能失效"],
    "risk_flags": ["high_valuation", "catalyst_uncertainty"],
    "data_limitations": [],
}

BULL_REBUTTAL_EXAMPLE = {
    "agent_name": "bull_rebuttal",
    "summary": "空头关于估值和事件风险的提醒成立，但现有趋势与基本面证据仍支持温和看多，而不是完全回避。",
    "accepted_opponent_points": ["估值对增长放缓敏感", "事件窗口可能增加短期波动"],
    "rejected_opponent_points": ["短期波动不等于趋势已经破坏", "估值偏高不能单独否定公司质量"],
    "reinforced_arguments": ["相对基准强势仍是有效正面证据", "盈利质量稳定降低了部分下行风险"],
    "final_conviction": "medium",
    "data_limitations": [],
}

BEAR_REBUTTAL_EXAMPLE = {
    "agent_name": "bear_rebuttal",
    "summary": "多头对趋势改善的引用有效，但证据尚不足以支持高置信度看多，尤其在估值和事件窗口未确认前。",
    "accepted_opponent_points": ["趋势改善是真实正面信号", "基本面质量仍有支撑"],
    "rejected_opponent_points": ["相对强势不足以证明风险收益已经占优", "缺少明确催化时不应上调 conviction"],
    "reinforced_arguments": ["估值敏感性仍是主要约束", "事件不确定性要求保持保守"],
    "final_conviction": "medium",
    "data_limitations": [],
}

DEBATE_JUDGE_BALANCED_EXAMPLE = {
    "asset_stance": "neutral",
    "conviction": "medium",
    "winner": "balanced",
    "accepted_bull_points": ["趋势改善有证据支持", "基本面质量没有明显恶化"],
    "accepted_bear_points": ["估值对增长放缓敏感", "事件窗口可能带来回撤"],
    "key_uncertainties": ["下一次财报是否验证增长", "相对强势能否延续"],
    "reasoning_summary": "多空证据都成立，当前更适合给出中性标的观点，等待催化和风险收益进一步明朗。",
    "data_limitations": [],
}

DEBATE_JUDGE_INSUFFICIENT_DATA_EXAMPLE = {
    "asset_stance": "insufficient_data",
    "conviction": "low",
    "winner": "insufficient_data",
    "accepted_bull_points": [],
    "accepted_bear_points": ["公开市场证据不足，不能可靠判断标的方向"],
    "key_uncertainties": ["行情、估值或事件数据缺失", "无法验证多头或空头主张"],
    "reasoning_summary": "输入证据质量不足，不能输出明确 bullish 或 bearish，应降级为 insufficient_data。",
    "data_limitations": ["公开市场数据大面积缺失或 fallback"],
}

TRADE_PLAN_ENTRY_WATCHLIST_EXAMPLE = {
    "asset_stance": "neutral",
    "portfolio_action": "watchlist",
    "action_reason_type": "no_action",
    "current_position_pct": 0.0,
    "target_position_pct": 0.0,
    "adjustment_pct": 0.0,
    "suggested_cash_amount": 0.0,
    "max_position_pct": 0.05,
    "execution_conditions": ["等待财报或关键事件落地", "价格回撤后风险收益改善再复查"],
    "invalidation_conditions": ["标的级观点转为 bearish", "公开数据继续不足"],
    "recheck_triggers": ["下一次财报发布", "事件风险解除", "趋势相对基准重新转强"],
    "risk_reward_assessment": {
        "entry_quality": "unknown",
        "upside_scenario": "催化兑现且趋势延续时再评估小仓位试探",
        "downside_scenario": "催化不及预期或估值压缩导致继续回撤",
        "reward_risk_ratio": None,
        "wait_for_pullback": True,
        "pullback_entry_level": None,
        "invalidation_level": None,
        "trim_level": None,
        "event_risk_window": "medium",
        "sanitization_notes": [],
    },
    "data_limitations": [],
    "summary": "无持仓且标的观点中性，当前不生成买入动作，先纳入观察并等待更清晰的催化或回撤机会。",
}

TRADE_PLAN_HOLDING_HOLD_NO_ADD_EXAMPLE = {
    "asset_stance": "bullish",
    "portfolio_action": "hold_no_add",
    "action_reason_type": "portfolio_risk_constraint",
    "current_position_pct": 0.08,
    "target_position_pct": 0.08,
    "adjustment_pct": 0.0,
    "suggested_cash_amount": 0.0,
    "max_position_pct": 0.08,
    "execution_conditions": ["继续持有但不加仓", "若价格回撤且仓位上限提高再复查"],
    "invalidation_conditions": ["asset_stance 降为 bearish", "核心基本面或趋势证据失效"],
    "recheck_triggers": ["仓位占比下降", "财报确认增长", "事件风险解除"],
    "risk_reward_assessment": {
        "entry_quality": "fair",
        "upside_scenario": "趋势延续且财报兑现时保留已有仓位收益",
        "downside_scenario": "估值压缩或事件风险触发回撤",
        "reward_risk_ratio": 1.4,
        "wait_for_pullback": True,
        "pullback_entry_level": None,
        "invalidation_level": None,
        "trim_level": None,
        "event_risk_window": "medium",
        "sanitization_notes": [],
    },
    "data_limitations": [],
    "summary": "标的观点偏多但当前仓位已达到建议上限，因此动作应为持有不加仓，而不是继续提高敞口。",
}

AI_POLICY_ASSESSMENT_EVALUATED_EXAMPLE = {
    "status": "evaluated",
    "ai_assessed_asset_role": "core_growth",
    "ai_role_confidence": "medium",
    "ai_recommended_min_position_pct": 0.08,
    "ai_recommended_target_position_pct": 0.14,
    "ai_recommended_max_position_pct": 0.2,
    "ai_recommended_target_position_range_pct": [0.12, 0.16],
    "ai_position_stance": "underweight",
    "current_position_pct": 0.06,
    "gap_to_ai_target_pct": 0.08,
    "gap_to_ai_max_pct": 0.14,
    "challenge_level": "mild_disagreement",
    "challenge_reason": "用户偏好上限偏高，当前估值和事件窗口不支持直接打到最大仓位。",
    "preference_alignment_summary": "认可核心成长定位，但建议阶段性目标低于用户偏好。",
    "recommended_action_bias": "prefer_pullback_add",
    "risk_budget": {
        "estimated_downside_pct": 0.18,
        "max_account_loss_pct": 0.036,
        "reason": "按 AI 最大仓位和下行情景估算账户损失预算。",
    },
    "key_reasons": ["趋势和基本面仍支持持有", "账户仓位未达到 AI 目标区间"],
    "key_risks": ["估值压缩", "财报或事件窗口波动"],
    "data_limitations": [],
    "prompt_key": "trade_decision_ai_policy_assessment",
    "prompt_source": "default_fallback",
}

AI_POLICY_ASSESSMENT_FALLBACK_EXAMPLE = {
    "status": "fallback",
    "ai_assessed_asset_role": "unknown",
    "ai_role_confidence": "low",
    "ai_recommended_min_position_pct": None,
    "ai_recommended_target_position_pct": None,
    "ai_recommended_max_position_pct": None,
    "ai_recommended_target_position_range_pct": None,
    "ai_position_stance": "unknown",
    "current_position_pct": 0.0,
    "gap_to_ai_target_pct": None,
    "gap_to_ai_max_pct": None,
    "challenge_level": "not_evaluated",
    "challenge_reason": "AI 投资策略评估失败，未使用 AI 仓位建议",
    "preference_alignment_summary": "未完成 AI 独立仓位评估。",
    "recommended_action_bias": "unknown",
    "risk_budget": {"estimated_downside_pct": None, "max_account_loss_pct": None, "reason": "未评估"},
    "key_reasons": [],
    "key_risks": [],
    "data_limitations": ["AI 投资策略评估失败，未使用 AI 仓位建议"],
    "prompt_key": "trade_decision_ai_policy_assessment",
    "prompt_source": "default_fallback",
}
