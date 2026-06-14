"""LangGraph StateGraph for trade review analysis.

Parallel fan-out/fan-in:
  START → load_trade_facts
        → [position | account | market | benchmark | event]  (parallel)
        → build_trade_review_context  (fan-in: waits for all 5)
        → [behavior_pattern | opportunity_cost]  (parallel)
        → compose_trade_review  (fan-in: waits for both)
        → persist_trade_review
        → END

All nodes receive deps via closure, not via state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.progress import instrument_graph_node
from app.agents.trade_review_graph.nodes import (
    make_account_node,
    make_behavior_pattern_node,
    make_benchmark_node,
    make_build_trade_review_context_node,
    make_compose_trade_review_node,
    make_event_node,
    make_load_trade_facts_node,
    make_market_node,
    make_opportunity_cost_node,
    make_persist_trade_review_node,
    make_position_node,
)
from app.agents.trade_review_graph.state import TradeReviewGraphState
from app.services.trade_review_evidence import TradeReviewEvidenceBuilder
from app.services.trade_review_repository import TradeReviewRepository
from app.services.llm_service import LLMService

TRADE_REVIEW_GRAPH_NODES = [
    {"id": "load_trade_facts", "label": "交易事实"},
    {"id": "position_evidence", "label": "持仓证据"},
    {"id": "account_evidence", "label": "账户证据"},
    {"id": "market_evidence", "label": "市场证据"},
    {"id": "benchmark_evidence", "label": "基准证据"},
    {"id": "event_evidence", "label": "事件证据"},
    {"id": "build_trade_review_context", "label": "构建上下文"},
    {"id": "behavior_pattern", "label": "行为模式"},
    {"id": "opportunity_cost", "label": "机会成本"},
    {"id": "compose_trade_review", "label": "生成复盘"},
    {"id": "persist_trade_review", "label": "保存结果"},
]

TRADE_REVIEW_GRAPH_EDGES = [
    {"source": "load_trade_facts", "target": "position_evidence"},
    {"source": "load_trade_facts", "target": "account_evidence"},
    {"source": "load_trade_facts", "target": "market_evidence"},
    {"source": "load_trade_facts", "target": "benchmark_evidence"},
    {"source": "load_trade_facts", "target": "event_evidence"},
    {"source": "position_evidence", "target": "build_trade_review_context"},
    {"source": "account_evidence", "target": "build_trade_review_context"},
    {"source": "market_evidence", "target": "build_trade_review_context"},
    {"source": "benchmark_evidence", "target": "build_trade_review_context"},
    {"source": "event_evidence", "target": "build_trade_review_context"},
    {"source": "build_trade_review_context", "target": "behavior_pattern"},
    {"source": "build_trade_review_context", "target": "opportunity_cost"},
    {"source": "behavior_pattern", "target": "compose_trade_review"},
    {"source": "opportunity_cost", "target": "compose_trade_review"},
    {"source": "compose_trade_review", "target": "persist_trade_review"},
]


@dataclass
class TradeReviewGraphDeps:
    evidence_builder: TradeReviewEvidenceBuilder
    llm_service: LLMService
    repository: TradeReviewRepository
    mcp_adapter: Any | None = None
    prompt_service: Any | None = None
    monitoring_service: Any | None = None
    investment_policy_service: Any | None = None


def build_trade_review_graph(deps: TradeReviewGraphDeps) -> Any:
    """Build and compile the trade review LangGraph with parallel fan-out/fan-in."""
    graph = StateGraph(TradeReviewGraphState)

    # Add nodes — each factory closes over deps
    graph.add_node("load_trade_facts", instrument_graph_node("load_trade_facts", make_load_trade_facts_node(deps)))
    graph.add_node("position_evidence", instrument_graph_node("position_evidence", make_position_node(deps)))
    graph.add_node("account_evidence", instrument_graph_node("account_evidence", make_account_node(deps)))
    graph.add_node("market_evidence", instrument_graph_node("market_evidence", make_market_node(deps)))
    graph.add_node("benchmark_evidence", instrument_graph_node("benchmark_evidence", make_benchmark_node(deps)))
    graph.add_node("event_evidence", instrument_graph_node("event_evidence", make_event_node(deps)))
    graph.add_node("build_trade_review_context", instrument_graph_node("build_trade_review_context", make_build_trade_review_context_node(deps)))
    graph.add_node("behavior_pattern", instrument_graph_node("behavior_pattern", make_behavior_pattern_node(deps)))
    graph.add_node("opportunity_cost", instrument_graph_node("opportunity_cost", make_opportunity_cost_node(deps)))
    graph.add_node("compose_trade_review", instrument_graph_node("compose_trade_review", make_compose_trade_review_node(deps)))
    graph.add_node("persist_trade_review", instrument_graph_node("persist_trade_review", make_persist_trade_review_node(deps)))

    # Fan-out 1: load_trade_facts → 5 parallel evidence nodes
    graph.add_edge(START, "load_trade_facts")
    graph.add_edge("load_trade_facts", "position_evidence")
    graph.add_edge("load_trade_facts", "account_evidence")
    graph.add_edge("load_trade_facts", "market_evidence")
    graph.add_edge("load_trade_facts", "benchmark_evidence")
    graph.add_edge("load_trade_facts", "event_evidence")

    # Fan-in 1: all 5 → build_trade_review_context.
    # Use explicit list fan-in so graph execution cannot be interpreted as
    # "any predecessor may trigger downstream" by LangGraph version changes.
    graph.add_edge(
        [
            "position_evidence",
            "account_evidence",
            "market_evidence",
            "benchmark_evidence",
            "event_evidence",
        ],
        "build_trade_review_context",
    )

    # Fan-out 2: build_trade_review_context → 2 parallel analysis nodes
    graph.add_edge("build_trade_review_context", "behavior_pattern")
    graph.add_edge("build_trade_review_context", "opportunity_cost")

    # Fan-in 2: both → compose_trade_review
    graph.add_edge(["behavior_pattern", "opportunity_cost"], "compose_trade_review")

    # Sequential tail
    graph.add_edge("compose_trade_review", "persist_trade_review")
    graph.add_edge("persist_trade_review", END)

    return graph.compile()
