from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.invariants import normalize_trade_review_output
from app.agents.output_schemas import TradeReviewOutput
from app.agents.trade_review_graph.prompts import TRADE_REVIEW_MAIN_SYSTEM_PROMPT as SYSTEM_PROMPT
from app.services.llm_service import LLMConfigError, LLMService
from app.services.trade_review_evidence import TradeReviewEvidenceBuilder
from app.services.trade_review_repository import TradeReviewRepository

SCORE_DIMENSIONS = {
    "return_result_score": 20,
    "relative_performance_score": 15,
    "entry_quality_score": 15,
    "exit_quality_score": 15,
    "position_sizing_score": 15,
    "holding_period_score": 5,
    "risk_control_score": 10,
    "decision_attribution_score": 5,
}

ALLOWED_MISTAKE_TAGS = {
    "CHASE_HIGH",
    "SELL_TOO_EARLY",
    "SELL_TOO_LATE",
    "PANIC_SELL",
    "POSITION_TOO_SMALL",
    "POSITION_TOO_LARGE",
    "MISSED_OPPORTUNITY",
    "NO_CLEAR_PLAN",
    "WEAK_RELATIVE_PERFORMANCE",
    "GOOD_ENTRY",
    "GOOD_EXIT",
    "GOOD_POSITION_SIZING",
    "GOOD_TREND_FOLLOW",
    "GOOD_RISK_CONTROL",
}

ALLOWED_RATINGS = {"excellent", "good", "average", "poor"}

class TradeReviewAgentError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def rating_for_score(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "average"
    return "poor"


def extract_json_object(raw_response: str) -> dict:
    """Deprecated: use app.agents.structured_output.extract_json_object instead."""
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        pass

    text = raw_response.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise TradeReviewAgentError("LLM_JSON_PARSE_FAILED", "LLM response is not valid JSON") from exc
    raise TradeReviewAgentError("LLM_JSON_PARSE_FAILED", "LLM response is not valid JSON")


class TradeReviewAgent:
    def __init__(
        self,
        evidence_builder: TradeReviewEvidenceBuilder,
        llm_service: LLMService,
        repository: TradeReviewRepository,
        prompt_service=None,
        trace_service=None,
        replay_service=None,
        monitoring_service=None,
    ) -> None:
        self.evidence_builder = evidence_builder
        self.llm_service = llm_service
        self.repository = repository
        self.prompt_service = prompt_service
        self.trace_service = trace_service
        self.replay_service = replay_service
        self._monitoring_service = monitoring_service
        self._graph_runner = None

    def _get_graph_runner(self):
        if self._graph_runner is None:
            from app.agents.trade_review_graph.runner import TradeReviewGraphRunner
            self._graph_runner = TradeReviewGraphRunner(
                evidence_builder=self.evidence_builder,
                llm_service=self.llm_service,
                repository=self.repository,
                prompt_service=self.prompt_service,
                trace_service=self.trace_service,
                replay_service=self.replay_service,
                monitoring_service=self._monitoring_service,
            )
        return self._graph_runner

    def health(self, longbridge_configured: bool) -> dict:
        return {
            "enabled": True,
            "llm_configured": self.llm_service.get_active_provider() is not None,
            "longbridge_configured": longbridge_configured,
            "message": "Trade review agent is ready"
            if self.llm_service.get_active_provider() is not None
            else "LLM active provider is missing",
        }

    def _ensure_llm_configured(self) -> None:
        if self.llm_service.get_active_provider() is None:
            raise LLMConfigError("No active LLM provider is configured")

    def generate_symbol_review(self, symbol: str, start_date: str | None, end_date: str | None, *, progress_reporter: Any = None) -> dict:
        self._ensure_llm_configured()
        kwargs = {"symbol": symbol, "start_date": start_date, "end_date": end_date}
        if progress_reporter is not None:
            kwargs["progress_reporter"] = progress_reporter
        return self._get_graph_runner().generate_symbol_review(**kwargs)

    def generate_single_trade_review(self, trade_id: str, *, progress_reporter: Any = None) -> dict:
        self._ensure_llm_configured()
        kwargs = {"trade_id": trade_id}
        if progress_reporter is not None:
            kwargs["progress_reporter"] = progress_reporter
        return self._get_graph_runner().generate_single_trade_review(**kwargs)

    def _run_tool_agent(
        self,
        *,
        review_type: str,
        symbol: str | None,
        trade_id: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> dict:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _review_tools(self) -> list[AgentTool]:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _default_plan(self, review_type: str) -> list[str]:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _default_tool_calls(
        self,
        review_type: str,
        symbol: str | None,
        trade_id: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict[str, Any]]:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _build_tool_user_prompt(self, review_type: str, symbol: str | None, trade_id: str | None, start_date: str | None, end_date: str | None) -> str:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _repair_tool_llm_response(
        self,
        review_type: str,
        symbol: str | None,
        trade_id: str | None,
        start_date: str | None,
        end_date: str | None,
        raw_response: str,
        trace: list[dict],
    ) -> str:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _run_and_save(self, evidence_pack: dict) -> dict:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _call_llm(self, evidence_pack: dict) -> str:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _repair_llm_response(self, evidence_pack: dict, raw_response: str) -> str:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def validate_llm_output(self, payload: dict, review_context: dict | None = None) -> dict:
        if not isinstance(payload, dict):
            raise TradeReviewAgentError("LLM_SCHEMA_INVALID", "LLM output must be an object")
        try:
            model = TradeReviewOutput.model_validate(payload)
            return normalize_trade_review_output(model.model_dump(), review_context=review_context)
        except ValidationError as exc:
            raise TradeReviewAgentError("LLM_SCHEMA_INVALID", str(exc)) from exc
        except ValueError as exc:
            code = "LLM_SCORE_INVALID" if "score must be between" in str(exc) else "LLM_SCHEMA_INVALID"
            raise TradeReviewAgentError(code, str(exc)) from exc

    def _build_user_prompt(self, evidence_pack: dict) -> str:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _evidence_for_llm(self, evidence_pack: dict) -> dict:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _review_start_date(self, evidence_pack: dict) -> str | None:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")

    def _review_end_date(self, evidence_pack: dict) -> str | None:
        """DEPRECATED: Use TradeReviewGraphRunner via generate_symbol_review/generate_single_trade_review."""
        raise RuntimeError("deprecated; use TradeReviewGraphRunner")
