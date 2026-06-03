"""LangGraph nodes for the daily position review graph.

Every node is created via a make_* factory that closes over deps.
Nodes never read _deps from state — they use the closure.
Parallel nodes write only to their own fields.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.agents.daily_review_evidence_cards import (
    DailyReviewEvidenceCardPack,
    DataQualitySummary,
    SubAgentTrace,
    build_fallback_macro_card,
    build_fallback_symbol_card,
    compute_card_pack_summary,
)
from app.agents.evidence_schema import build_daily_position_review_evidence_pack_from_cards
from app.agents.evidence_summary import build_evidence_summary
from app.agents.graph.result_contract import build_agent_metadata, build_run_trace_from_state, classify_agent_status
from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.graph.trace import (
    finish_node_trace,
    now_iso,
    start_node_trace,
)
from app.agents.trace_summary import build_run_trace_summary
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
from app.services.daily_review_evidence_card_builder import (
    DAILY_REVIEW_SYMBOL_CARD_LIMIT,
    _select_focus_symbols_for_cards,
)

# Compact position keys for LLM input
_COMPACT_POSITION_KEYS = (
    "symbol",
    "normalized_symbol",
    "quantity",
    "avg_cost",
    "average_cost",
    "average_cost_price",
    "current_price",
    "mark_price",
    "market_value",
    "position_value",
    "position_pct",
    "weight",
    "daily_pnl",
    "contribution_ratio",
    "unrealized_pnl",
    "unrealized_pnl_pct",
    "unrealized_pnl_percent",
    "realized_pnl",
    "daily_change_percent",
    "previous_day_change_percent",
    "is_major_contributor",
    "is_major_drag",
)


def _compact_positions_for_llm(positions: list[dict]) -> list[dict]:
    compacted = []
    for item in positions:
        if isinstance(item, dict):
            compacted.append({key: item.get(key) for key in _COMPACT_POSITION_KEYS if key in item})
    return compacted


# === Node factories ===


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


def make_load_daily_review_context_node(deps):
    """Load deterministic context from IBKR via review service."""
    def load_daily_review_context_node(state: dict) -> dict:
        trace = start_node_trace("load_daily_review_context")
        import time as _time
        _t0 = _time.monotonic()
        try:
            report_date = state["report_date"]
            deterministic_context = deps.review_service.build_review_context(
                report_date, include_public_context=True, include_benchmarks=True,
            )
            positions = deterministic_context.get("positions", [])
            compact_positions = _compact_positions_for_llm(positions)

            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="daily_position_review", node_name="load_daily_review_context",
                tool_name="ibkr_build_review_context", ok=True, latency_ms=latency_ms,
            )
            result = {
                "deterministic_context": deterministic_context,
                "compact_positions": compact_positions,
            }
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="daily_position_review", node_name="load_daily_review_context",
                tool_name="ibkr_build_review_context", ok=False, latency_ms=latency_ms,
                error_message=str(exc)[:200],
            )
            trace = finish_node_trace(trace, "failed", error=str(exc)[:200])
            return {
                "errors": [f"load_daily_review_context: {str(exc)[:200]}"],
                "node_traces": [trace],
            }
    return load_daily_review_context_node


def make_select_focus_symbols_node(deps):
    """Select focus symbols for evidence card generation."""
    def select_focus_symbols_node(state: dict) -> dict:
        trace = start_node_trace("select_focus_symbols")
        try:
            ctx = state.get("deterministic_context") or {}
            positions = ctx.get("positions", [])
            rankings = ctx.get("rankings", {})
            report_date = state["report_date"]

            focus_position_items = _select_focus_symbols_for_cards(
                positions=positions,
                rankings=rankings,
                report_date=report_date,
                limit=DAILY_REVIEW_SYMBOL_CARD_LIMIT,
            )
            focus_symbols = [
                str(item.get("normalized_symbol", item.get("symbol", "")))
                for item in focus_position_items
            ]

            result = {
                "focus_position_items": focus_position_items,
                "focus_symbols": focus_symbols,
            }
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "failed", error=str(exc)[:200])
            return {
                "errors": [f"select_focus_symbols: {str(exc)[:200]}"],
                "node_traces": [trace],
            }
    return select_focus_symbols_node


def make_symbol_cards_node(deps):
    """Generate SymbolEvidenceCards in parallel using sub-agents."""
    def symbol_cards_node(state: dict) -> dict:
        trace = start_node_trace("symbol_cards")
        tools_called: list[str] = []
        data_limitations: list[str] = []
        warnings: list[str] = []

        try:
            focus_position_items = state.get("focus_position_items") or []
            report_date = state["report_date"]
            ctx = state.get("deterministic_context") or {}
            symbol_public_context = ctx.get("symbol_public_context", {})
            benchmarks = ctx.get("benchmarks", {})

            if not focus_position_items:
                trace = finish_node_trace(trace, "success")
                return {
                    "symbol_cards": [],
                    "symbol_cards_public_data_mode": "unavailable",
                    "node_traces": [trace],
                }

            symbol_agent = deps.symbol_agent
            if symbol_agent is None:
                fallback_cards = [
                    build_fallback_symbol_card(
                        symbol=str(item.get("symbol", "")),
                        normalized_symbol=str(item.get("normalized_symbol", item.get("symbol", ""))),
                        report_date=state["report_date"],
                        position_item=item,
                        reason="symbol_agent_not_configured",
                    )
                    for item in focus_position_items
                ]
                warnings.append("symbol_agent_not_configured: using fallback cards")
                data_limitations.append("symbol_agent_not_configured")
                trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason="symbol_agent_not_configured")
                return {
                    "symbol_cards": fallback_cards,
                    "symbol_cards_public_data_mode": "unavailable",
                    "data_limitations": data_limitations,
                    "warnings": warnings,
                    "node_traces": [trace],
                }

            related_asset_service = deps.related_asset_service

            cards = _generate_symbol_cards_parallel(
                focus_position_items=focus_position_items,
                report_date=report_date,
                symbol_public_context=symbol_public_context,
                benchmark_context=benchmarks,
                symbol_agent=symbol_agent,
                related_asset_service=related_asset_service,
                tools_called=tools_called,
                data_limitations=data_limitations,
                warnings=warnings,
            )

            public_mode = "subagent"
            trace = finish_node_trace(trace, "success", tools_called=tools_called)
            return {
                "symbol_cards": cards,
                "symbol_cards_public_data_mode": public_mode,
                "data_limitations": data_limitations,
                "warnings": warnings,
                "node_traces": [trace],
            }
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "symbol_cards": [],
                "symbol_cards_public_data_mode": "unavailable",
                "warnings": [f"symbol_cards: {str(exc)[:200]}"],
                "node_traces": [trace],
            }
    return symbol_cards_node


def _generate_symbol_cards_parallel(
    focus_position_items: list[dict],
    report_date: str,
    symbol_public_context: dict,
    benchmark_context: dict,
    symbol_agent,
    related_asset_service,
    tools_called: list[str],
    data_limitations: list[str],
    warnings: list[str],
) -> list:
    """Generate symbol cards in parallel with fallback on failure."""
    from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent

    cards = []
    errors = []

    with ThreadPoolExecutor(max_workers=len(focus_position_items)) as executor:
        futures = {}
        for item in focus_position_items:
            symbol = str(item.get("symbol", ""))
            normalized = str(item.get("normalized_symbol", symbol))
            public_ctx = symbol_public_context.get(normalized, symbol_public_context.get(symbol, {}))

            if related_asset_service is not None:
                try:
                    related_asset_context = related_asset_service.build_related_asset_context(
                        symbol=symbol,
                        normalized_symbol=normalized,
                        report_date=report_date,
                        public_context=public_ctx,
                        benchmark_context=benchmark_context,
                    )
                    public_ctx = {**public_ctx, "related_asset_context": related_asset_context}
                except Exception:
                    pass

            future = executor.submit(
                symbol_agent.generate_symbol_card,
                report_date=report_date,
                symbol=symbol,
                normalized_symbol=normalized,
                position_item=item,
                public_context=public_ctx,
                benchmark_context=benchmark_context,
            )
            futures[future] = (symbol, normalized, item)

        for future in as_completed(futures):
            symbol, normalized, item = futures[future]
            try:
                card = future.result()
                cards.append(card)
                tools_called.append(f"symbol_agent:{normalized}")
            except Exception as exc:
                fallback_card = build_fallback_symbol_card(
                    symbol=symbol,
                    normalized_symbol=normalized,
                    report_date=report_date,
                    position_item=item,
                    reason=str(exc)[:200],
                )
                cards.append(fallback_card)
                errors.append(f"Symbol card failed for {symbol}: {exc}")

    for err in errors:
        warnings.append(err)

    return cards


def make_macro_card_node(deps):
    """Generate MacroEvidenceCard using macro sub-agent."""
    def macro_card_node(state: dict) -> dict:
        trace = start_node_trace("macro_card")
        tools_called: list[str] = []
        data_limitations: list[str] = []
        warnings: list[str] = []

        try:
            ctx = state.get("deterministic_context") or {}
            report_date = state["report_date"]
            benchmarks = ctx.get("benchmarks", {})
            focus_symbols = state.get("focus_symbols") or []
            overview = ctx.get("overview", {})
            account_return = overview.get("daily_return_percent")

            # Fetch macro news context if longbridge client available
            macro_news_context = None
            if deps.longbridge_client is not None:
                try:
                    macro_news_context = _fetch_macro_news_context(deps.longbridge_client, focus_symbols)
                    tools_called.append("search_macro_news")
                except Exception as exc:
                    warnings.append(f"Macro news context fetch failed: {exc}")
                    macro_news_context = None

            if deps.macro_agent is None:
                fallback_card = build_fallback_macro_card(
                    report_date=report_date,
                    benchmark_context=benchmarks,
                    reason="macro_agent_not_configured",
                )
                warnings.append("macro_agent_not_configured: using fallback card")
                data_limitations.append("macro_agent_not_configured")
                trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason="macro_agent_not_configured")
                return {
                    "macro_card": fallback_card,
                    "macro_public_data_mode": "unavailable",
                    "data_limitations": data_limitations,
                    "warnings": warnings,
                    "node_traces": [trace],
                }

            macro_card = deps.macro_agent.generate_macro_card(
                report_date=report_date,
                benchmark_context=benchmarks,
                focus_symbols=focus_symbols,
                account_return=account_return,
                macro_news_context=macro_news_context,
            )
            tools_called.append("macro_agent")

            trace = finish_node_trace(trace, "success", tools_called=tools_called)
            return {
                "macro_card": macro_card,
                "macro_public_data_mode": "subagent",
                "data_limitations": data_limitations,
                "warnings": warnings,
                "node_traces": [trace],
            }
        except Exception as exc:
            fallback_card = build_fallback_macro_card(
                report_date=state.get("report_date", ""),
                benchmark_context=ctx.get("benchmarks", {}),
                reason=str(exc)[:200],
            )
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "macro_card": fallback_card,
                "macro_public_data_mode": "unavailable",
                "warnings": [f"macro_card: {str(exc)[:200]}"],
                "node_traces": [trace],
            }
    return macro_card_node


def _fetch_macro_news_context(longbridge_client, focus_symbols: list[str]) -> dict:
    keywords = [
        "market", "Fed", "rate", "inflation", "CPI",
        "Nasdaq", "semiconductor", "AI", "crypto", "tech", "China tech",
    ]
    all_items: list[dict] = []
    seen_ids: set[str] = set()
    for keyword in keywords:
        try:
            response = longbridge_client.search_macro_news(keyword=keyword, limit=5)
            for item in response.items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    all_items.append(item.model_dump())
        except Exception:
            pass
    all_items.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
    return {"macro_news": all_items[:20], "keywords_searched": keywords}


def make_portfolio_attribution_node(deps):
    """Deterministic portfolio attribution summary."""
    def portfolio_attribution_node(state: dict) -> dict:
        trace = start_node_trace("portfolio_attribution")
        try:
            ctx = state.get("deterministic_context") or {}
            overview = ctx.get("overview", {})
            rankings = ctx.get("rankings", {})
            positions = ctx.get("positions", [])
            attribution_quality = ctx.get("attribution_quality", {})

            top_contributors = rankings.get("profit_contributors") or []
            top_drags = rankings.get("loss_drags") or []

            contributor_summary = "、".join(
                str(item.get("symbol", "")) for item in top_contributors[:3] if item.get("symbol")
            ) or "暂无"
            drag_summary = "、".join(
                str(item.get("symbol", "")) for item in top_drags[:3] if item.get("symbol")
            ) or "暂无"

            key_findings = []
            daily_pnl = overview.get("daily_pnl")
            daily_return = overview.get("daily_return_percent")
            if daily_pnl is not None:
                key_findings.append(f"当日盈亏 {daily_pnl}，收益率 {daily_return}%")
            if contributor_summary != "暂无":
                key_findings.append(f"主要贡献: {contributor_summary}")
            if drag_summary != "暂无":
                key_findings.append(f"主要拖累: {drag_summary}")

            card = {
                "card_type": "portfolio_attribution",
                "summary": f"当日账户盈亏 {daily_pnl}，收益率 {daily_return}%。贡献来自 {contributor_summary}，拖累来自 {drag_summary}。",
                "account_return": daily_return,
                "daily_pnl": daily_pnl,
                "top_contributors": [
                    {"symbol": item.get("symbol"), "daily_pnl": item.get("daily_pnl"), "contribution_ratio": item.get("contribution_ratio")}
                    for item in top_contributors[:5]
                ],
                "top_drags": [
                    {"symbol": item.get("symbol"), "daily_pnl": item.get("daily_pnl"), "contribution_ratio": item.get("contribution_ratio")}
                    for item in top_drags[:5]
                ],
                "attribution_quality": attribution_quality,
                "key_findings": key_findings,
                "data_limitations": [],
            }

            trace = finish_node_trace(trace, "success")
            return {"portfolio_attribution_card": card, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "portfolio_attribution_card": {"card_type": "portfolio_attribution", "summary": f"归因生成失败: {exc}", "data_limitations": [str(exc)[:200]]},
                "node_traces": [trace],
            }
    return portfolio_attribution_node


def make_risk_watch_node(deps):
    """Deterministic risk watch summary."""
    def risk_watch_node(state: dict) -> dict:
        trace = start_node_trace("risk_watch")
        try:
            ctx = state.get("deterministic_context") or {}
            risk = ctx.get("risk", {})
            positions = ctx.get("positions", [])
            overview = ctx.get("overview", {})

            max_position = risk.get("max_position") or {}
            risk_flags = [str(item) for item in risk.get("risk_flags") or []]
            cash_ratio = overview.get("cash_ratio")

            # Identify large daily movers
            large_move_symbols = []
            for pos in positions:
                change_pct = abs(pos.get("daily_change_percent") or 0)
                if change_pct > 5.0:
                    large_move_symbols.append({
                        "symbol": pos.get("normalized_symbol", pos.get("symbol")),
                        "daily_change_percent": pos.get("daily_change_percent"),
                        "weight": pos.get("weight"),
                    })

            watch_points = []
            if max_position:
                watch_points.append(f"最大持仓 {max_position.get('symbol', 'N/A')} 权重 {max_position.get('weight', 'N/A')}")
            if cash_ratio is not None and cash_ratio < 0.05:
                watch_points.append("现金比例偏低，需关注流动性")
            if large_move_symbols:
                watch_points.append(f"{len(large_move_symbols)} 只标的当日波动超 5%")

            card = {
                "card_type": "daily_risk_watch",
                "summary": f"集中度 {risk.get('max_single_position_weight', 'N/A')}，现金比例 {cash_ratio}。{len(risk_flags)} 个风险标志。",
                "position_concentration": risk.get("max_single_position_weight"),
                "cash_pct": cash_ratio,
                "large_move_symbols": large_move_symbols,
                "risk_flags": risk_flags,
                "watch_points": watch_points,
                "data_limitations": [],
            }

            trace = finish_node_trace(trace, "success")
            return {"risk_watch_card": card, "node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {
                "risk_watch_card": {"card_type": "daily_risk_watch", "summary": f"风险监控生成失败: {exc}", "data_limitations": [str(exc)[:200]]},
                "node_traces": [trace],
            }
    return risk_watch_node


def make_build_card_pack_node(deps):
    """Fan-in: assemble DailyReviewEvidenceCardPack from all cards."""
    def build_card_pack_node(state: dict) -> dict:
        trace = start_node_trace("build_card_pack")
        try:
            ctx = state.get("deterministic_context") or {}
            report_date = state["report_date"]
            positions = ctx.get("positions", [])
            rankings = ctx.get("rankings", {})
            risk = ctx.get("risk", {})
            overview = ctx.get("overview", {})
            attribution_quality = ctx.get("attribution_quality", {})
            benchmarks = ctx.get("benchmarks", {})
            data_quality_ctx = ctx.get("data_quality", {})

            symbol_cards = state.get("symbol_cards") or []
            macro_card = state.get("macro_card")

            account_facts = {
                "report_date": report_date,
                "overview": overview,
                "attribution_quality": attribution_quality,
                "data_quality": data_quality_ctx,
            }

            # Assess data quality
            quality_overall = "high"
            low_count = sum(1 for card in symbol_cards if getattr(card, "evidence_quality", "medium") == "low")
            if low_count > 0:
                quality_overall = "medium"
            if low_count > len(symbol_cards) // 2:
                quality_overall = "low"

            subagent_trace = SubAgentTrace()
            evidence_used = [
                "IBKR account snapshot: deterministic",
                "IBKR position snapshot: deterministic",
                "IBKR rankings: deterministic",
                "IBKR risk analysis: deterministic",
                f"Sub-agent symbol cards: {len(symbol_cards)} cards generated",
                f"Sub-agent macro card: {'yes' if macro_card else 'no'}",
            ]

            data_quality = DataQualitySummary(
                overall=quality_overall,
                warnings=[],
                limitations=[],
            )

            budget_report = {
                "symbol_cards_count": len(symbol_cards),
                "focus_position_items_count": len(state.get("focus_position_items") or []),
                "macro_card_present": macro_card is not None,
                "fallback_symbol_cards": low_count,
            }

            pack = DailyReviewEvidenceCardPack(
                report_date=report_date,
                account_facts=account_facts,
                position_facts=positions,
                rankings=rankings,
                risk=risk,
                attribution_quality=attribution_quality,
                symbol_cards=symbol_cards,
                macro_card=macro_card,
                data_quality=data_quality,
                evidence_used=evidence_used,
                subagent_trace=subagent_trace,
                budget_report=budget_report,
            )

            card_pack_summary = compute_card_pack_summary(pack)
            evidence_pack = build_daily_position_review_evidence_pack_from_cards(pack.to_dict())

            trace = finish_node_trace(trace, "success")
            return {
                "card_pack": pack,
                "card_pack_summary": card_pack_summary.to_dict(),
                "evidence_pack": evidence_pack,
                "node_traces": [trace],
            }
        except Exception as exc:
            trace = finish_node_trace(trace, "failed", error=str(exc)[:200])
            return {
                "errors": [f"build_card_pack: {str(exc)[:200]}"],
                "node_traces": [trace],
            }
    return build_card_pack_node


def make_compose_daily_review_node(deps):
    """Compose final daily review using LLM with card-based context."""
    def compose_daily_review_node(state: dict) -> dict:
        trace = start_node_trace("compose_daily_review")
        try:
            report_date = state["report_date"]
            card_pack = state.get("card_pack")
            compact_positions = state.get("compact_positions") or []
            deterministic_context = state.get("deterministic_context") or {}

            if card_pack is None:
                raise ValueError("card_pack is None, cannot compose review")

            # Import here to avoid circular dependency
            from app.services.daily_position_review_agent import (
                DailyPositionReviewAgent,
                SYSTEM_PROMPT_SUBAGENT_CARDS,
            )

            # Build prompt and tools using agent's existing methods
            agent = _AgentHelper(deps.llm_service)
            user_prompt = agent.build_tool_user_prompt_subagent_cards(report_date, card_pack, compact_positions)
            tools = agent.build_tools_subagent_cards(card_pack, compact_positions, report_date)

            from app.agents.runtime import ToolCallingRuntime
            input_char_budget, output_token_limit = _active_token_budget(deps.llm_service)
            system_prompt, prompt_metadata = resolve_runtime_prompt(
                getattr(deps, "prompt_service", None),
                "daily_position_review_main",
                SYSTEM_PROMPT_SUBAGENT_CARDS,
            )
            runtime = ToolCallingRuntime(
                deps.llm_service,
                max_rounds=4,
                max_observation_chars=input_char_budget,
                max_tokens=output_token_limit,
                agent_name="daily_position_review",
                node_name="compose_daily_review",
                prompt_metadata=prompt_metadata,
                call_type="compose",
                run_id=state.get("agent_run_id"),
            )

            result = runtime.run(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=tools,
                response_format={"type": "json_object"},
                plan=[
                    "读取 IBKR 账户和持仓快照（从证据卡片），结合子 Agent 生成的公开解释材料",
                    "解释主要贡献和拖累，使用证据卡片中的摘要而非原始大新闻/估值数据",
                    "识别账户风险变化，输出明日关注清单和观察条件",
                    "输出严格 JSON",
                ],
                initial_tool_calls=[
                    {"name": "get_daily_position_review_context", "arguments": {"report_date": report_date}},
                ],
            )

            raw_response = result["content"]
            llm_trace = result["trace"]

            structured = _parse_validate_repair_daily_review(
                llm_service=deps.llm_service,
                report_date=report_date,
                raw_response=raw_response,
                trace=llm_trace,
                deterministic_context=deterministic_context,
                card_pack=card_pack,
                compact_positions=compact_positions,
            )
            structured_metadata = structured.metadata
            if not structured.ok or structured.payload is None:
                raise ValueError(structured.error_message or structured.error_code or "daily_position_review_main structured output failed")

            validated = _normalize_daily_review_payload(
                structured.payload,
                report_date=report_date,
                deterministic_context=deterministic_context,
            )
            raw_response_clean = _format_structured_raw_response(raw_response, structured)

            # Strip thinking tags from all text fields
            validated = _strip_thinking_from_output(validated)

            provider_snapshot = _provider_snapshot(deps.llm_service)

            llm_trace.append(_structured_output_result_event(structured_metadata))
            trace = finish_node_trace(
                trace,
                "success",
                tools_called=["ToolCallingRuntime"],
                runtime_trace=llm_trace,
                structured_output=structured_metadata,
                fallback_used=structured.fallback_used,
                fallback_reason=structured_metadata.get("fallback_reason"),
            )
            return {
                "review_output": validated,
                "raw_llm_response": raw_response_clean,
                "model_provider_snapshot": provider_snapshot,
                "prompt_metadata": {"daily_position_review_main": prompt_metadata},
                "structured_output": structured_metadata,
                "fallback_used": structured.fallback_used,
                "fallback_reason": structured_metadata.get("fallback_reason") if structured.fallback_used else state.get("fallback_reason"),
                "node_traces": [trace],
            }
        except Exception as exc:
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            # Generate fallback
            ctx = state.get("deterministic_context") or {}
            fallback = _build_fallback_review_payload(
                report_date=state.get("report_date", ""),
                context=ctx,
                parse_error=str(exc)[:200],
            )
            return {
                "review_output": fallback,
                "raw_llm_response": f"fallback_due_to: {str(exc)[:200]}",
                "model_provider_snapshot": {},
                "warnings": [f"compose_daily_review: {str(exc)[:200]}"],
                "fallback_used": True,
                "fallback_reason": str(exc)[:200],
                "node_traces": [trace],
            }
    return compose_daily_review_node


def make_persist_daily_review_node(deps):
    """Persist the daily review document."""
    def persist_daily_review_node(state: dict) -> dict:
        trace = start_node_trace("persist_daily_review")
        try:
            report_date = state["report_date"]
            review_output = state.get("review_output") or {}
            deterministic_context = state.get("deterministic_context") or {}
            evidence_pack = state.get("evidence_pack") or {}
            card_pack = state.get("card_pack")
            card_pack_summary = state.get("card_pack_summary") or {}
            raw_llm_response = state.get("raw_llm_response") or ""
            model_provider_snapshot = state.get("model_provider_snapshot") or {}

            # Build run_trace from all node traces including persist
            finished_trace = finish_node_trace(trace, "success")
            all_traces = (state.get("node_traces") or []) + [finished_trace]
            run_trace = build_run_trace_from_state(state, finished_trace)
            run_trace_summary = build_run_trace_summary(run_trace)

            # Build evidence summary
            evidence_summary = build_evidence_summary(evidence_pack, run_trace)

            base_metadata = build_metadata(
                agent_version=DAILY_POSITION_REVIEW_AGENT_VERSION,
                prompt_version=DAILY_POSITION_REVIEW_PROMPT_VERSION,
                schema_version=OUTPUT_SCHEMA_VERSION,
                toolset_version=DAILY_POSITION_REVIEW_TOOLSET_VERSION,
                evidence_builder_version=DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
                agent_mode=DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
                model_provider_snapshot=model_provider_snapshot,
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
                fallback_used=state.get("fallback_used", False),
                fallback_reason=state.get("fallback_reason"),
            )
            metadata["prompt_metadata"] = state.get("prompt_metadata") or {}
            if state.get("structured_output"):
                metadata["structured_output"] = state.get("structured_output")
            if state.get("agent_run_id"):
                metadata["agent_run_id"] = state.get("agent_run_id")

            now = now_iso()
            compact_ctx = _compact_context_for_storage(deterministic_context)

            document: dict = {
                **review_output,
                "id": report_date,
                "review_type": "daily_position_review",
                "metadata": metadata,
                "evidence_summary": evidence_summary,
                "run_trace_summary": run_trace_summary,
                "deterministic_context": compact_ctx,
                "run_trace": run_trace,
                "raw_llm_response": raw_llm_response,
                "model_provider_snapshot": model_provider_snapshot,
                "data_source_summary": deterministic_context.get("data_sources") or {},
                # Card mode fields
                "agent_mode": DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
                "subagent_card_pack": card_pack.to_dict() if hasattr(card_pack, "to_dict") else (card_pack or {}),
                "subagent_trace": (card_pack.subagent_trace.to_dict() if hasattr(card_pack, "subagent_trace") else {}) if card_pack else {},
                "evidence_card_summary": card_pack_summary,
                # Graph-specific fields
                "graph_node_traces": all_traces,
                "graph_version": DAILY_POSITION_REVIEW_GRAPH_VERSION,
                "fallback_used": state.get("fallback_used", False),
                "fallback_reason": state.get("fallback_reason"),
                "created_at": now,
                "updated_at": now,
            }
            if state.get("agent_run_id"):
                document["agent_run_id"] = state.get("agent_run_id")
            document["status"] = classify_agent_status(document)

            saved = deps.repository.save_review(document)
            email_document = {
                **document,
                "created_at": saved.get("created_at") or document.get("created_at"),
                "updated_at": saved.get("updated_at") or document.get("updated_at"),
            }
            return {"saved_document": email_document, "node_traces": [finished_trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            error_trace = start_node_trace("persist_daily_review")
            error_trace = finish_node_trace(error_trace, "failed", error=error_msg)
            return {"errors": [f"persist_daily_review: {error_msg}"], "node_traces": [error_trace]}
    return persist_daily_review_node


def make_optional_email_summary_node(deps):
    """Send email if auto_email is True. Failure only writes warning."""
    def optional_email_summary_node(state: dict) -> dict:
        trace = start_node_trace("optional_email_summary")
        try:
            auto_email = state.get("auto_email", False)
            if not auto_email:
                trace = finish_node_trace(trace, "success", tools_called=[])
                return {"node_traces": [trace]}

            saved_document = state.get("saved_document")
            if not saved_document:
                trace = finish_node_trace(trace, "success", tools_called=[])
                return {"warnings": ["optional_email: no saved_document to email"], "node_traces": [trace]}

            if deps.email_service is None:
                trace = finish_node_trace(trace, "success", tools_called=[])
                return {"warnings": ["optional_email: email_service not configured"], "node_traces": [trace]}

            try:
                sent = deps.email_service.send_daily_position_review(saved_document)
                if sent:
                    trace = finish_node_trace(trace, "success", tools_called=["send_daily_position_review"])
                else:
                    trace = finish_node_trace(trace, "success", tools_called=[])
            except Exception as exc:
                trace = finish_node_trace(trace, "success", tools_called=[])
                return {"warnings": [f"optional_email: {str(exc)[:200]}"], "node_traces": [trace]}

            return {"node_traces": [trace]}
        except Exception as exc:
            trace = finish_node_trace(trace, "success")
            return {"warnings": [f"optional_email: {str(exc)[:200]}"], "node_traces": [trace]}
    return optional_email_summary_node


# === Helpers ===

def _build_run_trace(node_traces: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in t.items() if k != "_start_perf"}
        for t in node_traces
        if isinstance(t, dict)
    ]


def _compact_context_for_storage(context: dict) -> dict:
    from app.agents.context_budget import enforce_section_budget
    compacted = {
        "report_date": context.get("report_date"),
        "data_sources": context.get("data_sources"),
        "overview": context.get("overview"),
        "positions": context.get("positions"),
        "rankings": {
            key: value[:5] if isinstance(value, list) else value
            for key, value in (context.get("rankings") or {}).items()
        },
        "risk": context.get("risk"),
        "benchmarks": context.get("benchmarks"),
        "focus_symbols": context.get("focus_symbols"),
        "attribution_quality": context.get("attribution_quality"),
        "data_quality": context.get("data_quality"),
    }
    return enforce_section_budget("daily_position_context", compacted)


def _active_token_budget(llm_service) -> tuple[int, int]:
    from app.services.llm_service import DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_INPUT_TOKEN_LIMIT, DEFAULT_OUTPUT_TOKEN_LIMIT
    provider = llm_service.get_active_provider() if llm_service is not None else None
    input_token_limit = _coerce_positive_int(getattr(provider, "input_token_limit", None), DEFAULT_INPUT_TOKEN_LIMIT)
    output_token_limit = _coerce_positive_int(getattr(provider, "output_token_limit", None), DEFAULT_OUTPUT_TOKEN_LIMIT)
    return input_token_limit, output_token_limit


def _provider_snapshot(llm_service) -> dict:
    from app.services.llm_service import DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_INPUT_TOKEN_LIMIT, DEFAULT_OUTPUT_TOKEN_LIMIT
    active_provider = llm_service.get_active_provider() if llm_service is not None else None
    if active_provider is None:
        return {}
    return {
        "provider_name": getattr(active_provider, "name", ""),
        "base_url": getattr(active_provider, "base_url", ""),
        "model": getattr(active_provider, "default_model", ""),
        "context_window_tokens": _coerce_positive_int(getattr(active_provider, "context_window_tokens", None), DEFAULT_CONTEXT_WINDOW_TOKENS),
        "input_token_limit": _coerce_positive_int(getattr(active_provider, "input_token_limit", None), DEFAULT_INPUT_TOKEN_LIMIT),
        "output_token_limit": _coerce_positive_int(getattr(active_provider, "output_token_limit", None), DEFAULT_OUTPUT_TOKEN_LIMIT),
    }


def _coerce_positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _strip_thinking_from_output(payload: dict) -> dict:
    """Strip thinking tags from all text fields in the review output."""
    text_fields = [
        "summary", "account_conclusion", "attribution_summary",
        "market_context", "risk_analysis", "operation_observation",
        "major_contributors_analysis", "major_drags_analysis",
        "focus_symbol_analyses", "tomorrow_watchlist",
    ]
    result = dict(payload)
    for field in text_fields:
        value = result.get(field)
        if isinstance(value, str):
            result[field] = strip_thinking_tags(value)
        elif isinstance(value, list):
            result[field] = _strip_thinking_from_list(value)
    return result


def _strip_thinking_from_list(items: list) -> list:
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(strip_thinking_tags(item))
        elif isinstance(item, dict):
            cleaned = {}
            for k, v in item.items():
                if isinstance(v, str):
                    cleaned[k] = strip_thinking_tags(v)
                elif isinstance(v, list):
                    cleaned[k] = [strip_thinking_tags(s) if isinstance(s, str) else s for s in v]
                else:
                    cleaned[k] = v
            result.append(cleaned)
        else:
            result.append(item)
    return result


class _AgentHelper:
    """Thin helper to reuse agent prompt/tool building logic."""

    def __init__(self, llm_service):
        self.llm_service = llm_service

    def build_tool_user_prompt_subagent_cards(self, report_date, card_pack, compact_positions):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent
        from app.agents.output_schemas import DailyPositionReviewOutput
        import json

        schema = {
            "report_date": report_date,
            "summary": "一句话总结今日账户表现",
            "account_conclusion": "今日账户结论",
            "attribution_summary": "账户涨跌归因",
            "major_contributors_analysis": [{"symbol": "AMD.US", "analysis": "..."}],
            "major_drags_analysis": [{"symbol": "NVDA.US", "analysis": "..."}],
            "focus_symbol_analyses": [
                {
                    "symbol": "AMD.US",
                    "price_action": "...",
                    "account_impact": "...",
                    "possible_reasons": ["..."],
                    "valuation_note": "...",
                    "cost_position_note": "...",
                    "watch_points": ["..."],
                    "data_limitations": ["..."],
                }
            ],
            "market_context": "市场和行业背景",
            "risk_analysis": "仓位风险变化",
            "tomorrow_watchlist": [
                {
                    "symbol": "AMD.US",
                    "reason": "...",
                    "key_levels": ["20日线", "前高"],
                    "events": ["..."],
                    "conditions": ["如果...则继续观察", "如果...则关注转弱"],
                }
            ],
            "operation_observation": "操作观察建议，不是强买强卖",
            "data_limitations": ["..."],
            "evidence_used": ["tool_name: brief reason"],
        }

        card_summary_lines = [f"报告日期: {report_date}", f"子 Agent 证据卡片模式: {len(card_pack.symbol_cards)} 个标的卡片"]
        for card in card_pack.symbol_cards:
            quality_marker = {"high": "✓", "medium": "○", "low": "✗"}.get(card.evidence_quality, "○")
            card_summary_lines.append(
                f"  {quality_marker} {card.symbol}: "
                f"账户贡献={card.account_impact.daily_pnl}, "
                f"涨跌={card.price_action.day_change_percent}%, "
                f"质量={card.evidence_quality}"
            )

        if card_pack.macro_card:
            card_summary_lines.append(
                f"  宏观卡片: regime={card_pack.macro_card.market_regime or 'N/A'}, "
                f"risk_sentiment={card_pack.macro_card.risk_sentiment or 'N/A'}"
            )

        card_summary_text = "\n".join(card_summary_lines)

        return (
            "请基于子 Agent 证据卡片生成每日持仓复盘。\n"
            "IBKR 核心账户事实（持仓、权重、盈亏贡献）来自确定性数据，不得修改。\n"
            "公开解释材料（新闻、估值、财报、技术面、宏观）来自子 Agent 摘要的证据卡片。\n"
            "不要重新计算 IBKR 数字，只基于卡片摘要进行解释和归因。\n"
            "明日关注清单只能给观察条件，不要直接喊买卖。\n"
            "如果公开数据不足，必须写入 data_limitations。\n\n"
            f"{card_summary_text}\n\n"
            "最终只输出严格 JSON object，不要 Markdown，不要代码块，不要额外解释，不要省略字段。\n"
            "不确定字段填 null / []，并写入 data_limitations。\n"
            "简短完整输出样例:\n"
            f"{json.dumps({'report_date': report_date, 'summary': '今日账户小幅上涨，主要由 AMD 贡献。', 'account_conclusion': '账户归因优先，公开解释只作为辅助。', 'attribution_summary': '主要贡献和拖累以 IBKR 数据为准。', 'major_contributors_analysis': [{'symbol': 'AMD.US', 'analysis': '仓位贡献为正。'}], 'major_drags_analysis': [], 'focus_symbol_analyses': [{'symbol': 'AMD.US', 'price_action': '跑赢 QQQ。', 'account_impact': '对账户正贡献较高。', 'possible_reasons': ['板块偏强'], 'valuation_note': '估值需继续观察。', 'cost_position_note': '成本以 IBKR 为准。', 'watch_points': ['观察成交量'], 'data_limitations': []}], 'market_context': '科技相对偏强。', 'risk_analysis': '关注集中度。', 'tomorrow_watchlist': [{'symbol': 'AMD.US', 'reason': '重点持仓', 'key_levels': [], 'events': [], 'conditions': ['观察是否继续跑赢基准']}], 'operation_observation': '仅作观察，不构成买卖指令。', 'data_limitations': [], 'evidence_used': ['IBKR account snapshot', 'SymbolEvidenceCard', 'MacroEvidenceCard']}, ensure_ascii=False)}\n\n"
            f"所有 schema 字段都必须存在:\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def build_tools_subagent_cards(self, card_pack, compact_positions, expected_report_date):
        from app.agents.runtime import AgentTool

        def handler(report_date: str) -> dict:
            if report_date != expected_report_date:
                return {"error": f"report_date mismatch: requested {report_date}, expected {expected_report_date}"}
            return {
                "report_date": card_pack.report_date,
                "account_facts": card_pack.account_facts,
                "positions": compact_positions,
                "rankings": card_pack.rankings,
                "risk": card_pack.risk,
                "attribution_quality": card_pack.attribution_quality,
                "benchmarks": card_pack.to_dict().get("benchmarks", {}),
                "symbol_cards": [card.to_dict() for card in card_pack.symbol_cards],
                "macro_card": card_pack.macro_card.to_dict() if card_pack.macro_card else None,
                "data_quality": card_pack.data_quality.to_dict(),
                "subagent_trace": card_pack.subagent_trace.to_dict(),
            }

        return [
            AgentTool(
                "get_daily_position_review_context",
                "Read IBKR account/position attribution and sub-agent evidence cards for one report date.",
                {
                    "type": "object",
                    "properties": {"report_date": {"type": "string"}},
                    "required": ["report_date"],
                    "additionalProperties": False,
                },
                handler,
            )
        ]


def _validate_or_repair_llm_response(
    *,
    llm_service,
    report_date: str,
    raw_response: str,
    trace: list[dict],
    deterministic_context: dict | None = None,
) -> tuple[dict | None, str, str | None]:
    """Validate, repair, or fallback LLM output."""
    from app.services.daily_position_review_agent import (
        DailyPositionReviewAgent,
        DailyPositionReviewAgentError,
        extract_json_object,
        MAX_LLM_REPAIR_ATTEMPTS,
    )
    import json

    schema = {
        "report_date": report_date,
        "summary": "一句话总结今日账户表现",
        "account_conclusion": "今日账户结论",
        "attribution_summary": "账户涨跌归因",
        "major_contributors_analysis": [{"symbol": "AMD.US", "analysis": "..."}],
        "major_drags_analysis": [{"symbol": "NVDA.US", "analysis": "..."}],
        "focus_symbol_analyses": [
            {
                "symbol": "AMD.US",
                "price_action": "...",
                "account_impact": "...",
                "possible_reasons": ["..."],
                "valuation_note": "...",
                "cost_position_note": "...",
                "watch_points": ["..."],
                "data_limitations": ["..."],
            }
        ],
        "market_context": "市场和行业背景",
        "risk_analysis": "仓位风险变化",
        "tomorrow_watchlist": [
            {
                "symbol": "AMD.US",
                "reason": "...",
                "key_levels": ["20日线", "前高"],
                "events": ["..."],
                "conditions": ["如果...则继续观察", "如果...则关注转弱"],
            }
        ],
        "operation_observation": "操作观察建议，不是强买强卖",
        "data_limitations": ["..."],
        "evidence_used": ["tool_name: brief reason"],
    }

    candidate_response = raw_response
    response_history = [f"--- original_response ---\n{raw_response}"]
    last_error = None

    # Create a temporary agent instance for validation
    temp_agent = DailyPositionReviewAgent.__new__(DailyPositionReviewAgent)
    temp_agent.llm_service = llm_service

    for attempt in range(MAX_LLM_REPAIR_ATTEMPTS + 1):
        try:
            parsed = extract_json_object(candidate_response)
            validated = temp_agent.validate_llm_output(parsed, expected_report_date=report_date, deterministic_context=deterministic_context)
            if attempt > 0:
                response_history.append(f"--- final_validated_after_attempt_{attempt} ---")
            return validated, "\n\n".join(response_history), None
        except DailyPositionReviewAgentError as exc:
            last_error = exc
            if attempt >= MAX_LLM_REPAIR_ATTEMPTS:
                break
            repair_response = llm_service.chat(
                [
                    {"role": "system", "content": "你是 JSON 修复器，只输出符合 schema 的严格 JSON，不要输出 Markdown。"},
                    {
                        "role": "user",
                        "content": (
                            "下面的模型输出不是有效每日持仓复盘 JSON。请修复为严格 JSON。\n\n"
                            f"请求日期: {report_date}\n\n"
                            f"这是第 {attempt + 1}/{MAX_LLM_REPAIR_ATTEMPTS} 次修复。上一次错误: "
                            f"{exc.error_code}: {exc.message}\n\n"
                            f"所有 schema 字段都必须存在:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
                            f"原始输出:\n{candidate_response}"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=None,
                response_format={"type": "json_object"},
            )
            response_history.append(f"--- repair_attempt_{attempt + 1}_for_{exc.error_code} ---\n{repair_response}")
            candidate_response = repair_response

    return None, "\n\n".join(response_history), str(last_error)


def _parse_validate_repair_daily_review(
    *,
    llm_service,
    report_date: str,
    raw_response: str,
    trace: list[dict],
    deterministic_context: dict | None = None,
    card_pack=None,
    compact_positions: list[dict] | None = None,
):
    from app.agents.daily_review_structured_outputs import build_daily_position_review_main_contract
    from app.agents.structured_output.runtime import StructuredOutputRuntime

    def fallback_builder(context: dict | None, last_error, _raw_response: str) -> dict:
        ctx = (context or {}).get("deterministic_context") or {}
        return _build_fallback_review_payload(
            report_date=report_date,
            context=ctx,
            parse_error=f"{last_error.error_code}: {last_error.message}",
        )

    contract = build_daily_position_review_main_contract(fallback_builder=fallback_builder)
    context = {
        "report_date": report_date,
        "deterministic_context": deterministic_context or {},
        "card_pack_summary": card_pack.to_dict() if hasattr(card_pack, "to_dict") else {},
        "compact_positions": compact_positions or [],
        "runtime_trace": _compact_structured_trace_context(trace),
    }
    return StructuredOutputRuntime(llm_service).parse_validate_repair(
        raw_response,
        contract,
        context=context,
    )


def _normalize_daily_review_payload(payload: dict, *, report_date: str, deterministic_context: dict | None) -> dict:
    from app.agents.invariants import normalize_daily_position_review_output
    from app.agents.output_schemas import DailyPositionReviewOutput

    model = DailyPositionReviewOutput.model_validate({**payload, "report_date": payload.get("report_date") or report_date})
    return normalize_daily_position_review_output(
        model.model_dump(),
        expected_report_date=report_date,
        deterministic_context=deterministic_context,
    )


def _format_structured_raw_response(raw_response: str, structured) -> str:
    parts = [f"--- original_response ---\n{raw_response}"]
    for index, error in enumerate(structured.errors or [], start=1):
        code = error.get("error_code")
        message = error.get("message")
        parts.append(f"--- structured_error_{index}_{code} ---\n{message}")
    if structured.final_response:
        parts.append(f"--- final_validated_after_structured_repair_{structured.repair_attempts} ---\n{structured.final_response}")
    if structured.fallback_used:
        parts.append(f"--- fallback_reason ---\n{structured.metadata.get('fallback_reason') or structured.error_message or structured.error_code}")
    return "\n\n".join(parts)


def _structured_output_result_event(metadata: dict) -> dict:
    return {
        "event": "structured_output_result",
        "contract_name": metadata.get("contract_name"),
        "ok": metadata.get("schema_validation_passed"),
        "repaired": metadata.get("repaired"),
        "repair_attempts": metadata.get("repair_attempts"),
        "fallback_used": metadata.get("fallback_used"),
        "error_code": metadata.get("error_code"),
        "schema_validation_passed": metadata.get("schema_validation_passed"),
    }


def _compact_structured_trace_context(trace: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for item in trace[-12:]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "event": item.get("event"),
                "tool": item.get("tool") or item.get("tool_name"),
                "ok": item.get("ok"),
                "summary": item.get("summary"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
                "total_tokens": item.get("total_tokens"),
            }
        )
    return compacted


def _build_fallback_review_payload(report_date: str, context: dict, parse_error: str) -> dict:
    """Build fallback review payload from deterministic context."""
    overview = context.get("overview") or {}
    rankings = context.get("rankings") or {}
    risk = context.get("risk") or {}
    data_quality = context.get("data_quality") or {}
    top_contributors = rankings.get("profit_contributors") or []
    top_drags = rankings.get("loss_drags") or []
    top_weights = rankings.get("top_weights") or []
    focus_symbols = [str(symbol) for symbol in context.get("focus_symbols") or []]

    contributor_symbols = "、".join(item.get("symbol", "") for item in top_contributors[:3] if item.get("symbol")) or "暂无"
    drag_symbols = "、".join(item.get("symbol", "") for item in top_drags[:3] if item.get("symbol")) or "暂无"
    risk_flags = [str(item) for item in risk.get("risk_flags") or []]
    risk_summary = "；".join(risk_flags) if risk_flags else "当前没有明显集中度警报。"

    watch_symbols = focus_symbols[:5] or [item.get("symbol") for item in top_weights[:5] if item.get("symbol")]

    return {
        "report_date": report_date,
        "summary": overview.get("summary") or "复盘已生成，但 LLM 输出格式异常，本次先展示后端确定性数据摘要。",
        "account_conclusion": overview.get("summary") or "后端已完成账户涨跌和持仓贡献计算；LLM 解释部分因输出格式异常采用兜底摘要。",
        "attribution_summary": (
            f"当日账户盈亏为 {overview.get('daily_pnl')}，收益率为 {overview.get('daily_return_percent')}%。"
            f"主要贡献来自 {contributor_symbols}，主要拖累来自 {drag_symbols}。"
        ),
        "major_contributors_analysis": [
            {"symbol": item.get("symbol"), "analysis": f"当日盈亏 {item.get('daily_pnl')}，贡献比例 {item.get('contribution_ratio')}，权重 {item.get('weight')}。"}
            for item in top_contributors[:5]
        ],
        "major_drags_analysis": [
            {"symbol": item.get("symbol"), "analysis": f"当日盈亏 {item.get('daily_pnl')}，贡献比例 {item.get('contribution_ratio')}，权重 {item.get('weight')}。"}
            for item in top_drags[:5]
        ],
        "focus_symbol_analyses": [
            {
                "symbol": symbol,
                "price_action": "LLM 输出格式异常，价格异动解释待重新生成。",
                "account_impact": "请参考下方确定性持仓贡献排行。",
                "possible_reasons": [],
                "valuation_note": "公开市场解释不足。",
                "cost_position_note": "请参考持仓明细中的成本和浮盈亏位置。",
                "watch_points": ["重新生成 LLM 复盘"],
                "data_limitations": [parse_error],
            }
            for symbol in watch_symbols[:5]
        ],
        "market_context": "LLM 输出不是有效 JSON，本次未可靠生成市场和行业解释。",
        "risk_analysis": risk_summary,
        "tomorrow_watchlist": [
            {
                "symbol": symbol,
                "reason": "重点持仓或当日异动标的，需要在下一交易日继续观察。",
                "key_levels": [],
                "events": [],
                "conditions": ["关注成交量变化、关键均线或前高/前低位置"],
            }
            for symbol in watch_symbols[:5]
        ],
        "operation_observation": "本次是格式异常后的兜底复盘，不给出强买强卖结论；建议在 LLM 输出恢复后重新生成完整解释。",
        "data_limitations": [
            parse_error,
            "本报告采用后端确定性数据兜底生成，个股原因、估值和新闻归因不完整。",
        ],
        "evidence_used": [
            "get_daily_position_review_context: IBKR account and position attribution",
            "fallback: LLM response was not valid JSON",
        ],
    }
