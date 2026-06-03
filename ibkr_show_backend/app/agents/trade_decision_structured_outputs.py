from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
