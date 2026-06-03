"""TradeReviewGraphRunner - thin runner over the LangGraph."""

from __future__ import annotations

from typing import Any

from app.agents.agent_run_trace import build_agent_run_trace, new_agent_run_id
from app.agents.run_replay import build_replay_snapshot
from app.agents.graph.trace import now_iso
from app.agents.trade_review_graph.graph import (
    TradeReviewGraphDeps,
    build_trade_review_graph,
)
from app.agents.versions import (
    TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
    TRADE_REVIEW_AGENT_VERSION,
    TRADE_REVIEW_EVIDENCE_BUILDER_VERSION,
    TRADE_REVIEW_GRAPH_VERSION,
    TRADE_REVIEW_PROMPT_VERSION,
    TRADE_REVIEW_TOOLSET_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
)


class TradeReviewGraphRunner:

    def __init__(
        self,
        evidence_builder: Any,
        llm_service: Any,
        repository: Any,
        mcp_adapter: Any | None = None,
        prompt_service: Any | None = None,
        trace_service: Any | None = None,
        replay_service: Any | None = None,
        monitoring_service: Any | None = None,
    ) -> None:
        self.trace_service = trace_service
        self.replay_service = replay_service
        self.deps = TradeReviewGraphDeps(
            evidence_builder=evidence_builder,
            llm_service=llm_service,
            repository=repository,
            mcp_adapter=mcp_adapter,
            prompt_service=prompt_service,
            monitoring_service=monitoring_service,
        )
        self.graph = build_trade_review_graph(self.deps)

    def _initial_state(
        self,
        review_type: str,
        symbol: str | None = None,
        trade_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        progress_reporter: Any = None,
    ) -> dict:
        state = {
            "review_type": review_type,
            "symbol": symbol,
            "trade_id": trade_id,
            "start_date": start_date,
            "end_date": end_date,
            "started_at": now_iso(),
            "errors": [],
            "warnings": [],
            "data_limitations": [],
            "node_traces": [],
            "fallback_used": False,
            "fallback_reason": None,
            "metadata": {},
            "agent_run_id": new_agent_run_id("trade_review"),
        }
        if progress_reporter is not None:
            state["progress_reporter"] = progress_reporter
        return state

    def generate_symbol_review(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        progress_reporter: Any = None,
    ) -> dict:
        initial_state = self._initial_state(
            review_type="symbol_level_review",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            progress_reporter=progress_reporter,
        )
        return self._run(initial_state)

    def generate_single_trade_review(self, trade_id: str, *, progress_reporter: Any = None) -> dict:
        initial_state = self._initial_state(
            review_type="single_trade_review",
            trade_id=trade_id,
            progress_reporter=progress_reporter,
        )
        return self._run(initial_state)

    def _run(self, initial_state: dict) -> dict:
        report_date = initial_state.get("symbol") or initial_state.get("trade_id") or "unknown"
        try:
            final_state = self.graph.invoke(initial_state)
            saved = final_state.get("saved_document")
            if saved:
                return self._finalize(saved, initial_state, final_state)
            return self._finalize(self._build_fallback(initial_state, "graph completed without saving"), initial_state, None)
        except Exception as exc:
            reporter = initial_state.get("progress_reporter")
            if reporter is not None:
                try:
                    reporter.graph_failed(str(exc))
                except Exception:
                    pass
            return self._finalize(self._build_fallback(initial_state, str(exc)), initial_state, None, error=exc)

    def _build_fallback(self, initial_state: dict, reason: str) -> dict:
        now = now_iso()
        metadata = build_metadata(
            agent_version=TRADE_REVIEW_AGENT_VERSION,
            prompt_version=TRADE_REVIEW_PROMPT_VERSION,
            schema_version=OUTPUT_SCHEMA_VERSION,
            toolset_version=TRADE_REVIEW_TOOLSET_VERSION,
            evidence_builder_version=TRADE_REVIEW_EVIDENCE_BUILDER_VERSION,
            agent_mode=TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
        )
        metadata["graph_version"] = TRADE_REVIEW_GRAPH_VERSION

        review_type = initial_state.get("review_type", "symbol_level_review")
        symbol = initial_state.get("symbol", "")
        trade_id = initial_state.get("trade_id")

        document: dict = {
            "id": trade_id or symbol or "unknown",
            "review_type": review_type,
            "symbol": symbol or "",
            "trade_ids": [trade_id] if trade_id else [],
            "start_date": initial_state.get("start_date"),
            "end_date": initial_state.get("end_date"),
            "overall_score": 0,
            "rating": "poor",
            "score_detail": {},
            "summary": f"复盘生成失败，采用保守兜底：{reason[:100]}",
            "strengths": [],
            "weaknesses": [f"复盘流程异常：{reason[:100]}"],
            "mistake_tags": [],
            "improvement_suggestions": ["建议重新生成复盘"],
            "data_limitations": [f"graph_failed: {reason[:200]}"],
            "evidence_used": [],
            "evidence_summary": {},
            "run_trace_summary": {},
            "evidence_pack": {},
            "run_trace": [],
            "raw_llm_response": "",
            "model_provider_snapshot": {},
            "metadata": metadata,
            "agent_mode": TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
            "graph_version": TRADE_REVIEW_GRAPH_VERSION,
            "fallback_used": True,
            "fallback_reason": reason[:200],
            "created_at": now,
            "updated_at": now,
        }
        try:
            return self.deps.repository.save_review(document)
        except Exception:
            return document

    def _finalize(self, document: dict, initial_state: dict, final_state: dict | None, error: Exception | None = None) -> dict:
        run_id = initial_state.get("agent_run_id") or new_agent_run_id("trade_review")
        document["agent_run_id"] = run_id
        document.setdefault("metadata", {})["agent_run_id"] = run_id
        node_traces = (final_state or {}).get("node_traces") or document.get("run_trace") or []
        trace = build_agent_run_trace(
            run_id=run_id,
            agent_name="trade_review",
            document=document,
            node_traces=node_traces,
            started_at=initial_state.get("started_at"),
            final_status="failed" if error else None,
            error_message=str(error) if error else None,
        )
        replay = build_replay_snapshot(
            run_id=run_id,
            agent_name="trade_review",
            request={
                "review_type": initial_state.get("review_type"),
                "symbol": initial_state.get("symbol"),
                "trade_id": initial_state.get("trade_id"),
                "start_date": initial_state.get("start_date"),
                "end_date": initial_state.get("end_date"),
            },
            document=document,
            agent_run_trace=trace,
            node_traces=node_traces,
            context_snapshot={
                "evidence_pack": document.get("evidence_pack"),
                "evidence_summary": document.get("evidence_summary"),
                "run_trace_summary": document.get("run_trace_summary"),
            },
        )
        trace.metadata["replay_id"] = replay.replay_id
        document["agent_run_trace"] = {"run_id": run_id, "final_status": trace.final_status}
        document["agent_replay"] = {"replay_id": replay.replay_id, "run_id": run_id}
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
        if self.trace_service is not None or self.replay_service is not None:
            try:
                self.deps.repository.save_review(document)
            except Exception as exc:
                document.setdefault("data_limitations", []).append(f"trade_review_re_save_failed: {exc}")
        return document
