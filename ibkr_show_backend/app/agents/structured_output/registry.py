"""Structured Output Contract Registry.

Provides a static registry of all StructuredOutputContract specs for auditing,
documentation, and monitoring display. Does NOT require runtime instantiation
of contracts (some need fallback_builder or business context).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StructuredOutputContractSpec:
    name: str
    agent_name: str
    node_name: str
    output_model_name: str
    module_path: str
    builder_name: str | None
    schema_hint_available: bool
    examples_count: int
    max_repair_attempts: int
    repair_enabled: bool
    fallback_enabled: bool
    dynamic_fallback: bool
    owner: str
    description: str


def get_structured_output_contract_specs() -> list[StructuredOutputContractSpec]:
    return list(_REGISTRY)


def get_contract_spec_by_name(name: str) -> StructuredOutputContractSpec | None:
    return _INDEX.get(name)


def group_contract_specs_by_agent() -> dict[str, list[StructuredOutputContractSpec]]:
    grouped: dict[str, list[StructuredOutputContractSpec]] = {}
    for spec in _REGISTRY:
        grouped.setdefault(spec.agent_name, []).append(spec)
    return grouped


_REGISTRY: list[StructuredOutputContractSpec] = [
    # Account Copilot
    StructuredOutputContractSpec(
        name="account_copilot_planner",
        agent_name="account_copilot",
        node_name="planner",
        output_model_name="CopilotPlannerAction",
        module_path="app.agents.account_copilot.planner_schema",
        builder_name=None,
        schema_hint_available=True,
        examples_count=3,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="account_copilot",
        description="Account Copilot ReAct planner action selection: call_tool / final_answer / request_skill_approval.",
    ),
    StructuredOutputContractSpec(
        name="account_copilot_after_approval_final_answer",
        agent_name="account_copilot",
        node_name="after_approval_final_answer",
        output_model_name="CopilotFinalAnswerAfterApproval",
        module_path="app.agents.account_copilot.planner_schema",
        builder_name=None,
        schema_hint_available=True,
        examples_count=1,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="account_copilot",
        description="Account Copilot final answer after skill approval: final_answer, confidence, data_limitations, evidence_used.",
    ),
    # Trade Decision
    StructuredOutputContractSpec(
        name="trade_decision_market_trend",
        agent_name="trade_decision",
        node_name="market_trend",
        output_model_name="MarketTrendLLMOutput",
        module_path="app.agents.trade_decision_structured_outputs",
        builder_name="build_market_trend_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_decision",
        description="Market trend sub-agent output: price_trend, score 0-15, volatility, benchmark comparison.",
    ),
    StructuredOutputContractSpec(
        name="trade_decision_fundamental_valuation",
        agent_name="trade_decision",
        node_name="fundamental_valuation",
        output_model_name="FundamentalValuationLLMOutput",
        module_path="app.agents.trade_decision_structured_outputs",
        builder_name="build_fundamental_valuation_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_decision",
        description="Fundamental valuation sub-agent output: PE, market cap, revenue growth, score 0-35.",
    ),
    StructuredOutputContractSpec(
        name="trade_decision_event_catalyst",
        agent_name="trade_decision",
        node_name="event_catalyst",
        output_model_name="EventCatalystLLMOutput",
        module_path="app.agents.trade_decision_structured_outputs",
        builder_name="build_event_catalyst_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_decision",
        description="Event catalyst sub-agent output: sentiment, catalyst_strength, key_events, score 0-5.",
    ),
    StructuredOutputContractSpec(
        name="trade_decision_ai_policy_assessment",
        agent_name="trade_decision",
        node_name="ai_policy_assessment",
        output_model_name="AiPolicyAssessmentOutput",
        module_path="app.agents.trade_decision_structured_outputs",
        builder_name="build_ai_policy_assessment_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_decision",
        description="AI policy assessment sub-agent output: independent role, target range, max position, challenge and action bias.",
    ),
    # Daily Position Review
    StructuredOutputContractSpec(
        name="daily_review_symbol_evidence_card",
        agent_name="daily_position_review",
        node_name="symbol_evidence_card",
        output_model_name="SymbolEvidenceLLMOutput",
        module_path="app.agents.daily_review_structured_outputs",
        builder_name="build_symbol_evidence_contract",
        schema_hint_available=True,
        examples_count=1,
        max_repair_attempts=2,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="daily_review",
        description="Daily review symbol evidence card: account_impact, price_action, news, valuation, earnings, technical, cross_asset.",
    ),
    StructuredOutputContractSpec(
        name="daily_review_macro_evidence_card",
        agent_name="daily_position_review",
        node_name="macro_evidence_card",
        output_model_name="MacroEvidenceLLMOutput",
        module_path="app.agents.daily_review_structured_outputs",
        builder_name="build_macro_evidence_contract",
        schema_hint_available=True,
        examples_count=1,
        max_repair_attempts=2,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="daily_review",
        description="Daily review macro evidence card: market_regime, sector_context, risk_sentiment, tech_sentiment.",
    ),
    StructuredOutputContractSpec(
        name="daily_position_review_main",
        agent_name="daily_position_review",
        node_name="compose_daily_review",
        output_model_name="DailyPositionReviewOutput",
        module_path="app.agents.daily_review_structured_outputs",
        builder_name="build_daily_position_review_main_contract",
        schema_hint_available=True,
        examples_count=1,
        max_repair_attempts=3,
        repair_enabled=True,
        fallback_enabled=True,
        dynamic_fallback=True,
        owner="daily_review",
        description="Daily position review main output: summary, attribution, contributors, drags, watchlist. Has dynamic fallback.",
    ),
    # Trade Review
    StructuredOutputContractSpec(
        name="trade_review_behavior_pattern",
        agent_name="trade_review",
        node_name="behavior_pattern",
        output_model_name="BehaviorPatternLLMOutput",
        module_path="app.agents.trade_review_structured_outputs",
        builder_name="build_trade_review_behavior_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_review",
        description="Trade review behavior pattern analysis: behavior_score, patterns, mistake_tags.",
    ),
    StructuredOutputContractSpec(
        name="trade_review_opportunity_cost",
        agent_name="trade_review",
        node_name="opportunity_cost",
        output_model_name="OpportunityCostLLMOutput",
        module_path="app.agents.trade_review_structured_outputs",
        builder_name="build_trade_review_opportunity_contract",
        schema_hint_available=True,
        examples_count=2,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        dynamic_fallback=False,
        owner="trade_review",
        description="Trade review opportunity cost analysis: benchmark_comparison, missed_upside, avoided_downside.",
    ),
    StructuredOutputContractSpec(
        name="trade_review_main",
        agent_name="trade_review",
        node_name="compose_trade_review",
        output_model_name="TradeReviewMainLLMOutput",
        module_path="app.agents.trade_review_structured_outputs",
        builder_name="build_trade_review_main_contract",
        schema_hint_available=True,
        examples_count=1,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=True,
        dynamic_fallback=True,
        owner="trade_review",
        description="Trade review main output: overall_score, rating, score_detail, strengths, weaknesses. Has dynamic fallback.",
    ),
]


_INDEX: dict[str, StructuredOutputContractSpec] = {spec.name: spec for spec in _REGISTRY}
