"""LangGraph StateGraph for daily position review.

Parallel fan-out/fan-in:
  START → load_daily_review_context
        → select_focus_symbols
        → [symbol_cards | macro_card | portfolio_attribution | risk_watch]  (parallel)
        → build_card_pack
        → compose_daily_review
        → persist_daily_review
        → optional_email_summary
        → END

All nodes receive deps via closure, not via state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.agents.graph.progress import instrument_graph_node
from app.agents.daily_position_review_graph.nodes import (
    make_build_card_pack_node,
    make_compose_daily_review_node,
    make_load_daily_review_context_node,
    make_macro_card_node,
    make_optional_email_summary_node,
    make_persist_daily_review_node,
    make_portfolio_attribution_node,
    make_risk_watch_node,
    make_select_focus_symbols_node,
    make_symbol_cards_node,
)

DAILY_POSITION_REVIEW_GRAPH_NODES = [
    {"id": "load_daily_review_context", "label": "加载上下文"},
    {"id": "select_focus_symbols", "label": "选择重点标的"},
    {"id": "symbol_cards", "label": "个股卡片"},
    {"id": "macro_card", "label": "宏观卡片"},
    {"id": "portfolio_attribution", "label": "组合归因"},
    {"id": "risk_watch", "label": "风险观察"},
    {"id": "build_card_pack", "label": "构建卡片包"},
    {"id": "compose_daily_review", "label": "生成日报"},
    {"id": "persist_daily_review", "label": "保存结果"},
    {"id": "optional_email_summary", "label": "邮件摘要"},
]

DAILY_POSITION_REVIEW_GRAPH_EDGES = [
    {"source": "load_daily_review_context", "target": "select_focus_symbols"},
    {"source": "select_focus_symbols", "target": "symbol_cards"},
    {"source": "select_focus_symbols", "target": "macro_card"},
    {"source": "select_focus_symbols", "target": "portfolio_attribution"},
    {"source": "select_focus_symbols", "target": "risk_watch"},
    {"source": "symbol_cards", "target": "build_card_pack"},
    {"source": "macro_card", "target": "build_card_pack"},
    {"source": "portfolio_attribution", "target": "build_card_pack"},
    {"source": "risk_watch", "target": "build_card_pack"},
    {"source": "build_card_pack", "target": "compose_daily_review"},
    {"source": "compose_daily_review", "target": "persist_daily_review"},
    {"source": "persist_daily_review", "target": "optional_email_summary"},
]
from app.agents.daily_position_review_graph.state import DailyPositionReviewGraphState


@dataclass
class DailyPositionReviewGraphDeps:
    review_service: Any
    llm_service: Any
    repository: Any
    email_service: Any = None
    related_asset_service: Any = None
    longbridge_client: Any = None
    symbol_agent: Any = None
    macro_agent: Any = None
    prompt_service: Any = None
    monitoring_service: Any = None


def build_daily_position_review_graph(deps: DailyPositionReviewGraphDeps) -> Any:
    """Build and compile the daily position review LangGraph with parallel fan-out/fan-in."""
    graph = StateGraph(DailyPositionReviewGraphState)

    # Add nodes
    graph.add_node("load_daily_review_context", instrument_graph_node("load_daily_review_context", make_load_daily_review_context_node(deps)))
    graph.add_node("select_focus_symbols", instrument_graph_node("select_focus_symbols", make_select_focus_symbols_node(deps)))
    graph.add_node("symbol_cards", instrument_graph_node("symbol_cards", make_symbol_cards_node(deps)))
    graph.add_node("macro_card", instrument_graph_node("macro_card", make_macro_card_node(deps)))
    graph.add_node("portfolio_attribution", instrument_graph_node("portfolio_attribution", make_portfolio_attribution_node(deps)))
    graph.add_node("risk_watch", instrument_graph_node("risk_watch", make_risk_watch_node(deps)))
    graph.add_node("build_card_pack", instrument_graph_node("build_card_pack", make_build_card_pack_node(deps)))
    graph.add_node("compose_daily_review", instrument_graph_node("compose_daily_review", make_compose_daily_review_node(deps)))
    graph.add_node("persist_daily_review", instrument_graph_node("persist_daily_review", make_persist_daily_review_node(deps)))
    graph.add_node("optional_email_summary", instrument_graph_node("optional_email_summary", make_optional_email_summary_node(deps)))

    # Sequential: load → select
    graph.add_edge(START, "load_daily_review_context")
    graph.add_edge("load_daily_review_context", "select_focus_symbols")

    # Fan-out: select → 4 parallel nodes
    graph.add_edge("select_focus_symbols", "symbol_cards")
    graph.add_edge("select_focus_symbols", "macro_card")
    graph.add_edge("select_focus_symbols", "portfolio_attribution")
    graph.add_edge("select_focus_symbols", "risk_watch")

    # Fan-in: all 4 → build_card_pack
    graph.add_edge("symbol_cards", "build_card_pack")
    graph.add_edge("macro_card", "build_card_pack")
    graph.add_edge("portfolio_attribution", "build_card_pack")
    graph.add_edge("risk_watch", "build_card_pack")

    # Sequential tail
    graph.add_edge("build_card_pack", "compose_daily_review")
    graph.add_edge("compose_daily_review", "persist_daily_review")
    graph.add_edge("persist_daily_review", "optional_email_summary")
    graph.add_edge("optional_email_summary", END)

    return graph.compile()
