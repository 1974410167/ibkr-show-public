"""LangGraph nodes for the trade review graph.

Every node is created via a make_* factory that closes over deps.
Nodes never read _deps from state — they use the closure.
Parallel evidence nodes write only to their own per-node fields.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.context_budget import enforce_section_budget
from app.agents.evidence_summary import build_evidence_summary
from app.agents.graph.result_contract import build_agent_metadata, build_run_trace_from_state
from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.graph.trace import finish_node_trace, now_iso, start_node_trace
from app.agents.invariants import normalize_trade_review_output
from app.agents.output_schemas import TradeReviewOutput
from app.agents.runtime import ToolCallingRuntime
from app.agents.structured_output.runtime import StructuredOutputRuntime, StructuredOutputResult
from app.agents.trace_summary import build_run_trace_summary
from app.agents.trade_review_graph.prompts import (
    TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
    TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
    TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
)
from app.agents.trade_review_structured_outputs import (
    TRADE_REVIEW_MAIN_EXAMPLE,
    build_trade_review_behavior_contract,
    build_trade_review_main_contract,
    build_trade_review_opportunity_contract,
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
from app.services.trade_review_agent import (
    SCORE_DIMENSIONS,
    TradeReviewAgentError,
    extract_json_object,
    rating_for_score,
)
from app.services.trade_review_evidence import normalize_trade_side

# Reuse pydantic validation
from pydantic import ValidationError


# === Node factories (closure injection) ===


def _record_ibkr_metric(monitoring_service, *, run_id, agent_name, node_name, tool_name, ok, latency_ms, error_message=None, metadata=None):
    if not monitoring_service:
        return
    try:
        monitoring_service.record_tool_call(
            run_id=run_id or "", session_id="", tool_name=tool_name, tool_domain="ibkr",
            ok=ok, latency_ms=latency_ms, source="runtime", agent_name=agent_name,
            node_name=node_name, error_message=error_message, metadata=metadata or {},
        )
    except Exception:
        pass


def make_load_trade_facts_node(deps):
    """Load trade facts from evidence builder (IBKR-only, no Longbridge public data)."""
    def load_trade_facts_node(state: dict) -> dict:
        trace = start_node_trace("load_trade_facts")
        import time as _time
        _t0 = _time.monotonic()
        try:
            review_type = state["review_type"]
            symbol = state.get("symbol")
            trade_id = state.get("trade_id")
            start_date = state.get("start_date")
            end_date = state.get("end_date")
            builder = deps.evidence_builder

            if review_type == "single_trade_review" and trade_id:
                # IBKR-only: fetch single trade, then related trades
                trade_data = builder.tool_get_single_trade(trade_id)
                trade = trade_data.get("trade", {})
                symbol = symbol or trade_data.get("symbol") or trade.get("symbol")
                trade_date = trade.get("date") or trade.get("trade_date")
                # Build review window around trade date
                if trade_date:
                    from datetime import date as _date, timedelta
                    td = _date.fromisoformat(str(trade_date)[:10])
                    review_start = (td - timedelta(days=90)).isoformat()
                    review_end = min(td + timedelta(days=90), _date.today()).isoformat()
                else:
                    review_start = start_date or "2025-01-01"
                    review_end = end_date or now_iso()[:10]
                # Fetch related trades (IBKR-only)
                related_trades_data = builder.tool_get_symbol_trades(symbol, review_start, review_end) if symbol else {"trades": []}
                trade_facts = {
                    "trades": [trade],
                    "related_symbol_trades": related_trades_data.get("trades", []),
                    "reviewed_trade_id": trade.get("trade_id") or trade_id,
                    "first_buy_date": trade_date if trade.get("side") == "BUY" else None,
                    "last_trade_date": trade_date,
                    "current_position": {},
                    "source": "IBKR_ONLY",
                }
                review_context = {}
                start_date = review_start
                end_date = review_end
            elif review_type == "symbol_level_review" and symbol:
                trades_data = builder.tool_get_symbol_trades(symbol, start_date, end_date)
                trade_facts = {
                    "trades": trades_data.get("trades", []),
                    "source": "IBKR_ONLY",
                    **{
                        key: trades_data.get(key)
                        for key in (
                            "buy_count",
                            "sell_count",
                            "has_buy_trades",
                            "has_sell_trades",
                            "is_round_trip",
                            "has_reopened_position_after_sell",
                            "latest_trade_side",
                            "latest_trade_date",
                        )
                    },
                }
                review_context = {}
            else:
                trade_facts = {}
                review_context = {}

            result = {
                "trade_facts": trade_facts,
                "review_context": review_context,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
            }
            tc = []
            if review_type == "single_trade_review" and trade_id:
                tc.append({"tool_name": "tool_get_single_trade", "success": True})
                if symbol:
                    tc.append({"tool_name": "tool_get_symbol_trades", "success": True})
            elif review_type == "symbol_level_review" and symbol:
                tc.append({"tool_name": "tool_get_symbol_trades", "success": True})
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            for c in tc:
                _record_ibkr_metric(
                    deps.monitoring_service, run_id=state.get("agent_run_id"),
                    agent_name="trade_review", node_name="load_trade_facts",
                    tool_name=c["tool_name"], ok=True, latency_ms=latency_ms,
                )
            trace = finish_node_trace(
                trace, "success",
                runtime_trace=result.get("trace") or [],
                tools_called=[c["tool_name"] for c in tc],
                tool_calls=tc,
                tool_call_count=len(tc),
            )
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="trade_review", node_name="load_trade_facts",
                tool_name="ibkr_load_trade_facts", ok=False, latency_ms=latency_ms,
                error_message=error_msg,
            )
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"load_trade_facts: {error_msg}"],
                "trade_facts": {},
                "review_context": {},
                "node_traces": [trace],
            }
    return load_trade_facts_node


def make_position_node(deps):
    """Fetch current position for the symbol."""
    def position_node(state: dict) -> dict:
        trace = start_node_trace("position_evidence")
        import time as _time
        _t0 = _time.monotonic()
        try:
            symbol = state.get("symbol")
            if not symbol:
                return {"position_evidence": {}, "node_traces": [finish_node_trace(trace, "success")]}
            builder = deps.evidence_builder
            position = builder.tool_get_current_position(symbol)
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="trade_review", node_name="position_evidence",
                tool_name="ibkr_get_current_position", ok=True, latency_ms=latency_ms,
            )
            result = {"position_evidence": position}
            tc = [{"tool_name": "tool_get_current_position", "success": True}]
            trace = finish_node_trace(trace, "success", runtime_trace=result.get("trace") or [], tools_called=["tool_get_current_position"], tool_calls=tc, tool_call_count=1)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="trade_review", node_name="position_evidence",
                tool_name="ibkr_get_current_position", ok=False, latency_ms=latency_ms,
                error_message=str(exc)[:200],
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"position_evidence": {"error": str(exc)[:200]}, "node_traces": [trace]}
    return position_node


def make_account_node(deps):
    """Fetch account context."""
    def account_node(state: dict) -> dict:
        trace = start_node_trace("account_evidence")
        import time as _time
        _t0 = _time.monotonic()
        try:
            builder = deps.evidence_builder
            start_date = state.get("start_date")
            end_date = state.get("end_date")
            account = builder.tool_get_account_context(start_date, end_date)
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="trade_review", node_name="account_evidence",
                tool_name="ibkr_get_account_context", ok=True, latency_ms=latency_ms,
            )
            result = {"account_evidence": account}
            tc = [{"tool_name": "tool_get_account_context", "success": True}]
            trace = finish_node_trace(trace, "success", runtime_trace=result.get("trace") or [], tools_called=["tool_get_account_context"], tool_calls=tc, tool_call_count=1)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="trade_review", node_name="account_evidence",
                tool_name="ibkr_get_account_context", ok=False, latency_ms=latency_ms,
                error_message=str(exc)[:200],
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"account_evidence": {"error": str(exc)[:200]}, "node_traces": [trace]}
    return account_node


def make_market_node(deps):
    """Fetch price context from Longbridge."""
    def market_node(state: dict) -> dict:
        trace = start_node_trace("market_evidence")
        try:
            symbol = state.get("symbol")
            if not symbol:
                return {"market_evidence": {}, "node_traces": [finish_node_trace(trace, "success")]}
            builder = deps.evidence_builder
            start = state.get("start_date") or "2025-01-01"
            end = state.get("end_date") or now_iso()[:10]
            market = builder.tool_get_price_context(symbol, start, end)
            result = {"market_evidence": market}
            tc = [{"tool_name": "tool_get_price_context", "success": True}]
            trace = finish_node_trace(trace, "success", tools_called=["tool_get_price_context"], tool_calls=tc, tool_call_count=1)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"market_evidence": {"error": str(exc)[:200]}, "node_traces": [trace]}
    return market_node


def make_benchmark_node(deps):
    """Fetch benchmark context from Longbridge."""
    def benchmark_node(state: dict) -> dict:
        trace = start_node_trace("benchmark_evidence")
        try:
            builder = deps.evidence_builder
            start = state.get("start_date") or "2025-01-01"
            end = state.get("end_date") or now_iso()[:10]
            benchmark = builder.tool_get_benchmark_context(start, end)
            result = {"benchmark_evidence": benchmark}
            tc = [{"tool_name": "tool_get_benchmark_context", "success": True}]
            trace = finish_node_trace(trace, "success", tools_called=["tool_get_benchmark_context"], tool_calls=tc, tool_call_count=1)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"benchmark_evidence": {"error": str(exc)[:200]}, "node_traces": [trace]}
    return benchmark_node


def make_event_node(deps):
    """Fetch news/events from Longbridge."""
    def event_node(state: dict) -> dict:
        trace = start_node_trace("event_evidence")
        try:
            symbol = state.get("symbol")
            if not symbol:
                return {"event_evidence": {}, "node_traces": [finish_node_trace(trace, "success")]}
            builder = deps.evidence_builder
            news = builder.tool_get_symbol_news(symbol, 10)
            result = {"event_evidence": news}
            tc = [{"tool_name": "tool_get_symbol_news", "success": True}]
            trace = finish_node_trace(trace, "success", tools_called=["tool_get_symbol_news"], tool_calls=tc, tool_call_count=1)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"event_evidence": {"error": str(exc)[:200]}, "node_traces": [trace]}
    return event_node


# === Fan-in: build_trade_review_context ===


def make_build_trade_review_context_node(deps):
    """Merge all evidence into a unified review context for compose.

    Both single_trade_review and symbol_level_review use the same fan-in logic.
    load_trade_facts provides IBKR-only trade_facts; this node merges in
    position, account, market, benchmark, and event evidence.
    """
    def build_trade_review_context_node(state: dict) -> dict:
        trace = start_node_trace("build_trade_review_context")
        try:
            review_type = state["review_type"]
            symbol = state.get("symbol")
            trade_facts = state.get("trade_facts") or {}
            position = state.get("position_evidence") or {}
            account = state.get("account_evidence") or {}
            market = state.get("market_evidence") or {}
            benchmark = state.get("benchmark_evidence") or {}
            event = state.get("event_evidence") or {}

            # Enrich trade_facts with current position from position_evidence node
            current_position = {}
            if position and position.get("position"):
                current_position = position.get("position") or {}
            lifecycle_facts = _trade_lifecycle_facts(trade_facts.get("trades") or [], current_position)
            trade_facts = {
                **trade_facts,
                **{key: value for key, value in lifecycle_facts.items() if trade_facts.get(key) is None},
                "is_currently_holding": lifecycle_facts["is_currently_holding"],
                "current_position": current_position,
            }

            merged = {
                "review_type": review_type,
                "symbol": symbol,
                "trade_facts": trade_facts,
                "account_context": account,
                "price_context": market.get("price_context", {}),
                "benchmark_context": benchmark.get("benchmark_context", {}),
                "external_events": event,
                "data_sources": {
                    "trade_data": "IBKR_ONLY",
                    "account_data": "IBKR_ONLY",
                    "position_data": "IBKR_ONLY",
                    "public_market_data": "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
                },
            }

            result = {"merged_review_context": merged}
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"build_trade_review_context: {error_msg}"],
                "merged_review_context": {},
                "node_traces": [trace],
            }
    return build_trade_review_context_node


def _trade_lifecycle_facts(trades: list[dict], current_position: dict | None) -> dict:
    buy_count = sum(1 for trade in trades if isinstance(trade, dict) and normalize_trade_side(trade.get("side")) == "BUY")
    sell_count = sum(1 for trade in trades if isinstance(trade, dict) and normalize_trade_side(trade.get("side")) == "SELL")
    latest_trade = trades[-1] if trades and isinstance(trades[-1], dict) else {}
    latest_trade_side = normalize_trade_side(latest_trade.get("side")) if latest_trade else None
    latest_trade_date = latest_trade.get("date") if latest_trade else None
    is_currently_holding = bool(current_position and abs(float(current_position.get("quantity") or 0.0)) > 0)

    seen_sell = False
    has_reopened_position_after_sell = False
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        side = normalize_trade_side(trade.get("side"))
        if side == "SELL":
            seen_sell = True
        elif side == "BUY" and seen_sell:
            has_reopened_position_after_sell = True
            break

    return {
        "buy_count": buy_count,
        "sell_count": sell_count,
        "has_buy_trades": buy_count > 0,
        "has_sell_trades": sell_count > 0,
        "is_round_trip": buy_count > 0 and sell_count > 0,
        "is_currently_holding": is_currently_holding,
        "has_reopened_position_after_sell": has_reopened_position_after_sell,
        "latest_trade_side": latest_trade_side,
        "latest_trade_date": latest_trade_date,
    }


# === Parallel analysis nodes ===


def make_behavior_pattern_node(deps):
    """Analyze trading behavior patterns using LLM sub-agent."""
    def behavior_pattern_node(state: dict) -> dict:
        trace = start_node_trace("behavior_pattern")
        try:
            merged_context = state.get("merged_review_context") or {}
            review_type = state.get("review_type", "")

            prompt = (
                "你是交易行为模式分析子 Agent。基于以下交易数据，分析交易者的行为模式。\n"
                "关注：买卖时机选择、加减仓节奏、持仓周期管理、止损止盈行为。\n"
                "输出 JSON: {\"behavior_patterns\": [...], \"behavior_score\": 0-100, \"behavior_summary\": \"...\"}\n\n"
                f"交易数据:\n{json.dumps(_compact_for_llm(merged_context), ensure_ascii=False, default=str)[:8000]}"
            )

            system_prompt, prompt_metadata = resolve_runtime_prompt(
                getattr(deps, "prompt_service", None),
                "trade_review_behavior_pattern",
                TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
            )
            runtime = ToolCallingRuntime(
                deps.llm_service,
                agent_name="trade_review",
                node_name="behavior_pattern",
                prompt_metadata=prompt_metadata,
                call_type="sub_agent",
                run_id=state.get("agent_run_id"),
            )
            result = runtime.run(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=[],
                response_format={"type": "json_object"},
            )

            raw = result["content"]
            runtime_trace = list(result.get("trace") or [])
            structured = _parse_structured_output(
                deps.llm_service,
                raw,
                build_trade_review_behavior_contract(),
                context={
                    "review_type": review_type,
                    "symbol": state.get("symbol"),
                    "merged_review_context": _compact_for_llm(merged_context),
                    "runtime_trace": _compact_runtime_trace(runtime_trace),
                },
            )
            runtime_trace.append(_structured_output_event(structured.metadata))
            if structured.ok and structured.payload:
                parsed = structured.payload
            else:
                parsed = {
                    "behavior_patterns": [],
                    "behavior_score": 0,
                    "behavior_summary": "行为模式分析解析失败",
                    "data_limitations": [_friendly_structured_limitation(structured, "行为模式分析输出格式异常，已使用保守兜底。")],
                }

            # Strip thinking tags
            if isinstance(parsed.get("behavior_summary"), str):
                parsed["behavior_summary"] = strip_thinking_tags(parsed["behavior_summary"])

            result_data = {
                "behavior_pattern_analysis": parsed,
                "behavior_prompt_metadata": prompt_metadata,
                "behavior_structured_output": structured.metadata,
            }
            trace = finish_node_trace(trace, "success", runtime_trace=runtime_trace, structured_output=structured.metadata)
            return {**result_data, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "behavior_pattern_analysis": {"behavior_patterns": [], "behavior_score": 0, "behavior_summary": f"行为模式分析失败: {str(exc)[:100]}"},
                "node_traces": [trace],
            }
    return behavior_pattern_node


def make_opportunity_cost_node(deps):
    """Analyze opportunity cost using LLM sub-agent."""
    def opportunity_cost_node(state: dict) -> dict:
        trace = start_node_trace("opportunity_cost")
        try:
            merged_context = state.get("merged_review_context") or {}
            symbol = state.get("symbol", "")

            prompt = (
                "你是机会成本分析子 Agent。基于以下交易数据和基准表现，分析该交易的机会成本。\n"
                "关注：同期 SPY/QQQ/SMH 表现对比、资金占用成本、错过的机会。\n"
                "输出 JSON: {\"opportunity_cost_score\": 0-100, \"benchmark_comparison\": {...}, \"opportunity_cost_summary\": \"...\"}\n\n"
                f"交易数据:\n{json.dumps(_compact_for_llm(merged_context), ensure_ascii=False, default=str)[:8000]}"
            )

            system_prompt, prompt_metadata = resolve_runtime_prompt(
                getattr(deps, "prompt_service", None),
                "trade_review_opportunity_cost",
                TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
            )
            runtime = ToolCallingRuntime(
                deps.llm_service,
                agent_name="trade_review",
                node_name="opportunity_cost",
                prompt_metadata=prompt_metadata,
                call_type="sub_agent",
                run_id=state.get("agent_run_id"),
            )
            result = runtime.run(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=[],
                response_format={"type": "json_object"},
            )

            raw = result["content"]
            runtime_trace = list(result.get("trace") or [])
            structured = _parse_structured_output(
                deps.llm_service,
                raw,
                build_trade_review_opportunity_contract(),
                context={
                    "review_type": state.get("review_type"),
                    "symbol": symbol,
                    "merged_review_context": _compact_for_llm(merged_context),
                    "runtime_trace": _compact_runtime_trace(runtime_trace),
                },
            )
            runtime_trace.append(_structured_output_event(structured.metadata))
            if structured.ok and structured.payload:
                parsed = structured.payload
            else:
                parsed = {
                    "opportunity_cost_score": 0,
                    "benchmark_comparison": {},
                    "opportunity_cost_summary": "机会成本分析解析失败",
                    "data_limitations": [_friendly_structured_limitation(structured, "机会成本分析输出格式异常，已使用保守兜底。")],
                }

            if isinstance(parsed.get("opportunity_cost_summary"), str):
                parsed["opportunity_cost_summary"] = strip_thinking_tags(parsed["opportunity_cost_summary"])

            result_data = {
                "opportunity_cost_analysis": parsed,
                "opportunity_prompt_metadata": prompt_metadata,
                "opportunity_structured_output": structured.metadata,
            }
            trace = finish_node_trace(trace, "success", runtime_trace=runtime_trace, structured_output=structured.metadata)
            return {**result_data, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "opportunity_cost_analysis": {"opportunity_cost_score": 0, "benchmark_comparison": {}, "opportunity_cost_summary": f"机会成本分析失败: {str(exc)[:100]}"},
                "node_traces": [trace],
            }
    return opportunity_cost_node


# === Compose trade review ===


def make_compose_trade_review_node(deps):
    """Compose final trade review output using LLM."""
    def compose_trade_review_node(state: dict) -> dict:
        trace = start_node_trace("compose_trade_review")
        try:
            merged_context = state.get("merged_review_context") or {}
            behavior = state.get("behavior_pattern_analysis") or {}
            opportunity = state.get("opportunity_cost_analysis") or {}
            review_type = state.get("review_type", "symbol_level_review")
            symbol = state.get("symbol", "")

            # Enrich context with sub-agent analyses
            llm_context = {
                **merged_context,
                "behavior_pattern_analysis": behavior,
                "opportunity_cost_analysis": opportunity,
            }

            user_prompt = _build_compose_user_prompt(llm_context, review_type, symbol)

            system_prompt, prompt_metadata = resolve_runtime_prompt(
                getattr(deps, "prompt_service", None),
                "trade_review_main",
                TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
            )
            runtime = ToolCallingRuntime(
                deps.llm_service,
                agent_name="trade_review",
                node_name="compose_trade_review",
                prompt_metadata=prompt_metadata,
                call_type="compose",
                run_id=state.get("agent_run_id"),
            )
            result = runtime.run(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=[],
                response_format={"type": "json_object"},
            )

            raw_response = result["content"]
            runtime_trace = list(result.get("trace") or [])

            def _compose_fallback_builder(_context, _last_error, _raw_response):
                return _fallback_review_output(state)

            structured = _parse_structured_output(
                deps.llm_service,
                raw_response,
                build_trade_review_main_contract(fallback_builder=_compose_fallback_builder),
                context={
                    "review_type": review_type,
                    "symbol": symbol,
                    "merged_context": _compact_for_llm(merged_context),
                    "behavior_pattern_analysis": behavior,
                    "opportunity_cost_analysis": opportunity,
                    "score_dimensions": SCORE_DIMENSIONS,
                    "runtime_trace": _compact_runtime_trace(runtime_trace),
                },
            )
            runtime_trace.append(_structured_output_event(structured.metadata))
            fallback_used = False
            fallback_reason = None
            if structured.ok and structured.payload:
                try:
                    validated = _validate_review_output(structured.payload, merged_context)
                    if structured.fallback_used:
                        fallback_used = True
                        fallback_reason = structured.metadata.get("fallback_reason") or structured.error_code
                except TradeReviewAgentError as exc:
                    validated = _fallback_review_output(state)
                    fallback_used = True
                    fallback_reason = f"{exc.args[0] if exc.args else 'LLM_SCHEMA_INVALID'}: {str(exc)[:160]}"
                    structured.metadata["post_validate_error"] = fallback_reason
                    structured.metadata["schema_validation_passed"] = False
            else:
                validated = _fallback_review_output(state)
                fallback_used = True
                fallback_reason = f"{structured.error_code}: {structured.error_message}" if structured.error_code else "structured output failed"

            # Strip thinking tags from text fields
            for key in ("summary",):
                if key in validated and isinstance(validated[key], str):
                    validated[key] = strip_thinking_tags(validated[key])
            for key in ("strengths", "weaknesses", "improvement_suggestions", "data_limitations", "evidence_used"):
                if key in validated and isinstance(validated[key], list):
                    validated[key] = [strip_thinking_tags(str(item)) for item in validated[key]]

            result_data = {
                "trade_review_output": validated,
                "prompt_metadata": {
                    "trade_review_main": prompt_metadata,
                    "trade_review_behavior_pattern": state.get("behavior_prompt_metadata"),
                    "trade_review_opportunity_cost": state.get("opportunity_prompt_metadata"),
                },
                "structured_output": {
                    "trade_review_main": structured.metadata,
                    "trade_review_behavior_pattern": state.get("behavior_structured_output"),
                    "trade_review_opportunity_cost": state.get("opportunity_structured_output"),
                },
                "raw_llm_response": _structured_raw_response(raw_response, structured),
            }
            if fallback_used:
                result_data["fallback_used"] = True
                result_data["fallback_reason"] = fallback_reason
            trace = finish_node_trace(
                trace,
                "fallback" if fallback_used else "success",
                runtime_trace=runtime_trace,
                structured_output=structured.metadata,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
            return {**result_data, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"compose_trade_review: {error_msg}"],
                "trade_review_output": _fallback_review_output(state),
                "fallback_used": True,
                "fallback_reason": f"compose_trade_review: {error_msg}",
                "node_traces": [trace],
            }
    return compose_trade_review_node


# === Persist trade review ===


def make_persist_trade_review_node(deps):
    """Save trade review document to repository."""
    def persist_trade_review_node(state: dict) -> dict:
        trace = start_node_trace("persist_trade_review")
        try:
            review_output = state.get("trade_review_output") or _fallback_review_output(state)
            review_type = state.get("review_type", "symbol_level_review")
            symbol = state.get("symbol", "")
            trade_id = state.get("trade_id")
            start_date = state.get("start_date")
            end_date = state.get("end_date")
            trade_facts = state.get("trade_facts") or {}
            merged_context = state.get("merged_review_context") or {}

            provider_snapshot = _get_provider_snapshot(deps.llm_service)
            finished_trace = finish_node_trace(trace, "success")
            run_trace = build_run_trace_from_state(state, finished_trace)
            run_trace_summary = build_run_trace_summary(run_trace)

            evidence_pack = {
                **merged_context,
                "data_sources": {
                    "trade_data": "IBKR_ONLY",
                    "account_data": "IBKR_ONLY",
                    "position_data": "IBKR_ONLY",
                    "public_market_data": "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
                },
            }
            evidence_summary = build_evidence_summary(evidence_pack, run_trace)

            base_metadata = build_metadata(
                agent_version=TRADE_REVIEW_AGENT_VERSION,
                prompt_version=TRADE_REVIEW_PROMPT_VERSION,
                schema_version=OUTPUT_SCHEMA_VERSION,
                toolset_version=TRADE_REVIEW_TOOLSET_VERSION,
                evidence_builder_version=TRADE_REVIEW_EVIDENCE_BUILDER_VERSION,
                agent_mode=TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
                model_provider_snapshot=provider_snapshot,
            )
            metadata = build_agent_metadata(
                base_metadata=base_metadata,
                agent_mode=TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
                graph_version=TRADE_REVIEW_GRAPH_VERSION,
                account_data_source="IBKR_ONLY",
                trade_data_source="IBKR_ONLY",
                position_data_source="IBKR_ONLY",
                public_market_data_source="LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
                fallback_used=state.get("fallback_used", False),
                fallback_reason=state.get("fallback_reason"),
            )
            metadata["prompt_metadata"] = {
                key: value
                for key, value in (state.get("prompt_metadata") or {}).items()
                if value
            }
            metadata["structured_output"] = {
                key: value
                for key, value in (state.get("structured_output") or {}).items()
                if value
            }
            if state.get("agent_run_id"):
                metadata["agent_run_id"] = state.get("agent_run_id")

            resolved_symbol = str(review_output.get("symbol") or symbol or "").strip().upper()
            trade_ids = [trade_id] if trade_id else []
            if not trade_ids:
                for trade in trade_facts.get("trades", []):
                    tid = trade.get("trade_id")
                    if tid:
                        trade_ids.append(tid)

            now = now_iso()
            document: dict = {
                **review_output,
                "review_type": review_type,
                "symbol": resolved_symbol,
                "trade_ids": trade_ids,
                "start_date": start_date or _infer_start_date(trade_facts),
                "end_date": end_date or _infer_end_date(trade_facts),
                "metadata": metadata,
                "evidence_pack": evidence_pack,
                "evidence_summary": evidence_summary,
                "run_trace_summary": run_trace_summary,
                "run_trace": run_trace,
                "raw_llm_response": state.get("raw_llm_response", ""),
                "model_provider_snapshot": provider_snapshot,
                "fallback_used": state.get("fallback_used", False),
                "fallback_reason": state.get("fallback_reason"),
                "created_at": now,
                "updated_at": now,
            }
            if state.get("agent_run_id"):
                document["agent_run_id"] = state.get("agent_run_id")

            saved = deps.repository.save_review(document)

            result = {"saved_document": saved}
            return {**result, "node_traces": [finished_trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"persist_trade_review: {error_msg}"],
                "node_traces": [trace],
            }
    return persist_trade_review_node


# === Shared helpers ===


def _compact_for_llm(context: dict) -> dict:
    """Compact review context for LLM input, removing large raw data."""
    compact = {}
    for key, value in context.items():
        if key in ("symbol_candles",):
            # Limit candles to summary
            if isinstance(value, list) and len(value) > 20:
                compact[key] = value[:5] + [{"note": f"...{len(value) - 10} more candles..."}] + value[-5:]
            else:
                compact[key] = value
        elif key == "external_events" and isinstance(value, dict):
            compact[key] = {k: v[:5] if isinstance(v, list) else v for k, v in value.items()}
        else:
            compact[key] = value
    return compact


def _compact_runtime_trace(runtime_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for event in runtime_trace[-20:]:
        if not isinstance(event, dict):
            continue
        compact.append(
            {
                key: value
                for key, value in event.items()
                if key
                in {
                    "event",
                    "node_name",
                    "tool",
                    "tool_name",
                    "ok",
                    "latency_ms",
                    "error",
                    "error_code",
                    "total_tokens",
                    "prompt_key",
                    "prompt_version",
                    "fallback_used",
                }
            }
        )
    return compact


def _parse_structured_output(llm_service, raw_response: str, contract, context: dict[str, Any]) -> StructuredOutputResult:
    runtime = StructuredOutputRuntime(llm_service)
    return runtime.parse_validate_repair(raw_response, contract, context=context, trace=[])


def _structured_output_event(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    return {
        "event": "structured_output_result",
        "contract_name": metadata.get("contract_name"),
        "ok": bool(metadata.get("schema_validation_passed")) or bool(metadata.get("fallback_used")),
        "repaired": bool(metadata.get("repaired")),
        "repair_attempts": metadata.get("repair_attempts", 0),
        "fallback_used": bool(metadata.get("fallback_used")),
        "error_code": metadata.get("error_code"),
        "schema_validation_passed": bool(metadata.get("schema_validation_passed")),
        "raw_response_preview": metadata.get("raw_response_preview"),
        "final_response_preview": metadata.get("final_response_preview"),
    }


def _friendly_structured_limitation(structured: StructuredOutputResult, fallback_message: str) -> str:
    return fallback_message


def _structured_raw_response(raw_response: str, structured: StructuredOutputResult) -> str:
    payload = {
        "original_response_preview": str(raw_response or "")[:1000],
        "final_response_preview": structured.metadata.get("final_response_preview"),
        "repaired": structured.repaired,
        "repair_attempts": structured.repair_attempts,
        "fallback_used": structured.fallback_used,
        "error_code": structured.error_code or structured.metadata.get("error_code"),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _build_compose_user_prompt(context: dict, review_type: str, symbol: str) -> str:
    output_schema = {
        "symbol": symbol or "从数据中识别",
        "review_type": review_type,
        "overall_score": 76,
        "rating": "excellent | good | average | poor",
        "score_detail": {
            key: {"score": 0, "max_score": value, "reason": "..."} for key, value in SCORE_DIMENSIONS.items()
        },
        "summary": "一句话核心结论",
        "strengths": ["..."],
        "weaknesses": ["..."],
        "mistake_tags": [],
        "improvement_suggestions": ["..."],
        "data_limitations": ["..."],
        "evidence_used": ["..."],
    }
    output_example = dict(TRADE_REVIEW_MAIN_EXAMPLE)
    output_example["symbol"] = symbol or output_example["symbol"]
    output_example["review_type"] = review_type
    return (
        "请基于以下交易数据和分析进行交易复盘，按 8 个维度打分。"
        "对年化 30% aggressive_growth 目标，仓位利用率、卖飞、错过强势股、好机会买太少都要严格评价。"
        "如果 single_trade_review 是仅买入且当前仍持仓，不能因为没有卖出记录而整体给 0 分；"
        "应评价买点、仓位、买入后表现、持仓状态、风险控制和退出计划。"
        "如果复盘范围内没有卖出交易，exit_quality_score 的 score 填 null，reason 写明尚未卖出暂不评价，后端会自动标记为不适用并从总分中剔除。"
        "如果数据不足，必须写入 data_limitations。"
        "只能输出 JSON object，不要 Markdown，不要代码块，不要额外解释，不要省略字段。\n\n"
        f"评分维度和满分:\n{json.dumps(SCORE_DIMENSIONS, ensure_ascii=False)}\n\n"
        f"输出 schema:\n{json.dumps(output_schema, ensure_ascii=False)}\n\n"
        f"完整输出样例:\n{json.dumps(output_example, ensure_ascii=False)}\n\n"
        f"交易数据和分析:\n{json.dumps(_compact_for_llm(context), ensure_ascii=False, default=str)[:12000]}"
    )


def _validate_review_output(parsed: dict, review_context: dict | None) -> dict:
    """Validate and normalize trade review output."""
    try:
        model = TradeReviewOutput.model_validate(parsed)
        return normalize_trade_review_output(model.model_dump(), review_context=review_context)
    except ValidationError as exc:
        raise TradeReviewAgentError("LLM_SCHEMA_INVALID", str(exc)) from exc
    except ValueError as exc:
        code = "LLM_SCORE_INVALID" if "score must be between" in str(exc) else "LLM_SCHEMA_INVALID"
        raise TradeReviewAgentError(code, str(exc)) from exc


def _repair_compose(llm_service, review_type: str, symbol: str, raw_response: str) -> str:
    """Deprecated: repair is now handled by StructuredOutputRuntime via contract. Kept for reference."""
    return llm_service.chat(
        [
            {"role": "system", "content": "你是 JSON 修复器，只输出符合 schema 的严格 JSON。"},
            {
                "role": "user",
                "content": (
                    "下面的模型输出不是有效交易复盘 JSON。请修复为严格 JSON。\n\n"
                    f"复盘类型: {review_type}\nsymbol: {symbol}\n\n"
                    f"原始输出:\n{raw_response}\n\n"
                    f"评分维度:\n{json.dumps(SCORE_DIMENSIONS, ensure_ascii=False)}"
                ),
            },
        ],
        temperature=0.0,
        max_tokens=None,
        response_format={"type": "json_object"},
    )


def _fallback_review_output(state: dict) -> dict:
    """Build fallback review output when compose fails."""
    return {
        "overall_score": 0,
        "rating": "poor",
        "score_detail": {},
        "summary": "复盘生成失败，使用保守兜底。",
        "strengths": [],
        "weaknesses": ["复盘流程异常"],
        "mistake_tags": [],
        "improvement_suggestions": ["建议重新生成复盘"],
        "data_limitations": ["graph_compose_failed"],
        "evidence_used": [],
    }


def _get_provider_snapshot(llm_service) -> dict:
    """Get LLM provider snapshot for metadata."""
    try:
        provider = llm_service.get_active_provider()
        if provider:
            return {
                "provider_name": provider.name,
                "base_url": provider.base_url,
                "model": provider.default_model,
            }
    except Exception:
        pass
    return {}


def _infer_start_date(trade_facts: dict) -> str | None:
    trades = trade_facts.get("trades", [])
    dates = [t.get("date") for t in trades if t.get("date")]
    return min(dates) if dates else None


def _infer_end_date(trade_facts: dict) -> str | None:
    trades = trade_facts.get("trades", [])
    dates = [t.get("date") for t in trades if t.get("date")]
    return max(dates) if dates else None


def _build_run_trace(node_traces: list[dict]) -> list[dict]:
    """Convert node traces to run_trace format."""
    run_trace: list[dict] = []
    for nt in node_traces:
        run_trace.append({
            "event": f"node_{nt.get('status', 'unknown')}",
            "node_name": nt.get("node_name"),
            "elapsed_ms": nt.get("elapsed_ms", 0),
            "tools_called": nt.get("tools_called", []),
            "rounds_used": nt.get("rounds_used", 0),
            "fallback_used": nt.get("fallback_used", False),
        })
    return run_trace
