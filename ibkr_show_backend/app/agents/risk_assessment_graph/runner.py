"""RiskAssessmentGraphRunner - thin runner over the LangGraph."""

from __future__ import annotations

from typing import Any

from app.agents.graph.result_contract import build_agent_metadata
from app.agents.graph.trace import now_iso
from app.agents.risk_assessment_graph.graph import (
    RiskAssessmentGraphDeps,
    build_risk_assessment_graph,
)
from app.agents.versions import (
    RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
    RISK_ASSESSMENT_AGENT_VERSION,
    RISK_ASSESSMENT_CARD_SCHEMA_VERSION,
    RISK_ASSESSMENT_EVIDENCE_BUILDER_VERSION,
    RISK_ASSESSMENT_GRAPH_VERSION,
    RISK_ASSESSMENT_PROMPT_VERSION,
    RISK_ASSESSMENT_TOOLSET_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
)


class RiskAssessmentGraphRunner:

    def __init__(
        self,
        account_facts_builder: Any,
        repository: Any,
        llm_service: Any,
        mcp_adapter: Any = None,
        monitoring_service: Any = None,
    ) -> None:
        self.deps = RiskAssessmentGraphDeps(
            account_facts_builder=account_facts_builder,
            repository=repository,
            llm_service=llm_service,
            mcp_adapter=mcp_adapter,
            monitoring_service=monitoring_service,
        )
        self.graph = build_risk_assessment_graph(self.deps)

    def _initial_state(self, question: str | None = None, progress_reporter: Any = None) -> dict:
        state = {
            "assessment_type": "portfolio_risk",
            "user_question": question,
            "started_at": now_iso(),
            "errors": [],
            "warnings": [],
            "data_limitations": [],
            "node_traces": [],
            "fallback_used": False,
            "fallback_reason": None,
            "metadata": {},
        }
        if progress_reporter is not None:
            state["progress_reporter"] = progress_reporter
        return state

    def analyze(self, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        initial_state = self._initial_state(question, progress_reporter)
        try:
            final_state = self.graph.invoke(initial_state)
            saved = final_state.get("saved_document")
            if saved:
                return saved
            errors = final_state.get("errors") or []
            reason = "; ".join(str(item) for item in errors[-3:]) or "graph completed without saving"
            return self._build_fallback(question, reason)
        except Exception as exc:
            if progress_reporter is not None:
                try:
                    progress_reporter.graph_failed(str(exc))
                except Exception:
                    pass
            return self._build_fallback(question, str(exc))

    def _build_fallback(self, question: str | None, reason: str, *, persist: bool = True) -> dict:
        now = now_iso()
        base_metadata = build_metadata(
            agent_version=RISK_ASSESSMENT_AGENT_VERSION,
            prompt_version=RISK_ASSESSMENT_PROMPT_VERSION,
            schema_version=OUTPUT_SCHEMA_VERSION,
            toolset_version=RISK_ASSESSMENT_TOOLSET_VERSION,
            evidence_builder_version=RISK_ASSESSMENT_EVIDENCE_BUILDER_VERSION,
            agent_mode=RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
        )
        metadata = build_agent_metadata(
            base_metadata=base_metadata,
            agent_mode=RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
            graph_version=RISK_ASSESSMENT_GRAPH_VERSION,
            card_schema_version=RISK_ASSESSMENT_CARD_SCHEMA_VERSION,
            account_data_source="IBKR_ONLY",
            public_market_data_source="LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
            fallback_used=True,
            fallback_reason=reason[:200],
        )

        document: dict = {
            "id": f"risk-fallback-{now.replace(':', '').replace('-', '').replace('.', '')}",
            "assessment_type": "portfolio_risk",
            "overall_risk_score": 50,
            "risk_level": "medium",
            "risk_summary": f"风险评估失败，保守评估为中等风险：{reason[:100]}",
            "score_detail": {},
            "key_risks": [f"分析流程异常：{reason[:100]}"],
            "suggested_actions": ["重新运行风险评估"],
            "concentration_warnings": [],
            "event_warnings": [],
            "stress_test_summary": {},
            "data_limitations": [f"graph_failed: {reason[:200]}", "run_trace_empty_due_to_graph_failure"],
            "evidence_used": [],
            "confidence": "low",
            "card_pack": {},
            "run_trace": [],
            "run_trace_summary": {},
            "metadata": metadata,
            "fallback_used": True,
            "fallback_reason": reason[:200],
            "created_at": now,
            "updated_at": now,
        }
        if not persist or self.deps.repository is None:
            return document
        try:
            return self.deps.repository.save_assessment(document)
        except Exception as exc:
            document["data_limitations"].append(f"save_failed: {str(exc)[:200]}")
            document["fallback_reason"] = f"{reason[:120]}; save_failed: {str(exc)[:70]}"
            document["metadata"]["fallback_reason"] = document["fallback_reason"]
            return document
