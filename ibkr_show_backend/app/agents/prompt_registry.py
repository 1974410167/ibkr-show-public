from __future__ import annotations

from dataclasses import dataclass

from app.agents.account_copilot.planner_prompts import SYSTEM_PROMPT as ACCOUNT_COPILOT_PLANNER_PROMPT
from app.services.daily_position_review_agent import SYSTEM_PROMPT_SUBAGENT_CARDS as DAILY_POSITION_REVIEW_MAIN_PROMPT
from app.services.daily_review_macro_evidence_agent import SYSTEM_PROMPT_MACRO_CARD
from app.services.daily_review_symbol_evidence_agent import SYSTEM_PROMPT_SYMBOL_CARD
from app.services.trade_decision_sub_agents import (
    EVENT_CATALYST_SYSTEM_PROMPT,
    FUNDAMENTAL_VALUATION_SYSTEM_PROMPT,
    MARKET_TREND_SYSTEM_PROMPT,
)
from app.services.trade_decision_debate_agents import (
    BEAR_REBUTTAL_PROMPT,
    BEAR_THESIS_PROMPT,
    BULL_REBUTTAL_PROMPT,
    BULL_THESIS_PROMPT,
    DEBATE_JUDGE_PROMPT,
)
from app.services.trade_decision_trade_plan_agent import TRADE_PLAN_PROMPT
from app.services.trade_decision_policy_assessment_agent import AI_POLICY_ASSESSMENT_PROMPT
from app.agents.trade_review_graph.prompts import (
    TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
    TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
    TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
)


@dataclass(frozen=True)
class PromptDefinitionRecord:
    prompt_key: str
    display_name: str
    module_name: str
    agent_name: str
    description: str
    default_content: str

    def to_dict(self) -> dict:
        return {
            "prompt_key": self.prompt_key,
            "display_name": self.display_name,
            "module_name": self.module_name,
            "agent_name": self.agent_name,
            "description": self.description,
            "default_content": self.default_content,
        }


