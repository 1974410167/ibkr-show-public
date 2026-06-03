"""Risk Assessment Agent - service façade."""

from __future__ import annotations

from typing import Any

from app.agents.graph.result_contract import get_public_data_runtime_status
from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner
from app.agents.versions import RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH, RISK_ASSESSMENT_GRAPH_VERSION


class RiskAssessmentAgentError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class RiskAssessmentAgent:

    def __init__(
        self,
        account_facts_builder: Any,
        llm_service: Any,
        repository: Any,
        mcp_adapter: Any = None,
        monitoring_service: Any = None,
    ) -> None:
        self._account_facts_builder = account_facts_builder
        self._llm_service = llm_service
        self._repository = repository
        self._mcp_adapter = mcp_adapter
        self._monitoring_service = monitoring_service
        self._graph_runner: RiskAssessmentGraphRunner | None = None

    def _get_graph_runner(self) -> RiskAssessmentGraphRunner:
        if self._graph_runner is None:
            self._graph_runner = RiskAssessmentGraphRunner(
                account_facts_builder=self._account_facts_builder,
                repository=self._repository,
                llm_service=self._llm_service,
                mcp_adapter=self._mcp_adapter,
                monitoring_service=self._monitoring_service,
            )
        return self._graph_runner

    def analyze(self, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        if progress_reporter is not None:
            return self._get_graph_runner().analyze(question=question, progress_reporter=progress_reporter)
        return self._get_graph_runner().analyze(question=question)

    def health(
        self,
        longbridge_configured: bool = False,
    ) -> dict:
        errors: list[str] = []
        try:
            llm_configured = self._llm_service.get_active_provider() is not None
        except Exception as exc:
            llm_configured = False
            errors.append(f"llm_status_error: {str(exc)[:120]}")

        try:
            public_status = get_public_data_runtime_status(
                mcp_adapter=self._mcp_adapter,
                longbridge_sdk_configured=longbridge_configured,
            )
        except Exception as exc:
            errors.append(f"public_data_status_error: {str(exc)[:120]}")
            public_status = get_public_data_runtime_status(longbridge_sdk_configured=longbridge_configured)

        message = "Risk assessment agent is ready" if llm_configured and not errors else "; ".join(errors) or "LLM active provider is missing"
        return {
            "enabled": bool(llm_configured and not errors),
            "llm_configured": llm_configured,
            "account_data_source": "IBKR_ONLY",
            "agent_mode": RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
            "graph_version": RISK_ASSESSMENT_GRAPH_VERSION,
            "message": message,
            **public_status,
        }
