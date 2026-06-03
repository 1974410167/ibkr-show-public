"""DailyPositionReviewGraphRunner - thin runner over the LangGraph."""

from __future__ import annotations

from typing import Any

from app.agents.agent_run_trace import build_agent_run_trace, new_agent_run_id
from app.agents.run_replay import build_replay_snapshot
from app.agents.graph.result_contract import build_agent_metadata, build_run_trace_from_state, classify_agent_status
from app.agents.graph.trace import now_iso
from app.agents.trace_summary import build_run_trace_summary
from app.agents.daily_position_review_graph.graph import (
    DailyPositionReviewGraphDeps,
    build_daily_position_review_graph,
)
from app.agents.versions import (
    DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
    DAILY_POSITION_REVIEW_AGENT_VERSION,
    DAILY_POSITION_REVIEW_CARD_SCHEMA_VERSION,
    DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
    DAILY_POSITION_REVIEW_GRAPH_VERSION,
    DAILY_POSITION_REVIEW_PROMPT_VERSION,
    DAILY_POSITION_REVIEW_TOOLSET_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
)


class DailyPositionReviewGraphRunner:

    def __init__(
        self,
        review_service: Any,
        llm_service: Any,
        repository: Any,
        email_service: Any = None,
        related_asset_service: Any = None,
        longbridge_client: Any = None,
        symbol_agent: Any = None,
        macro_agent: Any = None,
        prompt_service: Any = None,
        trace_service: Any = None,
        replay_service: Any = None,
        monitoring_service: Any = None,
    ) -> None:
        from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent
        from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent

        default_symbol_agent = symbol_agent or DailyReviewSymbolEvidenceAgent(llm_service, prompt_service=prompt_service)
        default_macro_agent = macro_agent or DailyReviewMacroEvidenceAgent(llm_service, prompt_service=prompt_service)

        self.trace_service = trace_service
        self.replay_service = replay_service
        self.deps = DailyPositionReviewGraphDeps(
            review_service=review_service,
            llm_service=llm_service,
            repository=repository,
            email_service=email_service,
            related_asset_service=related_asset_service,
            longbridge_client=longbridge_client,
            symbol_agent=default_symbol_agent,
            macro_agent=default_macro_agent,
            prompt_service=prompt_service,
            monitoring_service=monitoring_service,
        )
        self.graph = build_daily_position_review_graph(self.deps)

    def _initial_state(
        self,
        report_date: str,
        force_refresh: bool = False,
        auto_email: bool = False,
        progress_reporter: Any = None,
    ) -> dict:
        state = {
            "report_date": report_date,
            "force_refresh": force_refresh,
            "auto_email": auto_email,
            "started_at": now_iso(),
            "errors": [],
            "warnings": [],
            "data_limitations": [],
            "node_traces": [],
            "fallback_used": False,
            "fallback_reason": None,
            "metadata": {},
            "agent_run_id": new_agent_run_id("daily_position_review"),
        }
        if progress_reporter is not None:
            state["progress_reporter"] = progress_reporter
        return state

    def generate_review(
        self,
        report_date: str,
        force_refresh: bool = False,
        auto_email: bool = False,
        progress_reporter: Any = None,
    ) -> dict:
        initial_state = self._initial_state(report_date, force_refresh, auto_email, progress_reporter)
        try:
            final_state = self.graph.invoke(initial_state)
            saved = final_state.get("saved_document")
            if saved:
                run_trace = build_run_trace_from_state(final_state)
                if len(run_trace) > len(saved.get("run_trace") or []):
                    saved["run_trace"] = run_trace
                    saved["run_trace_summary"] = build_run_trace_summary(run_trace)
                    saved["graph_node_traces"] = run_trace
                    try:
                        persisted = self.deps.repository.save_review(saved)
                        saved["created_at"] = persisted.get("created_at") or saved.get("created_at")
                        saved["updated_at"] = persisted.get("updated_at") or saved.get("updated_at")
                    except Exception as exc:
                        saved.setdefault("data_limitations", []).append(f"trace_resave_failed: {str(exc)[:200]}")
                saved.setdefault("status", classify_agent_status(saved))
                return self._finalize(saved, initial_state, final_state)
            errors = final_state.get("errors") or []
            reason = "; ".join(str(item) for item in errors[-3:]) or "graph completed without saving"
            return self._finalize(self._build_fallback(report_date, reason), initial_state, None)
        except Exception as exc:
            if progress_reporter is not None:
                try:
                    progress_reporter.graph_failed(str(exc))
                except Exception:
                    pass
            return self._finalize(self._build_fallback(report_date, str(exc)), initial_state, None, error=exc)

    def _build_fallback(self, report_date: str, reason: str) -> dict:
        now = now_iso()
        base_metadata = build_metadata(
            agent_version=DAILY_POSITION_REVIEW_AGENT_VERSION,
            prompt_version=DAILY_POSITION_REVIEW_PROMPT_VERSION,
            schema_version=OUTPUT_SCHEMA_VERSION,
            toolset_version=DAILY_POSITION_REVIEW_TOOLSET_VERSION,
            evidence_builder_version=DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
            agent_mode=DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
        )
        metadata = build_agent_metadata(
            base_metadata=base_metadata,
            agent_mode=DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
            graph_version=DAILY_POSITION_REVIEW_GRAPH_VERSION,
            card_schema_version=DAILY_POSITION_REVIEW_CARD_SCHEMA_VERSION,
            account_data_source="IBKR_ONLY",
            trade_data_source="IBKR_ONLY",
            position_data_source="IBKR_ONLY",
            public_market_data_source="LONGBRIDGE_PUBLIC_ONLY",
            fallback_used=True,
            fallback_reason=reason[:200],
        )

        document: dict = {
            "id": report_date,
            "report_date": report_date,
            "review_type": "daily_position_review",
            "summary": f"复盘生成失败，采用保守兜底：{reason[:100]}",
            "account_conclusion": f"复盘流程异常：{reason[:100]}",
            "attribution_summary": "复盘流程异常，未生成归因摘要。",
            "major_contributors_analysis": [],
            "major_drags_analysis": [],
            "focus_symbol_analyses": [],
            "market_context": "复盘流程异常，未生成市场背景。",
            "risk_analysis": "复盘流程异常，未生成风险分析。",
            "tomorrow_watchlist": [],
            "operation_observation": "复盘流程异常，建议重新生成。",
            "data_limitations": [f"graph_failed: {reason[:200]}", "run_trace_empty_due_to_graph_failure"],
            "evidence_used": [],
            "data_source_summary": {},
            "deterministic_context": {},
            "evidence_summary": {},
            "run_trace": [],
            "run_trace_summary": {},
            "raw_llm_response": "",
            "model_provider_snapshot": {},
            "metadata": metadata,
            "agent_mode": DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
            "subagent_card_pack": {},
            "subagent_trace": {},
            "evidence_card_summary": {},
            "graph_node_traces": [],
            "graph_version": DAILY_POSITION_REVIEW_GRAPH_VERSION,
            "fallback_used": True,
            "fallback_reason": reason[:200],
            "status": "failed",
            "created_at": now,
            "updated_at": now,
        }
        try:
            return self.deps.repository.save_review(document)
        except Exception:
            return document

    def _finalize(self, document: dict, initial_state: dict, final_state: dict | None, error: Exception | None = None) -> dict:
        run_id = initial_state.get("agent_run_id") or new_agent_run_id("daily_position_review")
        document["agent_run_id"] = run_id
        document.setdefault("metadata", {})["agent_run_id"] = run_id
        node_traces = (final_state or {}).get("node_traces") or document.get("run_trace") or []
        trace = build_agent_run_trace(
            run_id=run_id,
            agent_name="daily_position_review",
            document=document,
            node_traces=node_traces,
            started_at=initial_state.get("started_at"),
            final_status="failed" if error else None,
            error_message=str(error) if error else None,
        )
        trace_doc = trace.to_dict()
        replay = build_replay_snapshot(
            run_id=run_id,
            agent_name="daily_position_review",
            request={"report_date": initial_state.get("report_date"), "auto_email": initial_state.get("auto_email")},
            document=document,
            agent_run_trace=trace_doc,
            node_traces=node_traces,
            context_snapshot={
                "deterministic_context": document.get("deterministic_context"),
                "subagent_card_pack": document.get("subagent_card_pack"),
                "subagent_trace": document.get("subagent_trace"),
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
                document.setdefault("data_limitations", []).append(f"daily_review_re_save_failed: {exc}")
        return document
