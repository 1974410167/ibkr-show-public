"""LangGraph StateGraph for trade decision analysis.

Parallel fan-out/fan-in:
  START → build_account_facts
        → [account_fit | market_trend | fundamental_valuation | event_catalyst | market_event_context]  (parallel)
        → build_card_pack  (fan-in: waits for all 5)
        → [bull_thesis | bear_thesis]
        → [bull_rebuttal | bear_rebuttal]
        → debate_judge
        → trade_plan  (also derives compatibility risk_reward_card)
        → compose_decision
        → persist_decision
        → END

All nodes receive deps via closure, not via state.
Risk/reward is now generated inside trade_plan.risk_reward_assessment and
materialized as a compatibility RiskRewardCard after trade_plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.progress import instrument_graph_node
from app.agents.trade_decision_graph.nodes import (
    make_account_fit_node,
    make_bear_rebuttal_node,
    make_bear_thesis_node,
    make_bull_rebuttal_node,
    make_bull_thesis_node,
    make_build_account_facts_node,
    make_build_card_pack_node,
    make_compose_decision_node,
    make_debate_judge_node,
    make_event_catalyst_node,
    make_fundamental_valuation_node,
    make_market_event_context_node,
    make_market_trend_node,
    make_persist_decision_node,
    make_trade_plan_node,
)
from app.agents.trade_decision_graph.state import TradeDecisionGraphState
from app.services.llm_service import LLMService
from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
from app.services.trade_decision_account_facts import TradeDecisionAccountFactsBuilder
from app.services.trade_decision_composer import TradeDecisionComposer
from app.services.trade_decision_repository import TradeDecisionRepository

TRADE_DECISION_GRAPH_NODES = [
    {"id": "build_account_facts", "label": "账户事实"},
    {"id": "account_fit", "label": "账户适配"},
    {"id": "market_trend", "label": "市场趋势"},
    {"id": "fundamental_valuation", "label": "基本面估值"},
    {"id": "event_catalyst", "label": "事件催化"},
    {"id": "market_event_context", "label": "重点事件"},
    {"id": "build_card_pack", "label": "构建卡片"},
    {"id": "bull_thesis", "label": "多头立论"},
    {"id": "bear_thesis", "label": "空头立论"},
    {"id": "bull_rebuttal", "label": "多头反驳"},
    {"id": "bear_rebuttal", "label": "空头反驳"},
    {"id": "debate_judge", "label": "辩论裁判"},
    {"id": "trade_plan", "label": "交易计划"},
    {"id": "compose_decision", "label": "生成决策"},
    {"id": "persist_decision", "label": "保存结果"},
]

TRADE_DECISION_GRAPH_EDGES = [
    {"source": "build_account_facts", "target": "account_fit"},
    {"source": "build_account_facts", "target": "market_trend"},
    {"source": "build_account_facts", "target": "fundamental_valuation"},
    {"source": "build_account_facts", "target": "event_catalyst"},
    {"source": "build_account_facts", "target": "market_event_context"},
    {"source": "account_fit", "target": "build_card_pack"},
    {"source": "market_trend", "target": "build_card_pack"},
    {"source": "fundamental_valuation", "target": "build_card_pack"},
    {"source": "event_catalyst", "target": "build_card_pack"},
    {"source": "market_event_context", "target": "build_card_pack"},
    {"source": "build_card_pack", "target": "bull_thesis"},
    {"source": "build_card_pack", "target": "bear_thesis"},
    {"source": "bull_thesis", "target": "bull_rebuttal"},
    {"source": "bear_thesis", "target": "bull_rebuttal"},
    {"source": "bull_thesis", "target": "bear_rebuttal"},
    {"source": "bear_thesis", "target": "bear_rebuttal"},
    {"source": "bull_rebuttal", "target": "debate_judge"},
    {"source": "bear_rebuttal", "target": "debate_judge"},
    {"source": "debate_judge", "target": "trade_plan"},
    {"source": "trade_plan", "target": "compose_decision"},
    {"source": "compose_decision", "target": "persist_decision"},
]


@dataclass
class TradeDecisionGraphDeps:
    account_facts_builder: TradeDecisionAccountFactsBuilder
    llm_service: LLMService
    repository: TradeDecisionRepository
    mcp_adapter: LongbridgeMCPToolAdapter | None
    prompt_service: Any | None = None
    monitoring_service: Any | None = None
    market_event_query_service: Any | None = None


def build_trade_decision_graph(deps: TradeDecisionGraphDeps) -> Any:
    """Build and compile the trade decision LangGraph with parallel fan-out/fan-in."""
    graph = StateGraph(TradeDecisionGraphState)

    # Add nodes — each factory closes over deps
    graph.add_node("build_account_facts", instrument_graph_node("build_account_facts", make_build_account_facts_node(deps)))
    graph.add_node("account_fit", instrument_graph_node("account_fit", make_account_fit_node(deps)))
    graph.add_node("market_trend", instrument_graph_node("market_trend", make_market_trend_node(deps)))
    graph.add_node("fundamental_valuation", instrument_graph_node("fundamental_valuation", make_fundamental_valuation_node(deps)))
    graph.add_node("event_catalyst", instrument_graph_node("event_catalyst", make_event_catalyst_node(deps)))
    graph.add_node("market_event_context", instrument_graph_node("market_event_context", make_market_event_context_node(deps)))
    graph.add_node("build_card_pack", instrument_graph_node("build_card_pack", make_build_card_pack_node(deps)))
    graph.add_node("bull_thesis", instrument_graph_node("bull_thesis", make_bull_thesis_node(deps)))
    graph.add_node("bear_thesis", instrument_graph_node("bear_thesis", make_bear_thesis_node(deps)))
    graph.add_node("bull_rebuttal", instrument_graph_node("bull_rebuttal", make_bull_rebuttal_node(deps)))
    graph.add_node("bear_rebuttal", instrument_graph_node("bear_rebuttal", make_bear_rebuttal_node(deps)))
    graph.add_node("debate_judge", instrument_graph_node("debate_judge", make_debate_judge_node(deps)))
    graph.add_node("trade_plan", instrument_graph_node("trade_plan", make_trade_plan_node(deps)))
    graph.add_node("compose_decision", instrument_graph_node("compose_decision", make_compose_decision_node(deps)))
    graph.add_node("persist_decision", instrument_graph_node("persist_decision", make_persist_decision_node(deps)))

    # Fan-out: build_account_facts → 5 parallel evidence nodes
    graph.add_edge(START, "build_account_facts")
    graph.add_edge("build_account_facts", "account_fit")
    graph.add_edge("build_account_facts", "market_trend")
    graph.add_edge("build_account_facts", "fundamental_valuation")
    graph.add_edge("build_account_facts", "event_catalyst")
    graph.add_edge("build_account_facts", "market_event_context")

    # Fan-in: all 5 → build_card_pack (LangGraph auto-waits for all predecessors)
    graph.add_edge("account_fit", "build_card_pack")
    graph.add_edge("market_trend", "build_card_pack")
    graph.add_edge("fundamental_valuation", "build_card_pack")
    graph.add_edge("event_catalyst", "build_card_pack")
    graph.add_edge("market_event_context", "build_card_pack")

    # Sequential tail
    graph.add_edge("build_card_pack", "bull_thesis")
    graph.add_edge("build_card_pack", "bear_thesis")
    graph.add_edge("bull_thesis", "bull_rebuttal")
    graph.add_edge("bear_thesis", "bull_rebuttal")
    graph.add_edge("bull_thesis", "bear_rebuttal")
    graph.add_edge("bear_thesis", "bear_rebuttal")
    graph.add_edge("bull_rebuttal", "debate_judge")
    graph.add_edge("bear_rebuttal", "debate_judge")
    graph.add_edge("debate_judge", "trade_plan")
    graph.add_edge("trade_plan", "compose_decision")
    graph.add_edge("compose_decision", "persist_decision")
    graph.add_edge("persist_decision", END)

    return graph.compile()
