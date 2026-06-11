"""
TradeDecisionAgent - thin facade over LangGraph runner.

Main entry points:
  - analyze_trade_decision(symbol)
  - analyze_entry(symbol, question)
  - analyze_holding(symbol, question)
  - health()
"""

from __future__ import annotations

from typing import Any

from app.agents.evidence_summary import build_evidence_summary
from app.agents.graph.result_contract import get_public_data_runtime_status
from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner
from app.agents.versions import (
    TRADE_DECISION_AGENT_VERSION,
    TRADE_DECISION_PROMPT_VERSION,
    TRADE_DECISION_TOOLSET_VERSION,
    TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
    TRADE_DECISION_AGENT_MODE_LANGGRAPH,
    TRADE_DECISION_GRAPH_VERSION,
    TRADE_DECISION_CARD_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
)
from app.services.llm_service import LLMConfigError, LLMService
from app.services.longbridge_service import normalize_longbridge_symbol
from app.services.trade_decision_repository import TradeDecisionRepository
from app.services.trade_decision_account_facts import TradeDecisionAccountFactsBuilder
from app.services.longbridge_oauth_token_service import LongbridgeOAuthTokenService
from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient, get_longbridge_mcp_config


class TradeDecisionAgentError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class TradeDecisionAgent:
    def __init__(
        self,
        evidence_builder: Any,
        llm_service: LLMService,
        repository: TradeDecisionRepository,
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
        self.monitoring_service = monitoring_service
        self._mcp_client: LongbridgeMCPClient | None = None
        self._graph_runner: TradeDecisionGraphRunner | None = None

    def _get_mcp_client(self) -> LongbridgeMCPClient | None:
        if self._mcp_client is None:
            config = get_longbridge_mcp_config()
            if config.enabled:
                self._mcp_client = LongbridgeMCPClient(config=config)
        return self._mcp_client

    def _get_graph_runner(self) -> TradeDecisionGraphRunner:
        if self._graph_runner is None:
            from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
            from app.services.market_event_query_service import MarketEventQueryService

            account_facts_builder = TradeDecisionAccountFactsBuilder(
                self.repository.es_client,
                self.repository.settings,
            )
            adapter = LongbridgeMCPToolAdapter(self._get_mcp_client())
            try:
                market_event_query_service = MarketEventQueryService(
                    self.repository.es_client,
                    self.repository.settings,
                )
            except Exception:
                market_event_query_service = None
            self._graph_runner = TradeDecisionGraphRunner(
                account_facts_builder=account_facts_builder,
                llm_service=self.llm_service,
                repository=self.repository,
                mcp_adapter=adapter,
                prompt_service=self.prompt_service,
                trace_service=self.trace_service,
                replay_service=self.replay_service,
                monitoring_service=self.monitoring_service,
                market_event_query_service=market_event_query_service,
            )
        return self._graph_runner

    def health(self, longbridge_configured: bool, trade_review_available: bool) -> dict:
        llm_configured = self.llm_service.get_active_provider() is not None
        mcp_config = get_longbridge_mcp_config()
        oauth_status = LongbridgeOAuthTokenService().status()
        if not mcp_config.enabled:
            mcp_auth_status = "disabled"
        elif oauth_status.get("mcp_effective_connected"):
            mcp_auth_status = "connected"
        else:
            mcp_auth_status = "authorization_required"

        mcp_available = mcp_auth_status == "connected"
        public_status = get_public_data_runtime_status(
            mcp_enabled=mcp_config.enabled,
            mcp_available=mcp_available,
            longbridge_sdk_configured=longbridge_configured,
            mcp_auth_status=mcp_auth_status,
            mcp_last_error=str(oauth_status.get("last_error") or ""),
        )

        return {
            "enabled": True,
            "llm_configured": llm_configured,
            "longbridge_configured": longbridge_configured,
            "trade_review_available": trade_review_available,
            "account_data_source": "IBKR_ONLY",
            "agent_mode": TRADE_DECISION_AGENT_MODE_LANGGRAPH,
            "graph_version": TRADE_DECISION_GRAPH_VERSION,
            **public_status,
            "message": "Trade decision agent is ready" if llm_configured else "LLM active provider is missing",
        }

    def analyze_holding(self, symbol: str, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if self.llm_service.get_active_provider() is None:
            raise LLMConfigError("No active LLM provider is configured")
        runner = self._get_graph_runner()
        if progress_reporter is not None:
            return runner.analyze_holding(normalized_symbol, question, progress_reporter=progress_reporter)
        return runner.analyze_holding(normalized_symbol, question)

    def analyze_entry(self, symbol: str, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if self.llm_service.get_active_provider() is None:
            raise LLMConfigError("No active LLM provider is configured")
        runner = self._get_graph_runner()
        if progress_reporter is not None:
            return runner.analyze_entry(normalized_symbol, question, progress_reporter=progress_reporter)
        return runner.analyze_entry(normalized_symbol, question)

    def analyze_trade_decision(self, symbol: str, *, progress_reporter: Any = None) -> dict:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if self.llm_service.get_active_provider() is None:
            raise LLMConfigError("No active LLM provider is configured")
        runner = self._get_graph_runner()
        if progress_reporter is not None:
            return runner.analyze_trade_decision(normalized_symbol, progress_reporter=progress_reporter)
        return runner.analyze_trade_decision(normalized_symbol)


def _build_card_pack_evidence_pack(card_pack) -> dict[str, Any]:
    """Build a display-oriented evidence pack from V2 cards for evidence_summary."""
    snapshot = card_pack.account_fact_snapshot
    snapshot_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
    mkt = card_pack.market_trend_card
    fund = card_pack.fundamental_valuation_card
    evt = card_pack.event_catalyst_card
    rr = card_pack.risk_reward_card
    trade_plan = getattr(card_pack, "trade_plan_card", None)

    public_tools = []
    for card in (mkt, fund, evt):
        if card and card.source_tools:
            public_tools.extend(card.source_tools)
    public_source = "LONGBRIDGE_MCP" if public_tools else "LONGBRIDGE_MCP_UNAVAILABLE"

    return {
        "data_sources": {
            "account_data": "IBKR_ONLY",
            "position_data": "IBKR_ONLY",
            "trade_data": "IBKR_ONLY",
            "public_market_data": public_source,
            "review_data": "IBKR_ONLY",
        },
        "account_context": snapshot_dict.get("account_context") or {},
        "position_context": snapshot_dict.get("position_context") or {},
        "trade_history_context": snapshot_dict.get("trade_history_context") or {},
        "review_context": snapshot_dict.get("review_context") or {},
        "market_context": _card_context(mkt, source=public_source),
        "company_context": _fundamental_company_context(fund, source=public_source),
        "valuation_context": _fundamental_valuation_context(fund, source=public_source),
        "external_events": _card_context(evt, source=public_source),
        "risk_context": _risk_context_from_trade_plan_or_card(rr, trade_plan),
        "data_quality": snapshot.data_quality if hasattr(snapshot, "data_quality") else {},
    }


def _card_context(card, *, source: str) -> dict[str, Any]:
    if card is None:
        return {}
    payload = card.to_dict() if hasattr(card, "to_dict") else dict(card)
    payload["source"] = source
    return payload


def _risk_context_from_trade_plan_or_card(card, trade_plan) -> dict[str, Any]:
    if card is not None:
        return _card_context(card, source="TRADE_PLAN_DERIVED_CARD")
    if trade_plan is None:
        return {}
    assessment = getattr(trade_plan, "risk_reward_assessment", None)
    if not isinstance(assessment, dict):
        return {}
    return {
        "source": "TRADE_PLAN_RISK_REWARD_ASSESSMENT",
        "summary": getattr(trade_plan, "summary", ""),
        "reward_risk_ratio": assessment.get("reward_risk_ratio"),
        "wait_for_pullback": assessment.get("wait_for_pullback"),
        "pullback_entry_level": assessment.get("pullback_entry_level"),
        "invalidation_level": assessment.get("invalidation_level"),
        "trim_level": assessment.get("trim_level"),
        "event_risk_window": assessment.get("event_risk_window"),
        "data_limitations": list(getattr(trade_plan, "data_limitations", []) or []),
    }


def _fundamental_company_context(card, *, source: str) -> dict[str, Any]:
    if card is None:
        return {}
    return {
        "source": source,
        "summary": card.summary,
        "company_name": card.company_name,
        "revenue_growth_summary": card.revenue_growth_summary,
        "profitability_summary": card.profitability_summary,
        "score": card.score,
        "max_score": card.max_score,
        "evidence_quality": card.evidence_quality,
        "source_tools": card.source_tools,
        "data_limitations": card.data_limitations,
    }


def _fundamental_valuation_context(card, *, source: str) -> dict[str, Any]:
    if card is None:
        return {}
    return {
        "source": source,
        "summary": card.valuation_summary or card.summary,
        "pe_ttm": card.pe_ttm,
        "forward_pe": card.forward_pe,
        "ps_ttm": card.ps_ttm,
        "ev_sales": card.ev_sales,
        "market_cap": card.market_cap,
        "peer_relative_note": card.peer_relative_note,
        "score": card.score,
        "max_score": card.max_score,
        "evidence_quality": card.evidence_quality,
        "source_tools": card.source_tools,
        "data_limitations": card.data_limitations,
    }
