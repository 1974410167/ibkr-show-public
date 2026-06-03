"""LangGraph StateGraph for risk assessment.

Parallel fan-out/fan-in:
  START → build_account_risk_facts
        → [position_concentration | sector_theme_exposure | correlation | earnings_calendar_risk]  (parallel)
        → stress_test  (fan-in: waits for all 4, needs sector_theme_card)
        → risk_report_composer
        → persist_risk_assessment
        → END

All nodes receive deps via closure, not via state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.progress import instrument_graph_node
from app.agents.risk_assessment_graph.nodes import (
    make_build_account_risk_facts_node,
    make_correlation_node,
    make_earnings_calendar_risk_node,
    make_persist_risk_assessment_node,
    make_position_concentration_node,
    make_risk_report_composer_node,
    make_sector_theme_exposure_node,
    make_stress_test_node,
)

RISK_ASSESSMENT_GRAPH_NODES = [
    {"id": "build_account_risk_facts", "label": "账户风险事实"},
    {"id": "position_concentration", "label": "持仓集中度"},
    {"id": "sector_theme_exposure", "label": "行业主题暴露"},
    {"id": "correlation", "label": "相关性"},
    {"id": "earnings_calendar_risk", "label": "财报日历风险"},
    {"id": "stress_test", "label": "压力测试"},
    {"id": "risk_report_composer", "label": "生成报告"},
    {"id": "persist_risk_assessment", "label": "保存结果"},
]

RISK_ASSESSMENT_GRAPH_EDGES = [
    {"source": "build_account_risk_facts", "target": "position_concentration"},
    {"source": "build_account_risk_facts", "target": "sector_theme_exposure"},
    {"source": "build_account_risk_facts", "target": "correlation"},
    {"source": "build_account_risk_facts", "target": "earnings_calendar_risk"},
    {"source": "position_concentration", "target": "stress_test"},
    {"source": "sector_theme_exposure", "target": "stress_test"},
    {"source": "correlation", "target": "stress_test"},
    {"source": "earnings_calendar_risk", "target": "stress_test"},
    {"source": "stress_test", "target": "risk_report_composer"},
    {"source": "risk_report_composer", "target": "persist_risk_assessment"},
]
from app.agents.risk_assessment_graph.state import RiskAssessmentGraphState


@dataclass
class RiskAssessmentGraphDeps:
    account_facts_builder: Any
    repository: Any
    llm_service: Any
    mcp_adapter: Any = None
    monitoring_service: Any = None


def build_risk_assessment_graph(deps: RiskAssessmentGraphDeps) -> Any:
    graph = StateGraph(RiskAssessmentGraphState)

    # Add nodes
    graph.add_node("build_account_risk_facts", instrument_graph_node("build_account_risk_facts", make_build_account_risk_facts_node(deps)))
    graph.add_node("position_concentration", instrument_graph_node("position_concentration", make_position_concentration_node(deps)))
    graph.add_node("sector_theme_exposure", instrument_graph_node("sector_theme_exposure", make_sector_theme_exposure_node(deps)))
    graph.add_node("correlation", instrument_graph_node("correlation", make_correlation_node(deps)))
    graph.add_node("earnings_calendar_risk", instrument_graph_node("earnings_calendar_risk", make_earnings_calendar_risk_node(deps)))
    graph.add_node("stress_test", instrument_graph_node("stress_test", make_stress_test_node(deps)))
    graph.add_node("risk_report_composer", instrument_graph_node("risk_report_composer", make_risk_report_composer_node(deps)))
    graph.add_node("persist_risk_assessment", instrument_graph_node("persist_risk_assessment", make_persist_risk_assessment_node(deps)))

    # Fan-out: build_account_risk_facts → 4 parallel nodes
    graph.add_edge(START, "build_account_risk_facts")
    graph.add_edge("build_account_risk_facts", "position_concentration")
    graph.add_edge("build_account_risk_facts", "sector_theme_exposure")
    graph.add_edge("build_account_risk_facts", "correlation")
    graph.add_edge("build_account_risk_facts", "earnings_calendar_risk")

    # Fan-in: all 4 → stress_test
    graph.add_edge("position_concentration", "stress_test")
    graph.add_edge("sector_theme_exposure", "stress_test")
    graph.add_edge("correlation", "stress_test")
    graph.add_edge("earnings_calendar_risk", "stress_test")

    # Sequential tail
    graph.add_edge("stress_test", "risk_report_composer")
    graph.add_edge("risk_report_composer", "persist_risk_assessment")
    graph.add_edge("persist_risk_assessment", END)

    return graph.compile()