PROMPT_DEFINITIONS: dict[str, PromptDefinitionRecord] = {
    "account_copilot_planner": PromptDefinitionRecord(
        prompt_key="account_copilot_planner",
        display_name="Account Copilot Planner",
        module_name="account_copilot",
        agent_name="planner",
        description="Account Copilot 多轮 ReAct planner 的 system prompt。",
        default_content=ACCOUNT_COPILOT_PLANNER_PROMPT,
    ),
    "daily_position_review_main": PromptDefinitionRecord(
        prompt_key="daily_position_review_main",
        display_name="Daily Position Review Main",
        module_name="daily_position_review",
        agent_name="main_agent",
        description="每日持仓复盘主 Agent 在证据卡片模式下使用的 system prompt。",
        default_content=DAILY_POSITION_REVIEW_MAIN_PROMPT,
    ),
    "daily_symbol_evidence_card": PromptDefinitionRecord(
        prompt_key="daily_symbol_evidence_card",
        display_name="Daily Symbol Evidence Card",
        module_name="daily_position_review",
        agent_name="symbol_evidence_card_agent",
        description="每日复盘单标的证据卡片子 Agent 的 system prompt。",
        default_content=SYSTEM_PROMPT_SYMBOL_CARD,
    ),
    "daily_macro_evidence_card": PromptDefinitionRecord(
        prompt_key="daily_macro_evidence_card",
        display_name="Daily Macro Evidence Card",
        module_name="daily_position_review",
        agent_name="macro_evidence_card_agent",
        description="每日复盘宏观证据卡片子 Agent 的 system prompt。",
        default_content=SYSTEM_PROMPT_MACRO_CARD,
    ),
    "trade_review_main": PromptDefinitionRecord(
        prompt_key="trade_review_main",
        display_name="Trade Review Main",
        module_name="trade_review",
        agent_name="main_agent",
        description="交易复盘主 Agent 的 system prompt。",
        default_content=TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
    ),
    "trade_review_behavior_pattern": PromptDefinitionRecord(
        prompt_key="trade_review_behavior_pattern",
        display_name="Trade Review Behavior Pattern",
        module_name="trade_review",
        agent_name="behavior_pattern_sub_agent",
        description="交易行为模式分析子 Agent 的 system prompt。",
        default_content=TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
    ),
    "trade_review_opportunity_cost": PromptDefinitionRecord(
        prompt_key="trade_review_opportunity_cost",
        display_name="Trade Review Opportunity Cost",
        module_name="trade_review",
        agent_name="opportunity_cost_sub_agent",
        description="机会成本分析子 Agent 的 system prompt。",
        default_content=TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
    ),
    "trade_decision_market_trend": PromptDefinitionRecord(
        prompt_key="trade_decision_market_trend",
        display_name="Trade Decision Market Trend",
        module_name="trade_decision",
        agent_name="market_trend_sub_agent",
        description="交易决策市场趋势子 Agent 的 system prompt。",
        default_content=MARKET_TREND_SYSTEM_PROMPT,
    ),
    "trade_decision_fundamental_valuation": PromptDefinitionRecord(
        prompt_key="trade_decision_fundamental_valuation",
        display_name="Trade Decision Fundamental Valuation",
        module_name="trade_decision",
        agent_name="fundamental_valuation_sub_agent",
        description="交易决策基本面估值子 Agent 的 system prompt。",
        default_content=FUNDAMENTAL_VALUATION_SYSTEM_PROMPT,
    ),
    "trade_decision_event_catalyst": PromptDefinitionRecord(
        prompt_key="trade_decision_event_catalyst",
        display_name="Trade Decision Event Catalyst",
        module_name="trade_decision",
        agent_name="event_catalyst_sub_agent",
        description="交易决策事件催化子 Agent 的 system prompt。",
        default_content=EVENT_CATALYST_SYSTEM_PROMPT,
    ),
    "trade_decision_bull_thesis": PromptDefinitionRecord(
        prompt_key="trade_decision_bull_thesis",
        display_name="Trade Decision Bull Thesis",
        module_name="trade_decision",
        agent_name="bull_thesis_sub_agent",
        description="交易决策多头立论子 Agent 的 system prompt。",
        default_content=BULL_THESIS_PROMPT,
    ),
    "trade_decision_bear_thesis": PromptDefinitionRecord(
        prompt_key="trade_decision_bear_thesis",
        display_name="Trade Decision Bear Thesis",
        module_name="trade_decision",
        agent_name="bear_thesis_sub_agent",
        description="交易决策空头/谨慎立论子 Agent 的 system prompt。",
        default_content=BEAR_THESIS_PROMPT,
    ),
    "trade_decision_bull_rebuttal": PromptDefinitionRecord(
        prompt_key="trade_decision_bull_rebuttal",
        display_name="Trade Decision Bull Rebuttal",
        module_name="trade_decision",
        agent_name="bull_rebuttal_sub_agent",
        description="交易决策多头反驳子 Agent 的 system prompt。",
        default_content=BULL_REBUTTAL_PROMPT,
    ),
    "trade_decision_bear_rebuttal": PromptDefinitionRecord(
        prompt_key="trade_decision_bear_rebuttal",
        display_name="Trade Decision Bear Rebuttal",
        module_name="trade_decision",
        agent_name="bear_rebuttal_sub_agent",
        description="交易决策空头/谨慎反驳子 Agent 的 system prompt。",
        default_content=BEAR_REBUTTAL_PROMPT,
    ),
    "trade_decision_debate_judge": PromptDefinitionRecord(
        prompt_key="trade_decision_debate_judge",
        display_name="Trade Decision Debate Judge",
        module_name="trade_decision",
        agent_name="debate_judge_sub_agent",
        description="交易决策多空辩论裁判子 Agent 的 system prompt。",
        default_content=DEBATE_JUDGE_PROMPT,
    ),
    "trade_decision_ai_policy_assessment": PromptDefinitionRecord(
        prompt_key="trade_decision_ai_policy_assessment",
        display_name="Trade Decision AI Policy Assessment",
        module_name="trade_decision",
        agent_name="ai_policy_assessment_sub_agent",
        description="交易决策 AI 投资策略/仓位评估子 Agent 的 system prompt。",
        default_content=AI_POLICY_ASSESSMENT_PROMPT,
    ),
    "trade_decision_trade_plan": PromptDefinitionRecord(
        prompt_key="trade_decision_trade_plan",
        display_name="Trade Decision Trade Plan",
        module_name="trade_decision",
        agent_name="trade_plan_sub_agent",
        description="交易决策交易计划子 Agent 的 system prompt。",
        default_content=TRADE_PLAN_PROMPT,
    ),
}


def list_prompt_definitions() -> list[PromptDefinitionRecord]:
    return list(PROMPT_DEFINITIONS.values())


def get_prompt_definition(prompt_key: str) -> PromptDefinitionRecord | None:
    return PROMPT_DEFINITIONS.get(prompt_key)
