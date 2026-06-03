"""LangGraph nodes for the risk assessment graph.

Every node is created via a make_* factory that closes over deps.
Parallel nodes write only to their own card field + per-node public_data_mode.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents.graph.result_contract import build_agent_metadata, build_run_trace_from_state
from app.agents.graph.trace import finish_node_trace, now_iso, start_node_trace
from app.agents.risk_assessment_graph.cards import (
    AccountRiskSnapshot,
    ConcentrationRiskCard,
    CorrelationRiskCard,
    EarningsCalendarRiskCard,
    RiskAssessmentCardPack,
    RiskLevel,
    SectorThemeExposureCard,
    StressTestCard,
    build_fallback_concentration_card,
    build_fallback_correlation_card,
    build_fallback_earnings_calendar_card,
    build_fallback_sector_theme_card,
    build_fallback_stress_test_card,
    classify_symbol_theme,
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
from app.agents.graph.trace import summarize_node_traces


def _as_snapshot(raw) -> AccountRiskSnapshot:
    if isinstance(raw, AccountRiskSnapshot):
        return raw
    if isinstance(raw, dict):
        return AccountRiskSnapshot(**raw)
    raise TypeError(f"Expected AccountRiskSnapshot or dict, got {type(raw)}")


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


def make_build_account_risk_facts_node(deps):
    def build_account_risk_facts_node(state: dict) -> dict:
        trace = start_node_trace("build_account_risk_facts")
        import time as _time
        _t0 = _time.monotonic()
        try:
            snapshot = deps.account_facts_builder.build(question=state.get("user_question"))
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="risk_assessment", node_name="build_account_risk_facts",
                tool_name="ibkr_build_risk_facts", ok=True, latency_ms=latency_ms,
            )
            result: dict[str, Any] = {
                "account_risk_snapshot": snapshot,
                "assessment_type": "portfolio_risk",
            }
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            latency_ms = int((_time.monotonic() - _t0) * 1000)
            _record_ibkr_metric(
                deps.monitoring_service, run_id=state.get("agent_run_id"),
                agent_name="risk_assessment", node_name="build_account_risk_facts",
                tool_name="ibkr_build_risk_facts", ok=False, latency_ms=latency_ms,
                error_message=error_msg,
            )
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {
                "errors": [f"build_account_risk_facts: {error_msg}"],
                "node_traces": [trace],
            }
    return build_account_risk_facts_node


def make_position_concentration_node(deps):
    """Deterministic node - no MCP, no LLM."""
    def position_concentration_node(state: dict) -> dict:
        trace = start_node_trace("position_concentration")
        try:
            snapshot = _as_snapshot(state["account_risk_snapshot"])
            card = _assess_concentration(snapshot)
            result = {"concentration_card": card}
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_concentration_card(str(exc))
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"concentration_card": card, "node_traces": [trace]}
    return position_concentration_node


def _assess_concentration(snapshot: AccountRiskSnapshot) -> ConcentrationRiskCard:
    findings: list[str] = []
    risks: list[str] = []
    actions: list[str] = []
    score = 0.0

    largest = snapshot.largest_position_pct
    top3 = snapshot.top_3_position_pct
    pos_count = snapshot.position_count

    # Largest position scoring
    if largest > 0.40:
        score += 20
        findings.append(f"最大持仓占比 {largest:.1%}，极高集中度")
        risks.append("单一持仓过度集中，大幅下跌风险极高")
    elif largest > 0.25:
        score += 14
        findings.append(f"最大持仓占比 {largest:.1%}，高集中度")
        risks.append("单一持仓集中度过高")
    elif largest > 0.15:
        score += 7
        findings.append(f"最大持仓占比 {largest:.1%}，中等集中度")
    else:
        findings.append(f"最大持仓占比 {largest:.1%}，分散良好")

    # Top 3 concentration
    if top3 > 0.70:
        score += 5
        findings.append(f"前3大持仓合计 {top3:.1%}，集中度偏高")
        risks.append("前3大持仓占比过高，组合分散不足")

    # Position count
    if pos_count <= 2 and largest > 0.30:
        score += 5
        findings.append(f"仅 {pos_count} 只持仓，分散不足")
        risks.append("持仓数量过少")

    # Cash buffer
    if snapshot.cash_pct < 0.05:
        score += 3
        findings.append(f"现金占比仅 {snapshot.cash_pct:.1%}，流动性缓冲不足")

    score = min(score, 25)
    risk_level = _risk_level_from_score(score, 25)

    if risk_level in (RiskLevel.HIGH, RiskLevel.EXTREME):
        actions.append("考虑减仓最大持仓至20%以下")
        actions.append("增加持仓分散度")
    elif risk_level == RiskLevel.MEDIUM:
        actions.append("关注最大持仓占比变化")

    return ConcentrationRiskCard(
        summary=f"仓位集中度评估：{risk_level}。最大持仓 {largest:.1%}，前3大 {top3:.1%}，共 {pos_count} 只持仓。",
        score=round(score, 2),
        max_score=25,
        risk_level=risk_level,
        largest_position_pct=largest,
        top_3_position_pct=top3,
        top_5_position_pct=snapshot.top_5_position_pct,
        concentration_findings=findings,
        key_risks=risks,
        suggested_actions=actions,
        evidence_quality="high",
        created_at=now_iso(),
    )


def make_sector_theme_exposure_node(deps):
    """Uses MCP for company info if available, falls back to rule-based classification."""
    def sector_theme_exposure_node(state: dict) -> dict:
        trace = start_node_trace("sector_theme_exposure")
        tools_called: list[str] = []
        data_limitations: list[str] = []
        try:
            snapshot = _as_snapshot(state["account_risk_snapshot"])
            adapter = deps.mcp_adapter

            # Classify each position using rules first
            theme_map: dict[str, dict[str, float]] = {
                "semiconductor": {}, "ai": {}, "china": {}, "mega_cap_tech": {},
            }
            total_value = snapshot.total_position_value or 1.0
            unknown_value = 0.0

            for pos in snapshot.positions:
                if not pos.market_value:
                    continue
                themes = classify_symbol_theme(pos.symbol)
                is_known = False
                for theme, is_member in themes.items():
                    if is_member and theme in theme_map:
                        theme_map[theme][pos.normalized_symbol] = pos.position_pct
                        is_known = True
                if not is_known and not themes.get("cash_equivalent"):
                    unknown_value += pos.market_value

            # Try MCP for top positions not classified
            mcp_available = False
            if adapter and hasattr(adapter, "client") and getattr(adapter.client, "enabled", False):
                unclassified = [p for p in snapshot.positions[:10]
                                if not any(classify_symbol_theme(p.symbol).values())]
                for pos in unclassified[:5]:
                    result = adapter.call("company", {"symbol": pos.normalized_symbol})
                    if result.get("ok"):
                        mcp_available = True
                        tools_called.append("company")
                        industry = (result.get("data") or {}).get("industry", "")
                        if industry:
                            data_limitations.append(f"MCP company info for {pos.symbol}: {industry}")
                    else:
                        data_limitations.append(f"MCP company lookup failed for {pos.symbol}")

            if not mcp_available:
                data_limitations.append("MCP不可用，使用规则分类")

            # Compute exposure percentages
            ai_pct = sum(theme_map["ai"].values())
            semi_pct = sum(theme_map["semiconductor"].values())
            china_pct = sum(theme_map["china"].values())
            mega_pct = sum(theme_map["mega_cap_tech"].values())
            unknown_pct = round(unknown_value / total_value, 6)

            # Score: higher concentration in any theme = higher risk
            score = 0.0
            risks: list[str] = []
            if ai_pct > 0.40:
                score += 8
                risks.append(f"AI主题暴露 {ai_pct:.1%} 过高")
            elif ai_pct > 0.25:
                score += 4
            if semi_pct > 0.35:
                score += 6
                risks.append(f"半导体暴露 {semi_pct:.1%} 过高")
            elif semi_pct > 0.20:
                score += 3
            if china_pct > 0.30:
                score += 5
                risks.append(f"中国资产暴露 {china_pct:.1%} 过高")
            elif china_pct > 0.15:
                score += 2
            if mega_pct > 0.60:
                score += 4
                risks.append(f"大盘科技集中 {mega_pct:.1%}")
            if unknown_pct > 0.50:
                score += 3
                data_limitations.append(f"未分类持仓占比 {unknown_pct:.1%}")

            score = min(score, 20)
            risk_level = _risk_level_from_score(score, 20)

            public_data_mode = "mcp" if mcp_available else "unavailable"

            card = SectorThemeExposureCard(
                summary=f"行业主题暴露评估：{risk_level}。AI {ai_pct:.1%}，半导体 {semi_pct:.1%}，中概 {china_pct:.1%}，大盘科技 {mega_pct:.1%}。",
                score=round(score, 2),
                max_score=20,
                risk_level=risk_level,
                sector_exposures={},
                theme_exposures=theme_map,
                ai_exposure_pct=round(ai_pct, 6),
                semiconductor_exposure_pct=round(semi_pct, 6),
                china_exposure_pct=round(china_pct, 6),
                mega_cap_tech_exposure_pct=round(mega_pct, 6),
                unknown_exposure_pct=round(unknown_pct, 6),
                key_risks=risks,
                suggested_actions=["关注主题集中度变化"] if risks else [],
                source_tools=tools_called,
                data_limitations=data_limitations,
                evidence_quality="medium" if mcp_available else "low",
                created_at=now_iso(),
            )

            result = {"sector_theme_card": card, "sector_public_data_mode": public_data_mode}
            trace = finish_node_trace(trace, "success", tools_called=tools_called)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_sector_theme_card(str(exc))
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"sector_theme_card": card, "sector_public_data_mode": "unavailable", "node_traces": [trace]}
    return sector_theme_exposure_node


def make_correlation_node(deps):
    """Estimate correlation risk using theme overlap. MCP candlesticks optional."""
    def correlation_node(state: dict) -> dict:
        trace = start_node_trace("correlation")
        tools_called: list[str] = []
        data_limitations: list[str] = []
        try:
            snapshot = _as_snapshot(state["account_risk_snapshot"])

            # Group positions by theme
            theme_groups: dict[str, list[str]] = {}
            for pos in snapshot.positions:
                if not pos.market_value:
                    continue
                themes = classify_symbol_theme(pos.symbol)
                for theme, is_member in themes.items():
                    if is_member and theme != "cash_equivalent":
                        theme_groups.setdefault(theme, []).append(pos.normalized_symbol)

            high_corr_groups: list[dict] = []
            for theme, symbols in theme_groups.items():
                if len(symbols) >= 2:
                    total_pct = sum(
                        p.position_pct for p in snapshot.positions
                        if p.normalized_symbol in symbols
                    )
                    high_corr_groups.append({
                        "theme": theme,
                        "symbols": symbols,
                        "combined_pct": round(total_pct, 6),
                        "count": len(symbols),
                    })

            high_corr_groups.sort(key=lambda g: g["combined_pct"], reverse=True)

            # Score based on concentration in correlated groups
            score = 0.0
            risks: list[str] = []
            for group in high_corr_groups:
                if group["combined_pct"] > 0.30:
                    score += 6
                    risks.append(f"{group['theme']}主题 {group['count']}只股票合计 {group['combined_pct']:.1%}，相关性高")
                elif group["combined_pct"] > 0.15:
                    score += 3

            score = min(score, 20)
            risk_level = _risk_level_from_score(score, 20)

            est_corr = 0.3  # baseline
            if high_corr_groups:
                max_group_pct = high_corr_groups[0]["combined_pct"]
                est_corr = min(0.9, 0.3 + max_group_pct * 0.8)

            card = CorrelationRiskCard(
                summary=f"相关性风险评估：{risk_level}。{len(high_corr_groups)}个主题组存在高相关性。",
                score=round(score, 2),
                max_score=20,
                risk_level=risk_level,
                high_correlation_groups=high_corr_groups,
                estimated_portfolio_correlation=round(est_corr, 3),
                correlation_notes="基于主题重合度估算，未使用收益率相关性计算" if not tools_called else "",
                key_risks=risks,
                suggested_actions=["分散主题集中度"] if risks else [],
                source_tools=tools_called,
                data_limitations=data_limitations if data_limitations else ["使用主题近似法，未计算真实收益率相关性"],
                evidence_quality="medium" if tools_called else "low",
                created_at=now_iso(),
            )

            result = {"correlation_card": card, "correlation_public_data_mode": "unavailable"}
            trace = finish_node_trace(trace, "success", tools_called=tools_called)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_correlation_card(str(exc))
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"correlation_card": card, "correlation_public_data_mode": "unavailable", "node_traces": [trace]}
    return correlation_node


def make_earnings_calendar_risk_node(deps):
    """Uses MCP finance_calendar for upcoming earnings."""
    def earnings_calendar_risk_node(state: dict) -> dict:
        trace = start_node_trace("earnings_calendar_risk")
        tools_called: list[str] = []
        data_limitations: list[str] = []
        try:
            snapshot = _as_snapshot(state["account_risk_snapshot"])
            adapter = deps.mcp_adapter

            upcoming: list[dict] = []
            high_risk_symbols: list[str] = []
            near_term_exposure = 0.0
            mcp_available = False

            # Only check top 10 positions
            top_positions = [p for p in snapshot.positions[:10] if p.market_value > 0]

            if adapter and hasattr(adapter, "client") and getattr(adapter.client, "enabled", False):
                now_date = datetime.now(timezone.utc).date()
                for pos in top_positions:
                    result = adapter.call("finance_calendar", {"symbol": pos.normalized_symbol})
                    if result.get("ok"):
                        mcp_available = True
                        tools_called.append("finance_calendar")
                        data = result.get("data") or {}
                        earnings = data.get("earnings") or []
                        for event in earnings:
                            event_date_str = event.get("date") or event.get("report_date")
                            if not event_date_str:
                                continue
                            try:
                                event_date = datetime.fromisoformat(str(event_date_str)[:10]).date()
                            except (ValueError, TypeError):
                                continue
                            days_until = (event_date - now_date).days
                            if 0 <= days_until <= 30:
                                upcoming.append({
                                    "symbol": pos.normalized_symbol,
                                    "date": str(event_date),
                                    "days_until": days_until,
                                    "position_pct": pos.position_pct,
                                })
                                if days_until <= 7 and pos.position_pct > 0.10:
                                    high_risk_symbols.append(pos.normalized_symbol)
                                    near_term_exposure += pos.position_pct
                    else:
                        data_limitations.append(f"MCP calendar failed for {pos.symbol}")

            if not mcp_available:
                data_limitations.append("MCP不可用，无法获取财报日历")

            # Score
            score = 0.0
            risks: list[str] = []
            if high_risk_symbols:
                score += min(10, len(high_risk_symbols) * 3)
                risks.append(f"未来7天内 {len(high_risk_symbols)} 只重仓股有财报")
            if near_term_exposure > 0.30:
                score += 5
                risks.append(f"近7天财报暴露 {near_term_exposure:.1%}")
            if len(upcoming) > 3:
                score += 3
                risks.append(f"未来30天共 {len(upcoming)} 个财报事件")

            score = min(score, 15)
            risk_level = _risk_level_from_score(score, 15)

            card = EarningsCalendarRiskCard(
                summary=f"财报日历风险评估：{risk_level}。未来30天 {len(upcoming)} 个财报事件，{len(high_risk_symbols)} 只重仓股近7天有财报。",
                score=round(score, 2),
                max_score=15,
                risk_level=risk_level,
                upcoming_earnings=upcoming,
                near_term_event_exposure_pct=round(near_term_exposure, 6),
                high_event_risk_symbols=high_risk_symbols,
                key_risks=risks,
                suggested_actions=["关注重仓股财报日期"] if risks else [],
                source_tools=tools_called,
                data_limitations=data_limitations,
                evidence_quality="medium" if mcp_available else "low",
                created_at=now_iso(),
            )

            public_data_mode = "mcp" if mcp_available else "unavailable"
            result = {"earnings_calendar_card": card, "earnings_public_data_mode": public_data_mode}
            trace = finish_node_trace(trace, "success", tools_called=tools_called)
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_earnings_calendar_card(str(exc))
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"earnings_calendar_card": card, "earnings_public_data_mode": "unavailable", "node_traces": [trace]}
    return earnings_calendar_risk_node


def make_stress_test_node(deps):
    """Deterministic stress test - no MCP, no LLM."""
    def stress_test_node(state: dict) -> dict:
        trace = start_node_trace("stress_test")
        try:
            snapshot = _as_snapshot(state["account_risk_snapshot"])
            sector_card = state.get("sector_theme_card")

            card = _run_stress_test(snapshot, sector_card)
            result = {"stress_test_card": card}
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            card = build_fallback_stress_test_card(str(exc))
            trace = finish_node_trace(trace, "fallback", fallback_used=True, fallback_reason=str(exc)[:200])
            return {"stress_test_card": card, "node_traces": [trace]}
    return stress_test_node


def _run_stress_test(snapshot: AccountRiskSnapshot, sector_card: SectorThemeExposureCard | None) -> StressTestCard:
    nlv = snapshot.net_liquidation or 0.0
    positions = snapshot.positions

    # Identify themed positions
    semi_symbols = set()
    ai_symbols = set()
    china_symbols = set()
    if sector_card:
        for sym in (sector_card.theme_exposures.get("semiconductor") or {}):
            semi_symbols.add(sym)
        for sym in (sector_card.theme_exposures.get("ai") or {}):
            ai_symbols.add(sym)
        for sym in (sector_card.theme_exposures.get("china") or {}):
            china_symbols.add(sym)
    else:
        for pos in positions:
            themes = classify_symbol_theme(pos.symbol)
            if themes.get("semiconductor"):
                semi_symbols.add(pos.normalized_symbol)
            if themes.get("ai"):
                ai_symbols.add(pos.normalized_symbol)
            if themes.get("china"):
                china_symbols.add(pos.normalized_symbol)

    largest_sym = positions[0].normalized_symbol if positions else ""

    def _apply_shock(symbols: set[str], shock_pct: float, default_shock: float) -> float:
        loss = 0.0
        for pos in positions:
            if pos.normalized_symbol in symbols:
                loss += pos.market_value * shock_pct
            else:
                loss += pos.market_value * default_shock
        return loss

    scenarios_raw = [
        ("market_minus_10", 0.10, 0.10, "全市场下跌10%"),
        ("market_minus_20", 0.20, 0.20, "全市场下跌20%"),
        ("semiconductor_minus_30", 0.30, 0.10, "半导体-30%，其他-10%"),
        ("largest_position_minus_30", None, None, "最大持仓-30%"),
        ("china_adr_minus_25", 0.25, 0.05, "中概-25%，其他-5%"),
        ("ai_theme_minus_30", 0.30, 0.10, "AI主题-30%，其他-10%"),
    ]

    scenarios: list[dict] = []
    worst_loss = 0.0
    worst_drawdown = 0.0

    for name, theme_shock, default_shock, desc in scenarios_raw:
        if name == "largest_position_minus_30":
            loss = sum(p.market_value * 0.30 for p in positions if p.normalized_symbol == largest_sym)
        elif name == "semiconductor_minus_30":
            loss = _apply_shock(semi_symbols, theme_shock, default_shock)
        elif name == "china_adr_minus_25":
            loss = _apply_shock(china_symbols, theme_shock, default_shock)
        elif name == "ai_theme_minus_30":
            loss = _apply_shock(ai_symbols, theme_shock, default_shock)
        else:
            loss = _apply_shock(set(), 0, theme_shock)

        drawdown = round(loss / nlv, 6) if nlv else 0.0
        scenarios.append({
            "scenario_name": name,
            "description": desc,
            "estimated_loss_amount": round(loss, 2),
            "estimated_drawdown_pct": drawdown,
            "affected_symbols": list(semi_symbols if "semiconductor" in name else china_symbols if "china" in name else ai_symbols if "ai" in name else [])[:10],
        })

        if loss > worst_loss:
            worst_loss = loss
            worst_drawdown = drawdown

    liquidity_after = (snapshot.deployable_liquidity or 0.0) - worst_loss
    margin_warning = "none"
    if liquidity_after < 0:
        margin_warning = "critical"
    elif liquidity_after < (snapshot.deployable_liquidity or 0.0) * 0.3:
        margin_warning = "warning"

    # Score: worst_case_drawdown mapped to 0-20
    score = min(20, round(worst_drawdown * 100, 2))
    risk_level = _risk_level_from_score(score, 20)

    risks: list[str] = []
    if worst_drawdown > 0.30:
        risks.append(f"极端场景回撤 {worst_drawdown:.1%}，风险极高")
    elif worst_drawdown > 0.20:
        risks.append(f"极端场景回撤 {worst_drawdown:.1%}，风险较高")

    return StressTestCard(
        summary=f"压力测试评估：{risk_level}。最差场景回撤 {worst_drawdown:.1%}，损失 ${worst_loss:,.0f}。",
        score=round(score, 2),
        max_score=20,
        risk_level=risk_level,
        scenarios=scenarios,
        worst_case_drawdown_pct=round(worst_drawdown, 6),
        worst_case_loss_amount=round(worst_loss, 2),
        liquidity_after_stress=round(liquidity_after, 2),
        margin_risk_after_stress=margin_warning,
        key_risks=risks,
        suggested_actions=["关注极端场景下的流动性"] if risks else [],
        evidence_quality="high",
        created_at=now_iso(),
    )


def make_risk_report_composer_node(deps):
    """Deterministic composer - no LLM, no MCP. Fan-in node."""
    def risk_report_composer_node(state: dict) -> dict:
        trace = start_node_trace("risk_report_composer")
        try:
            concentration = state.get("concentration_card")
            sector = state.get("sector_theme_card")
            correlation = state.get("correlation_card")
            earnings = state.get("earnings_calendar_card")
            stress = state.get("stress_test_card")

            card_pack = RiskAssessmentCardPack(
                account_risk_snapshot=_as_snapshot(state["account_risk_snapshot"]),
                concentration_card=concentration,
                sector_theme_card=sector,
                correlation_card=correlation,
                earnings_calendar_card=earnings,
                stress_test_card=stress,
            )

            # Weighted risk score
            c_score = _normalized_score(concentration, 25)
            s_score = _normalized_score(sector, 20)
            cr_score = _normalized_score(correlation, 20)
            e_score = _normalized_score(earnings, 15)
            st_score = _normalized_score(stress, 20)

            overall = round(
                c_score * 0.30 + s_score * 0.20 + cr_score * 0.20 + e_score * 0.10 + st_score * 0.20,
                2,
            )
            risk_level = _overall_risk_level(overall)

            # Data quality check
            fallback_count = sum(1 for card in [concentration, sector, correlation, earnings, stress]
                                 if card and getattr(card, "evidence_quality", "") == "low")
            confidence = "high" if fallback_count == 0 else "medium" if fallback_count <= 1 else "low"

            # Data insufficient → bias toward higher risk, not lower
            if fallback_count >= 2 and risk_level == RiskLevel.LOW:
                risk_level = RiskLevel.MEDIUM
                overall = max(overall, 26)

            key_risks: list[str] = []
            suggested_actions: list[str] = []
            concentration_warnings: list[str] = []
            event_warnings: list[str] = []
            data_limitations: list[str] = []
            evidence_used: list[str] = []

            for card in [concentration, sector, correlation, earnings, stress]:
                if card:
                    key_risks.extend(getattr(card, "key_risks", []))
                    suggested_actions.extend(getattr(card, "suggested_actions", []))
                    data_limitations.extend(getattr(card, "data_limitations", []))

            if concentration:
                concentration_warnings = list(concentration.concentration_findings)
                evidence_used.append("concentration_risk")
            if sector:
                evidence_used.append("sector_theme_exposure")
            if correlation:
                evidence_used.append("correlation_risk")
            if earnings:
                event_warnings = list(earnings.key_risks)
                evidence_used.append("earnings_calendar_risk")
            if stress:
                evidence_used.append("stress_test")

            score_detail = {
                "concentration": {"score": c_score * 100, "weight": 0.30, "contribution": round(c_score * 100 * 0.30, 2)},
                "sector_theme": {"score": s_score * 100, "weight": 0.20, "contribution": round(s_score * 100 * 0.20, 2)},
                "correlation": {"score": cr_score * 100, "weight": 0.20, "contribution": round(cr_score * 100 * 0.20, 2)},
                "earnings_calendar": {"score": e_score * 100, "weight": 0.10, "contribution": round(e_score * 100 * 0.10, 2)},
                "stress_test": {"score": st_score * 100, "weight": 0.20, "contribution": round(st_score * 100 * 0.20, 2)},
            }

            stress_summary = {}
            if stress:
                stress_summary = {
                    "worst_case_drawdown_pct": stress.worst_case_drawdown_pct,
                    "worst_case_loss_amount": stress.worst_case_loss_amount,
                    "margin_risk_after_stress": stress.margin_risk_after_stress,
                    "scenario_count": len(stress.scenarios),
                }

            risk_report = {
                "overall_risk_score": overall,
                "risk_level": risk_level,
                "risk_summary": f"账户整体风险等级：{risk_level}。综合风险评分 {overall}/100。",
                "score_detail": score_detail,
                "key_risks": list(dict.fromkeys(key_risks)),
                "suggested_actions": list(dict.fromkeys(suggested_actions)),
                "concentration_warnings": concentration_warnings,
                "event_warnings": event_warnings,
                "stress_test_summary": stress_summary,
                "data_limitations": list(dict.fromkeys(data_limitations)),
                "evidence_used": evidence_used,
                "confidence": confidence,
            }

            card_pack.node_traces = state.get("node_traces") or []

            result: dict[str, Any] = {"risk_report": risk_report, "card_pack": card_pack}
            trace = finish_node_trace(trace, "success")
            return {**result, "node_traces": [trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {"errors": [f"risk_report_composer: {error_msg}"], "node_traces": [trace]}
    return risk_report_composer_node


def make_persist_risk_assessment_node(deps):
    def persist_risk_assessment_node(state: dict) -> dict:
        trace = start_node_trace("persist_risk_assessment")
        try:
            risk_report = state["risk_report"]
            card_pack = state.get("card_pack")

            finished_trace = finish_node_trace(trace, "success")
            run_trace = build_run_trace_from_state(state, finished_trace)

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
                fallback_used=state.get("fallback_used", False),
                fallback_reason=state.get("fallback_reason"),
            )

            now = now_iso()
            document: dict = {
                **risk_report,
                "assessment_type": state.get("assessment_type", "portfolio_risk"),
                "card_pack": card_pack.to_dict() if hasattr(card_pack, "to_dict") else card_pack,
                "run_trace": run_trace,
                "run_trace_summary": summarize_node_traces(run_trace),
                "metadata": metadata,
                "fallback_used": state.get("fallback_used", False),
                "fallback_reason": state.get("fallback_reason"),
                "created_at": now,
                "updated_at": now,
            }

            saved = deps.repository.save_assessment(document)
            result: dict[str, Any] = {"saved_document": saved}
            return {**result, "node_traces": [finished_trace]}
        except Exception as exc:
            error_msg = str(exc)[:200]
            trace = start_node_trace("persist_risk_assessment")
            trace = finish_node_trace(trace, "failed", error=error_msg)
            return {"errors": [f"persist_risk_assessment: {error_msg}"], "node_traces": [trace]}
    return persist_risk_assessment_node


# === Helpers ===

def _risk_level_from_score(score: float, max_score: float) -> str:
    pct = score / max_score if max_score else 0
    if pct >= 0.76:
        return RiskLevel.EXTREME
    if pct >= 0.51:
        return RiskLevel.HIGH
    if pct >= 0.26:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _normalized_score(card, max_score: float) -> float:
    if card is None:
        return 0.5  # unknown = medium risk
    score = getattr(card, "score", 0)
    return min(1.0, score / max_score) if max_score else 0.0


def _overall_risk_level(score: float) -> str:
    if score >= 76:
        return RiskLevel.EXTREME
    if score >= 51:
        return RiskLevel.HIGH
    if score >= 26:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _build_run_trace(state: dict) -> list[dict]:
    run_trace: list[dict] = []
    for nt in state.get("node_traces") or []:
        run_trace.append({
            "event": f"node_{nt.get('status', 'unknown')}",
            "node_name": nt.get("node_name"),
            "elapsed_ms": nt.get("elapsed_ms", 0),
            "tools_called": nt.get("tools_called", []),
            "rounds_used": nt.get("rounds_used", 0),
            "fallback_used": nt.get("fallback_used", False),
        })
    return run_trace
