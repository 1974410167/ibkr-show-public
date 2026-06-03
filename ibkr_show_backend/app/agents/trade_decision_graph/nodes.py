"""LangGraph nodes for the trade decision graph.

Every node is created via a make_* factory that closes over deps.
Nodes never read _deps from state — they use the closure.
Parallel nodes write only to their own card field + per-node public_data_mode.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.graph.result_contract import build_agent_metadata
from app.agents.graph.trace import (
    finish_node_trace,
    now_iso,
    start_node_trace,
)
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    BaseTradeDecisionCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
    TradeDecisionSubAgentTrace,
    build_fallback_account_fit_card,
    build_fallback_event_card,
    build_fallback_fundamental_card,
    build_fallback_market_trend_card,
    build_fallback_risk_reward_card,
)
from app.agents.evidence_summary import build_evidence_summary
from app.agents.versions import (
    TRADE_DECISION_AGENT_VERSION,
    TRADE_DECISION_CARD_SCHEMA_VERSION,
    TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
    TRADE_DECISION_PROMPT_VERSION,
    TRADE_DECISION_TOOLSET_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_metadata,
    TRADE_DECISION_AGENT_MODE_LANGGRAPH,
    TRADE_DECISION_GRAPH_VERSION,
)
from app.agents.trace_summary import build_run_trace_summary


# === Snapshot helpers ===

def _snapshot_is_holding(snapshot) -> bool:
    """Safely extract is_holding from either dict or dataclass."""
    if isinstance(snapshot, dict):
        return bool(snapshot.get("is_holding"))
    return bool(getattr(snapshot, "is_holding", False))


def _as_snapshot(snapshot) -> AccountFactSnapshot:
    """Convert dict snapshot to dataclass if needed."""
    if isinstance(snapshot, AccountFactSnapshot):
        return snapshot
    if isinstance(snapshot, dict):
        return AccountFactSnapshot(**snapshot)
    raise TypeError(f"Expected AccountFactSnapshot or dict, got {type(snapshot)}")


def _task_id_from_state(state: dict) -> str | None:
    reporter = state.get("progress_reporter")
    value = getattr(reporter, "task_id", None)
    return str(value) if value else None


# === Node factories (closure injection) ===

def _record_ibkr_metric(monitoring_service, *, run_id, agent_name, node_name, tool_name, ok, latency_ms, error_message=None, metadata=None):
    """Record an IBKR data-read metric if monitoring_service is available."""
    if not monitoring_service:
        return
    try:
        monitoring_service.record_tool_call(
            run_id=run_id or "",
            session_id="",
            tool_name=tool_name,
            tool_domain="ibkr",
            ok=ok,
            latency_ms=latency_ms,
            source="runtime",
            agent_name=agent_name,
            node_name=node_name,
            error_message=error_message,
            metadata=metadata or {},
        )
    except Exception:
        pass


def make_build_account_facts_node(deps):
    def build_account_facts_node(state: dict) -> dict:
        trace = start_node_trace("build_account_facts")
        import time as _time
        _t0 = _time.monotonic()
        try:
            builder = deps.account_facts_builder
            decision_type = state["decision_type"]
            symbol = state["normalized_symbol"]
            question = state.get("user_question")

            snapshot = builder.build(decision_type, symbol, question)
            _latency = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service,
                run_id=state.get("agent_run_id"), agent_name="trade_decision",
                node_name="build_account_facts", tool_name="ibkr_build_account_facts",
                ok=True, latency_ms=_latency,
                metadata={"decision_type": decision_type, "has_position": snapshot.is_holding},
            )

            warnings: list[str] = []
            data_limitations: list[str] = []

            if decision_type == "holding_decision" and not snapshot.is_holding:
                warnings.append("holding_decision requested but no position found; treating as entry-like")

            result: dict[str, Any] = {
                "account_fact_snapshot": snapshot,
                "warnings": warnings,
                "data_limitations": data_limitations,
            }
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            _latency = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service,
                run_id=state.get("agent_run_id"), agent_name="trade_decision",
                node_name="build_account_facts", tool_name="ibkr_build_account_facts",
                ok=False, latency_ms=_latency, error_message=error_msg,
            )
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"build_account_facts: {error_msg}"],
                "node_traces": [trace],
            }

    return build_account_facts_node


def make_account_fit_node(deps):
    def account_fit_node(state: dict) -> dict:
        trace = start_node_trace("account_fit")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            from app.services.trade_decision_sub_agents import AccountFitSubAgent

            agent = AccountFitSubAgent(deps.llm_service)
            card, sub_trace = agent.generate(snapshot)

            if card.summary:
                card.summary = strip_thinking_tags(card.summary)

            result = {"account_fit_card": card}
            trace = finish_node_trace(trace, "success", tools_called=sub_trace.tools_called or [])
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_account_fit_card(
                state.get("symbol", ""), state.get("decision_type", ""), str(exc)
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"account_fit_card": card, "node_traces": [trace]}

    return account_fit_node


def make_market_trend_node(deps):
    def market_trend_node(state: dict) -> dict:
        trace = start_node_trace("market_trend")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            from app.services.trade_decision_sub_agents import MarketTrendSubAgent

            agent = MarketTrendSubAgent(
                deps.llm_service,
                deps.mcp_adapter,
                prompt_service=getattr(deps, "prompt_service", None),
                monitoring_service=getattr(deps, "monitoring_service", None),
                run_id=state.get("agent_run_id"),
                task_id=_task_id_from_state(state),
            )
            card, sub_trace = agent.generate(snapshot)

            if card.summary:
                card.summary = strip_thinking_tags(card.summary)

            public_data_mode = "mcp" if sub_trace.status == "completed" and sub_trace.tools_called else "unavailable"

            result = {
                "market_trend_card": card,
                "market_public_data_mode": public_data_mode,
                "market_trend_prompt_metadata": sub_trace.prompt_metadata,
            }
            trace = finish_node_trace(
                trace,
                sub_trace.status if sub_trace.status == "completed" else "fallback",
                tools_called=sub_trace.tools_called or [],
                tool_call_count=sub_trace.tool_call_count,
                tool_calls=sub_trace.tool_calls,
                rounds_used=sub_trace.rounds_used,
                fallback_used=sub_trace.fallback_used,
                fallback_reason=sub_trace.fallback_reason,
            )
            trace["prompt_metadata"] = sub_trace.prompt_metadata
            trace["runtime_trace"] = sub_trace.runtime_trace
            trace["structured_output"] = sub_trace.structured_output
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_market_trend_card(
                state.get("symbol", ""), state.get("decision_type", ""), str(exc)
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "market_trend_card": card,
                "market_public_data_mode": "unavailable",
                "node_traces": [trace],
            }

    return market_trend_node


def make_fundamental_valuation_node(deps):
    def fundamental_valuation_node(state: dict) -> dict:
        trace = start_node_trace("fundamental_valuation")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            from app.services.trade_decision_sub_agents import FundamentalValuationSubAgent

            agent = FundamentalValuationSubAgent(
                deps.llm_service,
                deps.mcp_adapter,
                prompt_service=getattr(deps, "prompt_service", None),
                monitoring_service=getattr(deps, "monitoring_service", None),
                run_id=state.get("agent_run_id"),
                task_id=_task_id_from_state(state),
            )
            card, sub_trace = agent.generate(snapshot)

            if card.summary:
                card.summary = strip_thinking_tags(card.summary)

            public_data_mode = "mcp" if sub_trace.status == "completed" and sub_trace.tools_called else "unavailable"

            result = {
                "fundamental_valuation_card": card,
                "fundamental_public_data_mode": public_data_mode,
                "fundamental_valuation_prompt_metadata": sub_trace.prompt_metadata,
            }
            trace = finish_node_trace(
                trace,
                sub_trace.status if sub_trace.status == "completed" else "fallback",
                tools_called=sub_trace.tools_called or [],
                tool_call_count=sub_trace.tool_call_count,
                tool_calls=sub_trace.tool_calls,
                rounds_used=sub_trace.rounds_used,
                fallback_used=sub_trace.fallback_used,
                fallback_reason=sub_trace.fallback_reason,
            )
            trace["prompt_metadata"] = sub_trace.prompt_metadata
            trace["runtime_trace"] = sub_trace.runtime_trace
            trace["structured_output"] = sub_trace.structured_output
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_fundamental_card(
                state.get("symbol", ""), state.get("decision_type", ""), str(exc)
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "fundamental_valuation_card": card,
                "fundamental_public_data_mode": "unavailable",
                "node_traces": [trace],
            }

    return fundamental_valuation_node


def make_event_catalyst_node(deps):
    def event_catalyst_node(state: dict) -> dict:
        trace = start_node_trace("event_catalyst")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            from app.services.trade_decision_sub_agents import EventCatalystSubAgent

            agent = EventCatalystSubAgent(
                deps.llm_service,
                deps.mcp_adapter,
                prompt_service=getattr(deps, "prompt_service", None),
                monitoring_service=getattr(deps, "monitoring_service", None),
                run_id=state.get("agent_run_id"),
                task_id=_task_id_from_state(state),
            )
            card, sub_trace = agent.generate(snapshot)

            if card.summary:
                card.summary = strip_thinking_tags(card.summary)

            public_data_mode = "mcp" if sub_trace.status == "completed" and sub_trace.tools_called else "unavailable"

            result = {
                "event_catalyst_card": card,
                "event_public_data_mode": public_data_mode,
                "event_catalyst_prompt_metadata": sub_trace.prompt_metadata,
            }
            trace = finish_node_trace(
                trace,
                sub_trace.status if sub_trace.status == "completed" else "fallback",
                tools_called=sub_trace.tools_called or [],
                tool_call_count=sub_trace.tool_call_count,
                tool_calls=sub_trace.tool_calls,
                rounds_used=sub_trace.rounds_used,
                fallback_used=sub_trace.fallback_used,
                fallback_reason=sub_trace.fallback_reason,
            )
            trace["prompt_metadata"] = sub_trace.prompt_metadata
            trace["runtime_trace"] = sub_trace.runtime_trace
            trace["structured_output"] = sub_trace.structured_output
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_event_card(
                state.get("symbol", ""), state.get("decision_type", ""), str(exc)
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "event_catalyst_card": card,
                "event_public_data_mode": "unavailable",
                "node_traces": [trace],
            }

    return event_catalyst_node


# === Shared helpers ===

def _count_public_data_fallbacks(state: dict) -> int:
    """Count how many public-data cards are truly fallback (MCP data unavailable).

    A card is considered fallback only if:
    - It is missing entirely
    - Its evidence_quality is "low" AND score is near zero
    - Its stance is INSUFFICIENT_DATA

    LLM-generated data_limitations (e.g. "缺少forward PE") are informational
    and do NOT indicate MCP failure — the LLM may list limitations even when
    MCP data was successfully used.
    """
    count = 0
    for card_attr in ("market_trend_card", "fundamental_valuation_card", "event_catalyst_card"):
        card = state.get(card_attr)
        if card is None:
            count += 1
        elif isinstance(card, BaseTradeDecisionCard):
            if card.stance == CardStance.INSUFFICIENT_DATA:
                count += 1
            elif card.evidence_quality == "low" and card.score <= 1:
                count += 1
    return count


# === Risk reward (fan-in node — reads all 4 cards) ===

def make_risk_reward_node(deps):
    def risk_reward_node(state: dict) -> dict:
        trace = start_node_trace("risk_reward")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            account_fit = state.get("account_fit_card")
            market_trend = state.get("market_trend_card")
            fundamental = state.get("fundamental_valuation_card")
            event = state.get("event_catalyst_card")

            from app.services.trade_decision_sub_agents import RiskRewardSubAgent

            agent = RiskRewardSubAgent(deps.llm_service)
            card, sub_trace = agent.generate(snapshot, account_fit, market_trend, fundamental, event)

            # Enforce: if >=2 public data cards are fallback/low, cap risk_reward score
            public_fallback_count = _count_public_data_fallbacks(state)
            if public_fallback_count >= 2:
                card.score = min(card.score, 4)
                card.evidence_quality = "low"
                card.stance = CardStance.INSUFFICIENT_DATA
                card.summary = strip_thinking_tags(card.summary)
                if "公开市场数据不足" not in card.summary:
                    card.summary = f"公开市场数据不足，不能可靠评估风险收益。{card.summary}"
                card.data_limitations = list(set(card.data_limitations + [
                    "公开市场数据不足，risk_reward 评分已限制"
                ]))
                if not card.key_risks:
                    card.key_risks = ["公开数据不足，无法可靠评估"]
                card.wait_for_pullback = True

            if card.summary:
                card.summary = strip_thinking_tags(card.summary)

            result = {"risk_reward_card": card}
            trace = finish_node_trace(
                trace,
                "success",
                rounds_used=sub_trace.rounds_used,
                tools_called=sub_trace.tools_called,
                tool_call_count=sub_trace.tool_call_count,
                fallback_used=sub_trace.fallback_used,
                fallback_reason=sub_trace.fallback_reason,
                structured_output=sub_trace.structured_output,
                runtime_trace=sub_trace.runtime_trace,
            )
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_risk_reward_card(
                state.get("symbol", ""), state.get("decision_type", ""), str(exc)
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"risk_reward_card": card, "node_traces": [trace]}

    return risk_reward_node


# === Build card pack (fan-in after risk_reward) ===

def _resolve_public_data_mode(state: dict) -> str:
    """Resolve overall public_data_mode from per-node fields."""
    modes = [
        state.get("market_public_data_mode"),
        state.get("fundamental_public_data_mode"),
        state.get("event_public_data_mode"),
    ]
    if any(m == "mcp" for m in modes):
        return "mcp"
    if any(m == "sdk_fallback" for m in modes):
        return "sdk_fallback"
    return "unavailable"


def make_build_card_pack_node(deps):
    def build_card_pack_node(state: dict) -> dict:
        trace = start_node_trace("build_card_pack")
        try:
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            cards = [
                state.get("account_fit_card"),
                state.get("market_trend_card"),
                state.get("fundamental_valuation_card"),
                state.get("event_catalyst_card"),
                state.get("risk_reward_card"),
            ]

            # Ensure no None cards - generate fallback for any missing
            fallback_builders = [
                lambda: build_fallback_account_fit_card(state.get("symbol", ""), state.get("decision_type", ""), "card missing"),
                lambda: build_fallback_market_trend_card(state.get("symbol", ""), state.get("decision_type", ""), "card missing"),
                lambda: build_fallback_fundamental_card(state.get("symbol", ""), state.get("decision_type", ""), "card missing"),
                lambda: build_fallback_event_card(state.get("symbol", ""), state.get("decision_type", ""), "card missing"),
                lambda: build_fallback_risk_reward_card(state.get("symbol", ""), state.get("decision_type", ""), "card missing"),
            ]

            for i, card in enumerate(cards):
                if card is None:
                    cards[i] = fallback_builders[i]()

            # Compute data quality
            quality_scores = []
            for c in cards:
                if c:
                    q = getattr(c, "evidence_quality", "low")
                    quality_scores.append({"high": 3, "medium": 2, "low": 1}.get(q, 1))
            avg_q = sum(quality_scores) / max(len(quality_scores), 1)
            overall_quality = "high" if avg_q >= 2.5 else "medium" if avg_q >= 1.5 else "low"

            # Build subagent traces from node_traces
            subagent_traces = []
            for nt in state.get("node_traces") or []:
                node_name = nt.get("node_name", "")
                if node_name in ("account_fit", "market_trend", "fundamental_valuation", "event_catalyst", "risk_reward"):
                    subagent_traces.append(TradeDecisionSubAgentTrace(
                        sub_agent_name=node_name,
                        started_at=nt.get("started_at", ""),
                        finished_at=nt.get("finished_at", ""),
                        elapsed_ms=nt.get("elapsed_ms", 0),
                        status=nt.get("status", "unknown"),
                        error=nt.get("error"),
                        rounds_used=nt.get("rounds_used", 0),
                        tools_called=nt.get("tools_called", []),
                        tool_call_count=nt.get("tool_call_count", len(nt.get("tools_called", []) or [])),
                        tool_calls=nt.get("tool_calls", []),
                        runtime_trace=nt.get("runtime_trace", []),
                        fallback_used=nt.get("fallback_used", False),
                        fallback_reason=nt.get("fallback_reason"),
                        prompt_metadata=nt.get("prompt_metadata"),
                        structured_output=nt.get("structured_output"),
                    ))

            card_pack = TradeDecisionCardPack(
                decision_type=state.get("decision_type", ""),
                symbol=state.get("symbol", ""),
                account_fact_snapshot=snapshot,
                account_fit_card=cards[0],
                market_trend_card=cards[1],
                fundamental_valuation_card=cards[2],
                event_catalyst_card=cards[3],
                risk_reward_card=cards[4],
                data_quality_summary=overall_quality,
                subagent_traces=subagent_traces,
            )

            result: dict[str, Any] = {
                "card_pack": card_pack,
                "public_data_mode": _resolve_public_data_mode(state),
            }
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"build_card_pack: {error_msg}"],
                "node_traces": [trace],
            }

    return build_card_pack_node


# === Compose decision ===

def make_compose_decision_node(deps):
    def compose_decision_node(state: dict) -> dict:
        trace = start_node_trace("compose_decision")
        try:
            card_pack = state["card_pack"]

            from app.services.trade_decision_composer import TradeDecisionComposer

            composer = TradeDecisionComposer()
            decision_output = composer.compose(card_pack)

            # Strip thinking tags from all text fields
            for key in ("decision_summary",):
                if key in decision_output and isinstance(decision_output[key], str):
                    decision_output[key] = strip_thinking_tags(decision_output[key])

            if "key_reasons" in decision_output:
                decision_output["key_reasons"] = [
                    strip_thinking_tags(r) for r in decision_output["key_reasons"]
                ]

            # Enforce conservative action when public data is broadly fallback
            public_fallback = _count_public_data_fallbacks(state)
            if public_fallback >= 2:
                if decision_output.get("confidence") != "low":
                    decision_output["confidence"] = "low"
                data_lim = list(decision_output.get("data_limitations") or [])
                if "公开数据大面积 fallback" not in data_lim:
                    data_lim.append("公开数据大面积 fallback，结论可信度低")
                decision_output["data_limitations"] = data_lim

                action = decision_output.get("action", "")
                if action in ("add", "add_small", "add_batch"):
                    is_holding = _snapshot_is_holding(state.get("account_fact_snapshot"))
                    decision_output["action"] = "hold" if is_holding else "watchlist"

            result: dict[str, Any] = {"decision_output": decision_output}
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"compose_decision: {error_msg}"],
                "node_traces": [trace],
            }

    return compose_decision_node


# === Persist decision ===

def make_persist_decision_node(deps):
    def persist_decision_node(state: dict) -> dict:
        trace = start_node_trace("persist_decision")
        try:
            decision_output = state["decision_output"]
            card_pack = state["card_pack"]
            snapshot = _as_snapshot(state["account_fact_snapshot"])

            # Build evidence summary
            from app.services.trade_decision_agent import _build_card_pack_evidence_pack

            # Finish persist_decision trace before building run_trace so it's included
            trace = finish_node_trace(trace, "success")
            evidence_pack = _build_card_pack_evidence_pack(card_pack)
            run_trace = _build_run_trace({**state, "node_traces": (state.get("node_traces") or []) + [trace]})
            evidence_summary = build_evidence_summary(evidence_pack, run_trace)
            run_trace_summary = build_run_trace_summary(run_trace)

            # Resolve public data mode from graph state
            public_data_mode = state.get("public_data_mode") or _resolve_public_data_mode(state)
            # mcp_available should reflect whether MCP was actually used in this run
            mcp_available = public_data_mode in ("mcp", "sdk_fallback")
            public_market_data_source = state.get("public_market_data_source") or "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"

            base_metadata = build_metadata(
                agent_version=TRADE_DECISION_AGENT_VERSION,
                prompt_version=TRADE_DECISION_PROMPT_VERSION,
                schema_version=OUTPUT_SCHEMA_VERSION,
                toolset_version=TRADE_DECISION_TOOLSET_VERSION,
                evidence_builder_version=TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
                agent_mode=TRADE_DECISION_AGENT_MODE_LANGGRAPH,
            )
            metadata = build_agent_metadata(
                base_metadata=base_metadata,
                agent_mode=TRADE_DECISION_AGENT_MODE_LANGGRAPH,
                graph_version=TRADE_DECISION_GRAPH_VERSION,
                card_schema_version=TRADE_DECISION_CARD_SCHEMA_VERSION,
                account_data_source="IBKR_ONLY",
                trade_data_source="IBKR_ONLY",
                position_data_source="IBKR_ONLY",
                public_market_data_source=public_market_data_source,
                public_data_status={
                    "mcp_enabled": state.get("mcp_enabled", False),
                    "mcp_available": mcp_available,
                    "public_data_mode": public_data_mode,
                    "longbridge_sdk_configured": state.get("longbridge_sdk_configured", False),
                    "public_market_data_source": public_market_data_source,
                },
                fallback_used=state.get("fallback_used", False),
                fallback_reason=state.get("fallback_reason"),
            )
            metadata["prompt_metadata"] = {
                key: value
                for key, value in {
                    "trade_decision_market_trend": state.get("market_trend_prompt_metadata"),
                    "trade_decision_fundamental_valuation": state.get("fundamental_valuation_prompt_metadata"),
                    "trade_decision_event_catalyst": state.get("event_catalyst_prompt_metadata"),
                }.items()
                if value
            }
            if state.get("agent_run_id"):
                metadata["agent_run_id"] = state.get("agent_run_id")

            # Let repository generate id via uuid4
            now = now_iso()
            document: dict = {
                **decision_output,
                "decision_type": state["decision_type"],
                "symbol": state["symbol"],
                "user_question": state.get("user_question"),
                "card_pack": card_pack.to_dict() if hasattr(card_pack, "to_dict") else card_pack,
                "run_trace": run_trace,
                "run_trace_summary": run_trace_summary,
                "metadata": metadata,
                "evidence_summary": evidence_summary,
                "data_source_summary": decision_output.get("data_source_summary", {}),
                "fallback_used": state.get("fallback_used", False),
                "fallback_reason": state.get("fallback_reason"),
                "llm_error_summary": {},
                "created_at": now,
                "updated_at": now,
            }
            if state.get("agent_run_id"):
                document["agent_run_id"] = state.get("agent_run_id")

            # Strip thinking tags from all text fields in document
            for key in ("decision_summary",):
                if key in document and isinstance(document[key], str):
                    document[key] = strip_thinking_tags(document[key])
            if "key_reasons" in document:
                document["key_reasons"] = [strip_thinking_tags(r) for r in document["key_reasons"]]

            # Save
            saved = deps.repository.save_decision(document)

            result: dict[str, Any] = {"saved_document": saved}
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"persist_decision: {error_msg}"],
                "node_traces": [trace],
            }

    return persist_decision_node


def _build_run_trace(state: dict) -> list[dict]:
    """Convert node traces to run_trace format."""
    run_trace: list[dict] = []
    for nt in state.get("node_traces") or []:
        run_trace.append({
            "event": f"node_{nt.get('status', 'unknown')}",
            "node_name": nt.get("node_name"),
            "elapsed_ms": nt.get("elapsed_ms", 0),
            "tools_called": nt.get("tools_called", []),
            "tool_call_count": nt.get("tool_call_count", len(nt.get("tools_called", []) or [])),
            "tool_calls": nt.get("tool_calls", []),
            "rounds_used": nt.get("rounds_used", 0),
            "fallback_used": nt.get("fallback_used", False),
            "fallback_reason": nt.get("fallback_reason"),
            "structured_output": nt.get("structured_output"),
        })
    return run_trace
