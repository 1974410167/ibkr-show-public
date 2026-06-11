"""TradeDecisionGraphRunner - thin runner over the LangGraph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.agent_run_trace import build_agent_run_trace, new_agent_run_id
from app.agents.run_replay import build_replay_snapshot
from app.agents.trade_decision_graph.graph import (
    TradeDecisionGraphDeps,
    build_trade_decision_graph,
)
from app.agents.graph.result_contract import get_public_data_runtime_status
from app.agents.graph.trace import now_iso
from app.agents.versions import (
    TRADE_DECISION_AGENT_MODE_LANGGRAPH,
    TRADE_DECISION_GRAPH_VERSION,
    TRADE_DECISION_CARD_SCHEMA_VERSION,
    build_metadata,
    TRADE_DECISION_AGENT_VERSION,
    TRADE_DECISION_PROMPT_VERSION,
    OUTPUT_SCHEMA_VERSION,
    TRADE_DECISION_TOOLSET_VERSION,
    TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
)
from app.services.longbridge_service import normalize_longbridge_symbol


class TradeDecisionGraphRunner:
    """Runs the trade decision LangGraph."""

    def __init__(
        self,
        account_facts_builder: Any,
        llm_service: Any,
        repository: Any,
        mcp_adapter: Any = None,
        prompt_service: Any = None,
        trace_service: Any = None,
        replay_service: Any = None,
        monitoring_service: Any = None,
        market_event_query_service: Any = None,
    ) -> None:
        self.trace_service = trace_service
        self.replay_service = replay_service
        self.monitoring_service = monitoring_service
        self.deps = TradeDecisionGraphDeps(
            account_facts_builder=account_facts_builder,
            llm_service=llm_service,
            repository=repository,
            mcp_adapter=mcp_adapter,
            prompt_service=prompt_service,
            monitoring_service=monitoring_service,
            market_event_query_service=market_event_query_service,
        )
        self.graph = build_trade_decision_graph(self.deps)

    def analyze_entry(self, symbol: str, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        normalized = normalize_longbridge_symbol(symbol)
        return self._run("entry_decision", normalized, question, progress_reporter=progress_reporter)

    def analyze_holding(self, symbol: str, question: str | None = None, *, progress_reporter: Any = None) -> dict:
        normalized = normalize_longbridge_symbol(symbol)
        return self._run("holding_decision", normalized, question, progress_reporter=progress_reporter)

    def analyze_trade_decision(self, symbol: str, *, progress_reporter: Any = None) -> dict:
        normalized = normalize_longbridge_symbol(symbol)
        return self._run("trade_decision", normalized, None, progress_reporter=progress_reporter)

    def _run(self, decision_type: str, symbol: str, question: str | None, *, progress_reporter: Any = None) -> dict:
        # No _deps in state — nodes get deps via closure
        public_status = get_public_data_runtime_status(mcp_adapter=self.deps.mcp_adapter)
        initial_state: dict = {
            "decision_type": decision_type,
            "symbol": symbol,
            "normalized_symbol": symbol,
            "user_question": question,
            "started_at": now_iso(),
            "errors": [],
            "warnings": [],
            "data_limitations": [],
            "node_traces": [],
            "fallback_used": False,
            "fallback_reason": None,
            "metadata": {},
            "agent_run_id": new_agent_run_id("trade_decision"),
            "mcp_enabled": public_status.get("mcp_enabled", False),
            "mcp_available": public_status.get("mcp_available", False),
            "longbridge_sdk_configured": public_status.get("longbridge_sdk_configured", False),
            "public_data_mode": public_status.get("public_data_mode", "unavailable"),
            "public_market_data_source": public_status.get("public_market_data_source", "unavailable"),
        }
        if progress_reporter is not None:
            initial_state["progress_reporter"] = progress_reporter

        try:
            final_state = self.graph.invoke(initial_state)
            saved = final_state.get("saved_document")
            if saved:
                return self._finalize(saved, initial_state, final_state)
            return self._finalize(
                self._build_conservative_fallback(decision_type, symbol, question, "graph completed without saving"),
                initial_state,
                None,
            )
        except Exception as exc:
            if progress_reporter is not None:
                try:
                    progress_reporter.graph_failed(str(exc))
                except Exception:
                    pass
            return self._finalize(
                self._build_conservative_fallback(decision_type, symbol, question, str(exc)),
                initial_state,
                None,
                error=exc,
            )

    def _build_conservative_fallback(
        self,
        decision_type: str,
        symbol: str,
        question: str | None,
        reason: str,
    ) -> dict:
        """Build and save a conservative fallback document when graph fails."""
        now = now_iso()
        metadata = build_metadata(
            agent_version=TRADE_DECISION_AGENT_VERSION,
            prompt_version=TRADE_DECISION_PROMPT_VERSION,
            schema_version=OUTPUT_SCHEMA_VERSION,
            toolset_version=TRADE_DECISION_TOOLSET_VERSION,
            evidence_builder_version=TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
            agent_mode=TRADE_DECISION_AGENT_MODE_LANGGRAPH,
        )
        metadata["graph_version"] = TRADE_DECISION_GRAPH_VERSION
        metadata["card_schema_version"] = TRADE_DECISION_CARD_SCHEMA_VERSION
        metadata["public_data_mode"] = "unavailable"
        metadata["mcp_enabled"] = False
        metadata["mcp_available"] = False
        metadata["longbridge_sdk_configured"] = False
        quality = {
            "version": "trade_decision_quality_v1",
            "score": 0,
            "level": "poor",
            "passed": False,
            "hard_failures": ["graph_failed"],
            "warnings": [],
            "flags": ["graph_failed"],
            "checks": {},
            "summary": "图运行失败，已生成保守 fallback。",
            "fallback_used": True,
            "fallback_reason": reason[:200],
        }
        metadata["decision_quality"] = {
            "version": quality["version"],
            "score": quality["score"],
            "level": quality["level"],
            "passed": quality["passed"],
        }

        document: dict = {
            "decision_type": decision_type,
            "symbol": symbol,
            "user_question": question,
            "overall_score": 0,
            "rating": "negative",
            "action": "watchlist",
            "confidence": "low",
            "decision_summary": f"分析失败，建议观望：{reason[:100]}",
            "score_detail": {},
            "position_advice": {
                "current_position_pct": 0,
                "suggested_target_position_pct": 0,
                "max_position_pct": 0,
                "suggested_cash_amount": 0,
                "position_size_label": "none",
            },
            "execution_plan": {
                "should_act_now": False,
                "plan": [],
                "invalid_conditions": [],
                "recheck_triggers": [],
            },
            "key_reasons": [f"分析流程异常：{reason[:100]}"],
            "major_risks": ["分析数据不足"],
            "review_warnings": [],
            "data_limitations": [f"graph_failed: {reason[:200]}"],
            "evidence_used": [],
            "data_source_summary": {},
            "run_trace": [],
            "run_trace_summary": {},
            "metadata": metadata,
            "evidence_summary": {},
            "card_pack": {},
            "fallback_used": True,
            "fallback_reason": reason[:200],
            "llm_error_summary": {},
            "decision_quality": quality,
            "created_at": now,
            "updated_at": now,
        }

        try:
            return self.deps.repository.save_decision(document)
        except Exception:
            return document

    def _finalize(self, document: dict, initial_state: dict, final_state: dict | None, error: Exception | None = None) -> dict:
        run_id = initial_state.get("agent_run_id") or new_agent_run_id("trade_decision")
        document["agent_run_id"] = run_id
        document.setdefault("metadata", {})["agent_run_id"] = run_id
        node_traces = (final_state or {}).get("node_traces") or document.get("run_trace") or []
        trace = build_agent_run_trace(
            run_id=run_id,
            agent_name="trade_decision",
            document=document,
            node_traces=node_traces,
            started_at=initial_state.get("started_at"),
            final_status="failed" if error else None,
            error_message=str(error) if error else None,
        )
        replay = build_replay_snapshot(
            run_id=run_id,
            agent_name="trade_decision",
            request={
                "decision_type": initial_state.get("decision_type"),
                "symbol": initial_state.get("symbol"),
                "question": initial_state.get("user_question"),
            },
            document=document,
            agent_run_trace=trace,
            node_traces=node_traces,
            context_snapshot={
                "card_pack": document.get("card_pack"),
                "evidence_summary": document.get("evidence_summary"),
                "run_trace_summary": document.get("run_trace_summary"),
                "data_source_summary": document.get("data_source_summary"),
            },
        )
        trace.metadata["replay_id"] = replay.replay_id
        document["agent_run_trace"] = {"run_id": run_id, "final_status": trace.final_status}
        document["agent_replay"] = {"replay_id": replay.replay_id, "run_id": run_id}

        # Record trace and replay snapshot
        if self.trace_service is not None:
            try:
                self.trace_service.record_trace(trace)
            except Exception as exc:
                document.setdefault("data_limitations", []).append(f"agent_trace_persist_failed: {exc}")
        if self.replay_service is not None:
            try:
                self.replay_service.record_snapshot(replay)
                document["agent_replay"]["persisted"] = True
            except Exception as exc:
                document["agent_replay"]["persisted"] = False
                document["agent_replay"]["error"] = str(exc)[:200]
                document.setdefault("data_limitations", []).append(f"agent_replay_persist_failed: {exc}")

        # Re-save document so agent_run_id / agent_replay / agent_run_trace reach ES
        try:
            self.deps.repository.save_decision(document)
        except Exception as exc:
            document.setdefault("data_limitations", []).append(f"decision_re_save_failed: {exc}")

        return document
