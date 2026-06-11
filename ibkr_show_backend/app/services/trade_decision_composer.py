"""
TradeDecisionComposer - composes final TradeDecisionOutput from TradeDecisionCardPack.

Does NOT call MCP. Reads only from the card pack produced by sub-agents.
Replaces the old LLM-based fixed evidence flow as the primary composer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
)


# Score weights matching the old DECISION_SCORE_DIMENSIONS
SCORE_WEIGHTS = {
    "fundamental_quality_score": 20,
    "valuation_score": 15,
    "trend_score": 15,
    "account_fit_score": 20,
    "risk_reward_score": 15,
    "review_constraint_score": 10,
    "event_catalyst_score": 5,
}

ALLOWED_ACTIONS = {
    # Legacy / composer-originated
    "add", "add_small", "add_batch", "hold", "reduce", "reduce_batch",
    "sell", "wait", "avoid", "watchlist",
    # New explicit gate actions - first-class citizens of the vocabulary
    "hold_no_add", "add_on_pullback", "add_right_side", "trim_on_rebound",
    "reduce_now", "sell_thesis_broken", "panic_blocked",
}

RISK_REWARD_INITIAL_ACTIONS = {
    "reduce_now", "hold_no_add", "wait", "add_on_pullback", "add_right_side",
}

ACTION_ALIASES = {
    "buy": "add_batch", "buy_now": "add", "strong_buy": "add",
    "accumulate": "add_batch", "increase": "add",
    "add_on_dips": "add_small", "add_on_pullback_legacy": "add_small",
    "buy_on_dips": "add_small", "buy_on_pullback": "add_small",
    "hold_or_add": "add_small", "hold_or_add_small": "add_small",
    "hold_and_add": "add_small", "hold_add_small": "add_small",
    "wait_for_pullback": "wait", "wait_pullback": "wait",
    "do_nothing": "hold", "trim": "reduce", "partial_sell": "reduce_batch",
    "full_sell": "sell", "clear": "sell", "exit": "sell",
    "watch": "watchlist", "observe": "watchlist", "hold_wait": "wait",
    "hold_no_add_legacy": "hold_no_add", "pullback_add": "add_on_pullback",
    "right_side_add": "add_right_side", "rebound_trim": "trim_on_rebound",
    "reduce_immediately": "reduce_now", "thesis_broken_sell": "sell_thesis_broken",
    "加仓": "add", "小幅加仓": "add_small", "少量加仓": "add_small",
    "逢低加仓": "add_small", "回调加仓": "add_small",
    "持有并逢低加仓": "add_small", "持有并小幅加仓": "add_small",
    "分批加仓": "add_batch", "建仓": "add_batch", "买入": "add_batch",
    "首笔建仓": "add_batch", "持有": "hold", "继续持有": "hold",
    "减仓": "reduce", "小幅减仓": "reduce", "分批减仓": "reduce_batch",
    "清仓": "sell", "卖出": "sell", "等待": "wait", "观望": "wait",
    "暂时等待": "wait", "等待回调": "wait", "等待更好买点": "wait",
    "不操作": "hold", "回避": "avoid", "避免": "avoid",
    "不建议": "avoid", "观察": "watchlist", "加入观察": "watchlist",
    "观察列表": "watchlist",
    "持有不加仓": "hold_no_add", "不加仓": "hold_no_add",
    "逢回调加仓": "add_on_pullback", "右侧加仓": "add_right_side",
    "反弹减仓": "trim_on_rebound", "立即减仓": "reduce_now",
    "假设破坏": "sell_thesis_broken", "恐慌拦截": "panic_blocked",
}


def rating_for_score(score: float) -> str:
    if score >= 85:
        return "strong_buy_or_hold"
    if score >= 70:
        return "positive"
    if score >= 50:
        return "neutral"
    return "negative"


def normalize_action(raw: str) -> str:
    normalized = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_ACTIONS:
        return normalized
    if normalized in ACTION_ALIASES:
        return ACTION_ALIASES[normalized]
    # Try contains matching
    for alias, action in ACTION_ALIASES.items():
        if alias in normalized or alias in raw:
            return action
    return normalized if normalized in ALLOWED_ACTIONS else "watchlist"


def _reason_text(prefix: str, text: str | None, limit: int = 500) -> str:
    clean = str(text or "").strip()
    if not clean:
        return f"{prefix}: 暂无说明"
    return f"{prefix}: {clean[:limit]}"


def _clean_user_data_limitation(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if (
        text.startswith("mcp_field_missing")
        or "agent exceeded max_rounds" in lowered
        or "subagent_failed" in lowered
        or "traceback" in lowered
        or "runtimeerror" in lowered
        or "jsondecodeerror" in lowered
        or "llm_json" in lowered
        or "runtime constraint" in lowered
        or "laufzeitbeschränkung" in lowered
        or ("tool" in lowered and ("truncated" in lowered or "abgeschnitten" in lowered))
    ):
        return "公开市场数据不足，已基于可用信息做保守分析"
    if "1970-01-01" in text:
        return "部分新闻缺少发布时间，时效性判断置信度降低"
    return text[:200]


@dataclass
class ComposerScoreDetail:
    score: float
    max_score: float
    reason: str


@dataclass
class ComposerPositionAdvice:
    current_position_pct: float | None
    suggested_target_position_pct: float | None
    max_position_pct: float | None
    suggested_cash_amount: float | None
    position_size_label: str


@dataclass
class ComposerExecutionPlan:
    should_act_now: bool
    plan: list[dict]
    invalid_conditions: list[str]
    recheck_triggers: list[str]


@dataclass
class ComposerResult:
    symbol: str
    decision_type: str
    overall_score: float
    rating: str
    action: str
    confidence: str
    decision_summary: str
    score_detail: dict[str, ComposerScoreDetail]
    position_advice: ComposerPositionAdvice
    execution_plan: ComposerExecutionPlan
    key_reasons: list[str]
    major_risks: list[str]
    review_warnings: list[str]
    data_limitations: list[str]
    evidence_used: list[str]
    data_source_summary: dict[str, str]


class TradeDecisionComposer:
    """
    Composes a structured TradeDecisionOutput from a TradeDecisionCardPack.
    Does NOT call MCP, does NOT call LLM.
    """

    def compose(self, card_pack: TradeDecisionCardPack) -> dict[str, Any]:
        # Stage 03: Resolve investment thesis (code-only) for the symbol.
        # The thesis is attached to the card_pack so the RiskGate can read it
        # even if compose() is called from a different code path.
        self._attach_investment_thesis(card_pack)
        result = self._compose(card_pack)
        output = {
            "id": f"tdc-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "symbol": result.symbol,
            "decision_type": result.decision_type,
            "overall_score": result.overall_score,
            "rating": result.rating,
            "action": result.action,
            "confidence": result.confidence,
            "decision_summary": result.decision_summary,
            "score_detail": {k: {"score": v.score, "max_score": v.max_score, "reason": v.reason} for k, v in result.score_detail.items()},
            "position_advice": {
                "current_position_pct": result.position_advice.current_position_pct,
                "suggested_target_position_pct": result.position_advice.suggested_target_position_pct,
                "max_position_pct": result.position_advice.max_position_pct,
                "suggested_cash_amount": result.position_advice.suggested_cash_amount if result.position_advice.suggested_cash_amount else 0,
                "position_size_label": result.position_advice.position_size_label,
            },
            "execution_plan": {
                "should_act_now": result.execution_plan.should_act_now,
                "plan": result.execution_plan.plan,
                "invalid_conditions": result.execution_plan.invalid_conditions,
                "recheck_triggers": result.execution_plan.recheck_triggers,
            },
            "key_reasons": result.key_reasons,
            "major_risks": result.major_risks,
            "review_warnings": result.review_warnings,
            "data_limitations": result.data_limitations,
            "evidence_used": result.evidence_used,
            "data_source_summary": result.data_source_summary,
        }

        # P3 - apply investment thesis override on position_advice BEFORE the
        # Risk Gate. This guarantees risk_gate.action_constraints and the
        # final position_advice use the same max_position_pct baseline.
        self._apply_thesis_to_position(output, card_pack)

        # Stage 04: Let the LLM trade plan provide the draft account action
        # before the deterministic Risk Gate validates or downgrades it.
        self._apply_trade_plan_to_output(output, card_pack)

        # Stage 03: Attach investment thesis to the output.
        thesis = card_pack.investment_thesis or {}
        output["investment_thesis"] = thesis
        output["thesis_risks"] = list(thesis.get("sell_triggers") or []) if isinstance(thesis, dict) else []

        # Apply deterministic risk gate with explicit fail-safe.
        # The gate may downgrade the action (e.g. add_batch -> add_on_pullback
        # / hold_no_add / panic_blocked) and attach a `risk_gate` block plus
        # surface reasons in data_limitations and review_warnings. It also
        # downgrades confidence via risk_gate.confidence_cap (P2).
        from app.services.trade_decision_risk_gate import apply_risk_gate, make_fail_safe_result

        user_question = getattr(card_pack.account_fact_snapshot, "user_question", None)
        action_before_risk_gate = output.get("action")
        try:
            output, gate_result = apply_risk_gate(output, card_pack, user_question=user_question)
        except Exception as gate_exc:
            # P1 - RiskGate is a safety layer; never let an exception here
            # silently disable the gate. We attach a fail-safe result and
            # downgrade the action + confidence to conservative defaults.
            fail_result = make_fail_safe_result(
                original_action=output.get("action") or "watchlist",
                snapshot=card_pack.account_fact_snapshot,
                error=str(gate_exc),
            )
            output["risk_gate"] = fail_result.to_dict()
            # Apply the conservative action + low confidence
            output["action"] = fail_result.final_action
            original_conf = output.get("confidence")
            output["confidence"] = "low" if original_conf != "low" else original_conf
            # Surface the failure in data_limitations and review_warnings
            dl = list(output.get("data_limitations") or [])
            for reason in fail_result.gate_reasons:
                if reason and reason not in dl:
                    dl.append(reason)
            output["data_limitations"] = dl
            rw = list(output.get("review_warnings") or [])
            for flag in fail_result.risk_flags:
                label = f"risk_gate:{flag}"
                if label not in rw:
                    rw.append(label)
            output["review_warnings"] = rw
            # Re-derive position_advice / execution_plan / decision_summary
            # for the fail-safe action so the output is internally consistent.
            try:
                new_pos = self._compute_position_advice(
                    card_pack.account_fact_snapshot,
                    card_pack.account_fit_card,
                    card_pack.risk_reward_card,
                    output["action"],
                )
                new_plan = self._compute_execution_plan(
                    output["action"],
                    new_pos,
                    card_pack.account_fact_snapshot,
                    card_pack,
                )
                output["position_advice"] = {
                    "current_position_pct": new_pos.current_position_pct,
                    "suggested_target_position_pct": new_pos.suggested_target_position_pct,
                    "max_position_pct": new_pos.max_position_pct,
                    "suggested_cash_amount": new_pos.suggested_cash_amount if new_pos.suggested_cash_amount else 0,
                    "position_size_label": new_pos.position_size_label,
                }
                output["execution_plan"] = {
                    "should_act_now": new_plan.should_act_now,
                    "plan": new_plan.plan,
                    "invalid_conditions": new_plan.invalid_conditions,
                    "recheck_triggers": new_plan.recheck_triggers,
                }
                output["decision_summary"] = self._build_decision_summary(
                    output["action"],
                    result.overall_score,
                    result.rating,
                    result.key_reasons,
                )
                # Re-apply thesis override on the new position_advice
                self._apply_thesis_to_position(output, card_pack)
            except Exception:
                # Even the fail-safe derivation should not crash; leave
                # the original position_advice / execution_plan unchanged.
                pass
            gate_result = fail_result

        # If the gate changed the action, re-derive position_advice and
        # execution_plan for the new action and re-apply the thesis override
        # so action_constraints and final position_advice stay consistent.
        if gate_result is not None and output.get("action") != action_before_risk_gate:
            try:
                new_pos = self._compute_position_advice(
                    card_pack.account_fact_snapshot,
                    card_pack.account_fit_card,
                    card_pack.risk_reward_card,
                    output["action"],
                )
                new_plan = self._compute_execution_plan(
                    output["action"],
                    new_pos,
                    card_pack.account_fact_snapshot,
                    card_pack,
                )
                output["position_advice"] = {
                    "current_position_pct": new_pos.current_position_pct,
                    "suggested_target_position_pct": new_pos.suggested_target_position_pct,
                    "max_position_pct": new_pos.max_position_pct,
                    "suggested_cash_amount": new_pos.suggested_cash_amount if new_pos.suggested_cash_amount else 0,
                    "position_size_label": new_pos.position_size_label,
                }
                output["execution_plan"] = {
                    "should_act_now": new_plan.should_act_now,
                    "plan": new_plan.plan,
                    "invalid_conditions": new_plan.invalid_conditions,
                    "recheck_triggers": new_plan.recheck_triggers,
                }
                output["decision_summary"] = self._build_decision_summary(
                    output["action"],
                    result.overall_score,
                    result.rating,
                    result.key_reasons,
                )
                # Re-apply thesis override on the new position_advice so the
                # final max_position_pct reflects both gate and thesis.
                self._apply_thesis_to_position(output, card_pack)
            except Exception:
                # Fall through; the gate has already attached its block.
                pass

        # Build thesis_constraints AFTER position_advice is final, so the
        # constraints reflect the same max_position_pct the gate saw.
        output["thesis_constraints"] = _build_thesis_constraints(
            output.get("investment_thesis") or {}, output
        )

        # Always recompute thesis_status AFTER the risk gate so the status
        # reflects the gated action and the gate's risk_flags.
        output["thesis_status"] = _resolve_thesis_status(
            output.get("investment_thesis") or {}, output, card_pack, result
        )

        # Risk-control hardening: expose one stable block that eval,
        # replay, and frontend code can inspect without reverse-engineering
        # risk_gate + execution_plan + cards.
        output["risk_control"] = _build_risk_control_block(output, card_pack)
        self._apply_weak_catalyst_language(output, card_pack)

        return output

    def _apply_trade_plan_to_output(self, output: dict, card_pack: TradeDecisionCardPack) -> None:
        plan = getattr(card_pack, "trade_plan_card", None)
        if plan is None:
            return
        plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {})
        output["trade_plan"] = plan_dict

        data_limitations = list(plan_dict.get("data_limitations") or [])
        assessment = plan_dict.get("risk_reward_assessment") if isinstance(plan_dict.get("risk_reward_assessment"), dict) else {}
        sanitization_notes = list((assessment or {}).get("sanitization_notes") or [])
        merged_limitations = list(output.get("data_limitations") or [])
        for item in data_limitations + [f"trade_plan_sanitized:{note}" for note in sanitization_notes if note]:
            if item and item not in merged_limitations:
                merged_limitations.append(item)
        output["data_limitations"] = merged_limitations

        summary = str(plan_dict.get("summary") or "").strip()
        if summary:
            reason = f"交易计划: {summary[:240]}"
            key_reasons = list(output.get("key_reasons") or [])
            if reason not in key_reasons:
                output["key_reasons"] = [reason, *key_reasons][:6]

        downside = str((assessment or {}).get("downside_scenario") or "").strip()
        event_window = str((assessment or {}).get("event_risk_window") or "").lower()
        major_risks = list(output.get("major_risks") or [])
        for risk in ([downside] if downside else []) + (["重点事件风险窗口较高，交易计划要求执行前复核"] if event_window in {"critical", "high"} else []):
            if risk and risk not in major_risks:
                major_risks.append(risk[:240])
        output["major_risks"] = major_risks[:8]

        skeleton_fallback = "trade_plan_agent_not_wired" in data_limitations
        portfolio_action = normalize_action(plan_dict.get("portfolio_action") or "")
        if skeleton_fallback and portfolio_action in {"hold_no_add", "watchlist"}:
            return

        output["action"] = portfolio_action
        current_pct = _to_float(plan_dict.get("current_position_pct"))
        target_pct = _to_float(plan_dict.get("target_position_pct"))
        max_pct = _to_float(plan_dict.get("max_position_pct"))
        suggested_cash = _to_float(plan_dict.get("suggested_cash_amount")) or 0
        existing_position = output.get("position_advice") or {}
        output["position_advice"] = {
            "current_position_pct": current_pct,
            "suggested_target_position_pct": target_pct,
            "max_position_pct": max_pct,
            "suggested_cash_amount": suggested_cash,
            "position_size_label": existing_position.get("position_size_label") or _position_size_label(current_pct, target_pct),
        }
        output["execution_plan"] = {
            "should_act_now": portfolio_action in {"add", "add_small", "add_batch", "add_right_side", "reduce_now", "sell_thesis_broken", "sell", "reduce"},
            "plan": _trade_plan_conditions(plan_dict, portfolio_action),
            "invalid_conditions": list(plan_dict.get("invalidation_conditions") or []),
            "recheck_triggers": list(plan_dict.get("recheck_triggers") or []),
        }
        output["asset_stance"] = plan_dict.get("asset_stance")
        output["action_reason_type"] = plan_dict.get("action_reason_type")

    def _compose(self, card_pack: TradeDecisionCardPack) -> ComposerResult:
        snapshot = card_pack.account_fact_snapshot
        acc = card_pack.account_fit_card
        mkt = card_pack.market_trend_card
        fund = card_pack.fundamental_valuation_card
        evt = card_pack.event_catalyst_card
        rr = card_pack.risk_reward_card

        # Compute scores
        score_detail = self._compute_score_detail(card_pack)
        overall_score = self._compute_overall_score(score_detail)

        # Derive ratings
        rating = rating_for_score(overall_score)
        confidence = self._compute_confidence(card_pack)

        # Determine action
        action = self._determine_action(score_detail, snapshot, acc, rr)

        # Position advice
        pos_advice = self._compute_position_advice(snapshot, acc, rr, action)

        # Execution plan
        exec_plan = self._compute_execution_plan(action, pos_advice, snapshot, card_pack)

        # Key reasons
        key_reasons = self._extract_key_reasons(card_pack)

        # Major risks
        major_risks = self._extract_major_risks(card_pack)

        # Review warnings
        review_warnings = self._extract_review_warnings(card_pack)

        # Data limitations
        data_limitations = self._extract_data_limitations(card_pack)

        # Evidence used
        evidence_used = self._extract_evidence_used(card_pack)

        # Data source summary
        data_source_summary = self._compute_data_source_summary(card_pack)

        # Decision summary
        decision_summary = self._build_decision_summary(action, overall_score, rating, key_reasons)

        return ComposerResult(
            symbol=snapshot.symbol,
            decision_type=snapshot.decision_type,
            overall_score=overall_score,
            rating=rating,
            action=action,
            confidence=confidence,
            decision_summary=decision_summary,
            score_detail=score_detail,
            position_advice=pos_advice,
            execution_plan=exec_plan,
            key_reasons=key_reasons,
            major_risks=major_risks,
            review_warnings=review_warnings,
            data_limitations=data_limitations,
            evidence_used=evidence_used,
            data_source_summary=data_source_summary,
        )

    def _compute_score_detail(self, card_pack: TradeDecisionCardPack) -> dict[str, ComposerScoreDetail]:
        acc = card_pack.account_fit_card
        mkt = card_pack.market_trend_card
        fund = card_pack.fundamental_valuation_card
        evt = card_pack.event_catalyst_card
        rr = card_pack.risk_reward_card
        snapshot = card_pack.account_fact_snapshot

        # Fundamental quality score (20): from fundamental card
        if fund and fund.score > 0:
            fund_quality_score = min(20, fund.score)
            fund_quality_reason = _reason_text("基本面分析", fund.summary, 500)
        else:
            fund_quality_score = 0
            fund_quality_reason = "基本面数据不可用"

        # Valuation score (15): from fundamental card PE/fwd PE.
        # PE <= 0 means missing/invalid data, not cheap valuation.
        if fund and fund.pe_ttm is not None and fund.pe_ttm > 0:
            pe = fund.pe_ttm
            if pe < 20:
                valuation_score = 15
                valuation_reason = f"PE TTM {pe:.1f}，估值偏低"
            elif pe < 35:
                valuation_score = 10
                valuation_reason = f"PE TTM {pe:.1f}，估值合理"
            elif pe < 60:
                valuation_score = 6
                valuation_reason = f"PE TTM {pe:.1f}，估值偏高"
            else:
                valuation_score = 2
                valuation_reason = f"PE TTM {pe:.1f}，估值过高"
        elif fund and fund.score > 0 and fund.evidence_quality != "low":
            valuation_score = min(8, int(fund.score * 0.35))
            valuation_reason = f"缺少有效 PE，按基本面估值卡保守折算 {valuation_score}/15"
        else:
            valuation_score = 0
            valuation_reason = "估值数据不可用"

        # Trend score (15): from market trend card
        if mkt and mkt.score > 0:
            trend_score = min(15, mkt.score)
            trend_reason = _reason_text("趋势", mkt.summary, 500)
        else:
            trend_score = 0
            trend_reason = "趋势数据不可用"

        # Account fit score (20): from account fit card
        if acc and acc.score > 0:
            account_fit_score = min(20, acc.score)
            account_fit_reason = _reason_text("账户适配", acc.summary, 500)
        else:
            account_fit_score = 0
            account_fit_reason = "账户数据不可用"

        # Risk/reward score (15): from risk/reward card.
        # Stage 05 - prefer reward_risk_ratio when available; otherwise
        # fall back to rr.score. The R-multiple drives the score so that
        # a ratio of 0 or < 1 pulls the score down hard.
        # Reason priority is preserved from before Stage 05:
        #   risk_assessment_reason > summary > ratio-formatted
        risk_reward_score = 0
        rr_reason = "风险收益数据不可用"
        if rr:
            ratio = getattr(rr, "reward_risk_ratio", None)
            if ratio is not None and ratio >= 0:
                # Map ratio: 0 -> 0, 1.0 -> 6, 2.0 -> 11, 3.0 -> 14, >=4 -> 15
                if ratio < 1.0:
                    risk_reward_score = max(0, int(ratio * 6))
                else:
                    risk_reward_score = min(15, int(6 + (ratio - 1.0) * 3.0))
            elif rr.score > 0:
                risk_reward_score = min(15, rr.score)
            # Reason text: keep the original preference order
            if getattr(rr, "risk_assessment_reason", None):
                rr_reason = _reason_text("风险收益", rr.risk_assessment_reason, 500)
            elif rr.summary:
                rr_reason = _reason_text("风险收益", rr.summary, 500)
            elif ratio is not None and ratio >= 0:
                rr_reason = f"风险收益比 {ratio:.1f}x，上行{(rr.upside_potential_pct or 0):.0f}%，下行{(rr.downside_risk_pct or 0):.0f}%"

        # Review constraint score (10): from account fit review warnings
        review_score = 10
        review_reason = "无复盘警告"
        if acc and acc.review_warnings:
            review_score = 3
            review_reason = f"复盘警告: {'; '.join(acc.review_warnings[:2])}"
        if snapshot.latest_review:
            prev_score = snapshot.latest_review.get("overall_score")
            if prev_score and prev_score < 50:
                review_score = min(review_score, 2)
                review_reason += f"，该标的历史复盘得分{prev_score:.0f}分"

        # Event catalyst score (5): from event card
        if evt and evt.score > 0:
            event_score = min(5, evt.score)
            event_reason = _reason_text("事件催化", evt.summary, 1000)
        else:
            event_score = 0
            event_reason = "事件数据不可用"

        return {
            "fundamental_quality_score": ComposerScoreDetail(fund_quality_score, 20, fund_quality_reason),
            "valuation_score": ComposerScoreDetail(valuation_score, 15, valuation_reason),
            "trend_score": ComposerScoreDetail(trend_score, 15, trend_reason),
            "account_fit_score": ComposerScoreDetail(account_fit_score, 20, account_fit_reason),
            "risk_reward_score": ComposerScoreDetail(risk_reward_score, 15, rr_reason),
            "review_constraint_score": ComposerScoreDetail(review_score, 10, review_reason),
            "event_catalyst_score": ComposerScoreDetail(event_score, 5, event_reason),
        }

    def _compute_overall_score(self, score_detail: dict[str, ComposerScoreDetail]) -> float:
        total = sum(d.score for d in score_detail.values())
        max_total = sum(d.max_score for d in score_detail.values())
        if max_total == 0:
            return 0
        return round(total / max_total * 100, 1)

    def _compute_confidence(self, card_pack: TradeDecisionCardPack) -> str:
        quality = card_pack.data_quality_summary or "low"
        fallback_count = sum(1 for t in card_pack.subagent_traces if t.fallback_used)

        if fallback_count >= 3:
            return "low"
        if quality == "high" and fallback_count == 0:
            return "high"
        if quality == "medium" and fallback_count <= 1:
            return "medium"
        return "low"

    def _determine_action(
        self,
        score_detail: dict[str, ComposerScoreDetail],
        snapshot: AccountFactSnapshot,
        acc: AccountFitCard | None,
        rr: RiskRewardCard | None,
    ) -> str:
        overall = sum(d.score for d in score_detail.values())
        max_possible = sum(d.max_score for d in score_detail.values())
        score_pct = overall / max_possible if max_possible > 0 else 0

        if rr and rr.action_guidance:
            guidance = normalize_action(rr.action_guidance)
            if guidance in RISK_REWARD_INITIAL_ACTIONS:
                return guidance

        # Check if wait_for_pullback
        if rr and rr.wait_for_pullback:
            if snapshot.is_holding:
                return "hold"
            return "wait"

        # Check account fit
        if acc and acc.account_fit_level in ("poor", "unknown"):
            if snapshot.is_holding:
                return "hold"
            return "watchlist"

        # Check liquidity
        deployable = snapshot.deployable_liquidity or 0
        if deployable <= 0 and not snapshot.is_holding:
            return "watchlist"

        # Score-based action
        if score_pct >= 0.8:
            if not snapshot.is_holding:
                return "add_batch"
            return "hold"
        elif score_pct >= 0.65:
            if snapshot.is_holding:
                return "hold"
            return "add_small"
        elif score_pct >= 0.45:
            return "watchlist"
        else:
            return "avoid"

    def _compute_position_advice(
        self,
        snapshot: AccountFactSnapshot,
        acc: AccountFitCard | None,
        rr: RiskRewardCard | None,
        action: str,
    ) -> ComposerPositionAdvice:
        current_pct = snapshot.position_pct or 0

        if action in {"wait", "avoid", "watchlist"} and not snapshot.is_holding:
            return ComposerPositionAdvice(
                current_position_pct=current_pct,
                suggested_target_position_pct=0,
                max_position_pct=0,
                suggested_cash_amount=0,
                position_size_label="none",
            )

        if acc:
            suggested_target = acc.max_suggested_position_pct or 0.05
            max_pct = acc.max_suggested_position_pct or 0.10
            cash_amount = acc.suggested_cash_amount
            size_label = acc.position_size_label
        elif rr:
            suggested_target = rr.max_position_pct or 0.05
            max_pct = rr.max_position_pct or 0.10
            cash_amount = None
            size_label = rr.position_size_label
        else:
            suggested_target = 0.05
            max_pct = 0.10
            cash_amount = None
            size_label = "unknown"

        # For entry decisions with no holding, compute suggested cash from max position
        if not snapshot.is_holding and cash_amount is None:
            net_liq = snapshot.net_liquidation or 1
            max_invest = max_pct * net_liq
            cash_amount = min(max_invest, snapshot.deployable_liquidity or 0)

        return ComposerPositionAdvice(
            current_position_pct=current_pct,
            suggested_target_position_pct=round(suggested_target, 6),
            max_position_pct=round(max_pct, 6),
            suggested_cash_amount=cash_amount,
            position_size_label=size_label,
        )

    def _compute_execution_plan(
        self,
        action: str,
        pos_advice: ComposerPositionAdvice,
        snapshot: AccountFactSnapshot,
        card_pack: TradeDecisionCardPack,
    ) -> ComposerExecutionPlan:
        should_act = action in {
            "add", "add_small", "add_batch", "add_on_pullback", "add_right_side",
            "hold", "hold_no_add", "reduce", "reduce_now", "reduce_batch",
            "trim_on_rebound", "sell", "sell_thesis_broken",
        }
        rr = card_pack.risk_reward_card

        plan: list[dict] = []
        invalid_conditions: list[str] = []
        recheck_triggers: list[str] = []

        if action == "add_on_pullback":
            pullback_pct = getattr(rr, "wait_for_pullback_pct", None) if rr else None
            pullback_level = getattr(rr, "pullback_entry_level", None) if rr else None
            if pullback_pct and pullback_level:
                condition = f"等待回调约{pullback_pct:.1f}%至{pullback_level:.2f}附近再分批买入"
                trigger = f"股价回调约{pullback_pct:.1f}%至{pullback_level:.2f}附近"
                note_extra = f"，计划买点约{pullback_level:.2f}"
            elif pullback_pct:
                condition = f"等待回调约{pullback_pct:.1f}%再分批买入"
                trigger = f"股价回调约{pullback_pct:.1f}%"
                note_extra = ""
            else:
                condition = "等待回调(建议5%以上)再分批买入"
                trigger = "股价回调超过5%"
                note_extra = ""
            plan = [{
                "step": 1,
                "condition": condition,
                "action": "回调后分批建仓，首笔不超过目标仓位40%",
                "amount": None,
                "target_position_pct": round((pos_advice.suggested_target_position_pct or 0) * 0.4, 6),
                "risk_check": "仅在失效条件未触发且仓位低于上限时执行",
                "wait_for_pullback_pct": pullback_pct,
                "pullback_entry_level": pullback_level,
                "first_batch_pct": 0.4,
                "second_batch_condition": "回调后企稳并重新站上短期均线，再考虑第二批",
                "invalidation_condition": "跌破计划买点后继续放量走弱或基本面恶化",
                "note": f"目标仓位{pos_advice.suggested_target_position_pct*100:.1f}%，最大{pos_advice.max_position_pct*100:.1f}%{note_extra}"
            }]
            invalid_conditions = ["未出现有效回调", "回调过程中基本面恶化", "仓位已超过目标"]
            recheck_triggers = [trigger, "估值回到合理区间", "出现明确右侧信号"]

        elif action == "add_right_side":
            plan = [{
                "step": 1,
                "condition": "趋势确认后加仓(如突破阻力、均线重新多头)",
                "action": "右侧信号成立后分批买入",
                "amount": None,
                "target_position_pct": pos_advice.suggested_target_position_pct,
                "risk_check": "突破失败或重新跌回关键位则停止加仓",
                "confirmation_signal": "突破阻力、重新站上关键均线或 trend_break_level=none",
                "breakout_or_reclaim_level": _first_level(getattr(card_pack.market_trend_card, "resistance_levels", None)),
                "max_chase_pct": 3.0,
                "stop_add_condition": "突破后回落并跌破确认位，或仓位达到上限",
                "note": f"目标仓位{pos_advice.suggested_target_position_pct*100:.1f}%，最大{pos_advice.max_position_pct*100:.1f}%"
            }]
            invalid_conditions = ["右侧信号未成立", "趋势重新走弱"]
            recheck_triggers = ["趋势确认", "突破关键阻力位", "回调企稳"]

        elif action == "hold_no_add":
            plan = [{
                "step": 1,
                "condition": "继续持有但不加仓",
                "action": "不操作",
                "amount": None,
                "target_position_pct": pos_advice.current_position_pct,
                "risk_check": "确认禁止加仓原因仍存在",
                "no_add_reason": "仓位/数据/催化/失效条件不足，Risk Gate 已禁用加仓",
                "recheck_trigger": "数据质量改善、仓位下降到目标或出现明确催化",
                "what_would_change_decision": "风险收益比改善且失效条件、仓位上限、催化证据齐全",
                "note": "Risk Gate 已禁用加仓（仓位/数据/催化/失效条件不足）"
            }]
            invalid_conditions = ["仓位已超过目标上限", "数据质量持续偏低", "出现新的下跌风险"]
            recheck_triggers = ["数据质量改善", "仓位下降到目标", "出现明确催化或失效条件"]

        elif action in {"reduce_now", "sell_thesis_broken", "panic_blocked", "trim_on_rebound"}:
            if action == "reduce_now":
                action_text = "立即减仓"
                note = "Risk Gate 识别严重破坏，建议主动降低敞口"
            elif action == "sell_thesis_broken":
                action_text = "分批清仓/退出"
                note = "投资假设已被破坏，建议退出"
            elif action == "panic_blocked":
                action_text = "继续持有（恐慌拦截）"
                note = "情绪化卖出已拦截，按计划继续持有并观察"
            else:
                action_text = "反弹时分批减仓"
                note = "等待反弹机会减仓"
            plan = [{
                "step": 1,
                "condition": "减仓/退出",
                "action": action_text,
                "amount": None,
                "target_position_pct": max((pos_advice.current_position_pct or 0) * 0.5, 0) if action != "sell_thesis_broken" else 0,
                "risk_check": "确认减仓触发条件仍成立，避免在信息误读下执行",
                "reduce_reason": note,
                "target_reduction_pct": 0.5 if action != "sell_thesis_broken" else 1.0,
                "rebound_level": getattr(rr, "trim_level", None) if rr else None,
                "invalidation_condition": "基本面重新确认或风险触发信号消失",
                "note": note
            }]
            invalid_conditions = ["不应继续加仓"] if action == "panic_blocked" else ["基本面重新确认"]
            recheck_triggers = ["减仓完成", "重新评估假设是否仍成立"]

        elif action == "add_batch":
            plan = [{
                "step": 1,
                "condition": "当前无持仓或持仓<2%",
                "action": "分批建仓，首笔不超过总仓位5%",
                "amount": None,
                "target_position_pct": min(pos_advice.suggested_target_position_pct or 0, 0.05),
                "risk_check": "分批前确认失效条件、仓位上限和下行场景",
                "note": f"目标仓位{pos_advice.suggested_target_position_pct*100:.1f}%，最大{pos_advice.max_position_pct*100:.1f}%"
            }]
            if rr and rr.wait_for_pullback:
                plan[0]["condition"] = "等待回调5%以上"
                plan.append({
                    "step": 2,
                    "condition": "已持仓>2%",
                    "action": "持有，不追高",
                    "amount": None,
                    "target_position_pct": pos_advice.suggested_target_position_pct,
                    "risk_check": "未回调或失效条件触发时不加第二批",
                    "note": "等待回调加仓机会"
                })
            recheck_triggers = ["回调超过5%", "公司财报大幅超预期", "市场系统性风险"]

        elif action == "add_small":
            plan = [{
                "step": 1,
                "condition": "现有仓位<5%",
                "action": "小幅加仓",
                "amount": int(pos_advice.suggested_cash_amount or 0) if pos_advice.suggested_cash_amount else None,
                "target_position_pct": pos_advice.suggested_target_position_pct,
                "risk_check": "确认仓位未超过上限且未触发失效条件",
                "note": f"建议现金量${pos_advice.suggested_cash_amount:.0f}" if pos_advice.suggested_cash_amount else ""
            }]
            recheck_triggers = ["仓位超过8%", "下跌超过10%", "出现流动性问题"]

        elif action == "hold":
            plan = [{"step": 1, "condition": "持续持有", "action": "不操作", "amount": None, "target_position_pct": pos_advice.current_position_pct, "risk_check": "持续确认仓位和失效条件", "note": "保持当前仓位"}]
            invalid_conditions = ["持仓超过15%", "单日下跌超过8%", "基本面出现重大恶化"]
            recheck_triggers = ["持仓超过目标仓位", "出现重大宏观风险"]

        elif action == "wait":
            plan = [{
                "step": 1,
                "condition": "等待更好买点",
                "action": "不建仓",
                "amount": None,
                "target_position_pct": 0,
                "risk_check": "等待触发条件，不提前建仓",
                "note": "当前估值或位置不适合建仓"
            }]
            invalid_conditions = ["估值回到合理区间", "出现催化剂"]
            recheck_triggers = ["PE回到历史低位", "有分析师上调评级", "技术面突破关键阻力位"]

        elif action == "avoid":
            plan = [{"step": 1, "condition": "规避", "action": "不建仓/清仓", "amount": None, "target_position_pct": 0, "risk_check": "风险收益比改善前不行动", "note": "风险收益比不具吸引力"}]
            invalid_conditions = ["所有买入条件均已失效"]
            recheck_triggers = ["风险收益比明显改善"]

        elif action in {"reduce", "reduce_batch", "sell"}:
            plan = [{
                "step": 1,
                "condition": "减仓",
                "action": f"{'分批' if action == 'reduce_batch' else ''}减仓{'/清仓' if action == 'sell' else ''}",
                "amount": None,
                "target_position_pct": 0 if action == "sell" else max((pos_advice.current_position_pct or 0) * 0.5, 0),
                "risk_check": "确认减仓理由仍成立",
                "note": f"当前持仓{pos_advice.current_position_pct*100:.2f}%"
            }]
            recheck_triggers = ["持仓降到目标仓位", "出现更好再入场时机"]

        else:
            plan = [{"step": 1, "condition": "观望", "action": "不操作", "amount": None, "target_position_pct": pos_advice.current_position_pct, "risk_check": "等待信息更充分", "note": ""}]

        return ComposerExecutionPlan(
            should_act_now=should_act,
            plan=plan,
            invalid_conditions=invalid_conditions,
            recheck_triggers=recheck_triggers,
        )

    def _extract_key_reasons(self, card_pack: TradeDecisionCardPack) -> list[str]:
        reasons: list[str] = []
        acc = card_pack.account_fit_card
        mkt = card_pack.market_trend_card
        fund = card_pack.fundamental_valuation_card
        evt = card_pack.event_catalyst_card
        rr = card_pack.risk_reward_card
        snapshot = card_pack.account_fact_snapshot

        if acc and acc.account_fit_level in ("excellent", "good"):
            reasons.append(f"账户适配{acc.account_fit_level}，可用流动性{(snapshot.deployable_liquidity_ratio or 0)*100:.1f}%")

        if mkt and mkt.stance == CardStance.BULLISH:
            reasons.append(f"市场趋势看涨：{mkt.summary[:60]}")
        elif mkt and mkt.stance == CardStance.BEARISH:
            reasons.append(f"市场趋势看跌：{mkt.summary[:60]}")

        if fund and fund.pe_ttm:
            reasons.append(f"PE TTM {fund.pe_ttm:.1f}，{fund.valuation_summary}")

        if evt and evt.key_events:
            reasons.extend(evt.key_events[:2])

        if rr and rr.key_opportunities:
            reasons.extend(rr.key_opportunities[:2])
        elif rr and rr.reward_risk_ratio and rr.reward_risk_ratio >= 2.0:
            reasons.append(f"风险收益比 {rr.reward_risk_ratio:.1f}x，具吸引力")

        if snapshot.is_holding and snapshot.holding_days and snapshot.holding_days > 30:
            reasons.append(f"已持有{snapshot.holding_days}天，趋势稳定")

        return reasons[:5]

    def _extract_major_risks(self, card_pack: TradeDecisionCardPack) -> list[str]:
        risks: list[str] = []
        acc = card_pack.account_fit_card
        mkt = card_pack.market_trend_card
        fund = card_pack.fundamental_valuation_card
        evt = card_pack.event_catalyst_card
        rr = card_pack.risk_reward_card

        if acc and acc.review_warnings:
            risks.extend(acc.review_warnings[:2])

        if mkt and mkt.stance == CardStance.BEARISH:
            risks.append(f"市场趋势看跌：{mkt.summary[:60]}")

        if fund and fund.pe_ttm and fund.pe_ttm > 50:
            risks.append(f"PE估值过高({fund.pe_ttm:.1f})，有估值压缩风险")

        if rr and rr.key_risks:
            risks.extend(rr.key_risks[:2])

        if rr and rr.downside_risk_pct and rr.downside_risk_pct > 20:
            risks.append(f"下行风险较高({rr.downside_risk_pct:.0f}%)")

        if evt and evt.risk_events:
            risks.extend(evt.risk_events[:2])

        return risks[:5]

    def _extract_review_warnings(self, card_pack: TradeDecisionCardPack) -> list[str]:
        warnings: list[str] = []
        acc = card_pack.account_fit_card
        snapshot = card_pack.account_fact_snapshot

        if acc and acc.review_warnings:
            warnings.extend(acc.review_warnings)

        if acc and acc.historical_mistake_flags:
            warnings.append(f"历史错误模式: {', '.join(acc.historical_mistake_flags[:2])}")

        if snapshot.latest_review:
            tags = snapshot.latest_review.get("mistake_tags") or []
            for tag in (tags[:3] if isinstance(tags, list) else []):
                warnings.append(f"复盘标记: {tag}")

        return list(dict.fromkeys(warnings))[:5]

    def _extract_data_limitations(self, card_pack: TradeDecisionCardPack) -> list[str]:
        limitations: list[str] = []
        for card in [card_pack.account_fit_card, card_pack.market_trend_card,
                     card_pack.fundamental_valuation_card, card_pack.event_catalyst_card,
                     card_pack.risk_reward_card]:
            if card and card.data_limitations:
                for item in card.data_limitations:
                    # Filter out tool-level mcp_field_missing diagnostics
                    if not isinstance(item, str):
                        continue
                    cleaned = _clean_user_data_limitation(item)
                    if cleaned:
                        limitations.append(cleaned)

        if card_pack.data_quality_summary == "low":
            limitations.append("部分子代理使用了 fallback，数据质量偏低")

        fallback_count = sum(1 for t in card_pack.subagent_traces if t.fallback_used)
        if fallback_count >= 2:
            limitations.append(f"{fallback_count}个子代理使用了 fallback，结果仅供参考")

        return list(dict.fromkeys(limitations))[:8]

    def _extract_evidence_used(self, card_pack: TradeDecisionCardPack) -> list[str]:
        evidence: list[str] = []
        for card in [card_pack.account_fit_card, card_pack.market_trend_card,
                     card_pack.fundamental_valuation_card, card_pack.event_catalyst_card,
                     card_pack.risk_reward_card]:
            if card:
                for tool in (card.source_tools or []):
                    evidence.append(f"{tool}: {card.summary[:50]}")
        return evidence[:10]

    def _compute_data_source_summary(self, card_pack: TradeDecisionCardPack) -> dict[str, str]:
        public_tools: list[str] = []
        for card in [card_pack.market_trend_card, card_pack.fundamental_valuation_card, card_pack.event_catalyst_card]:
            if card and card.source_tools:
                public_tools.extend(card.source_tools)
        return {
            "account_data": "IBKR_ONLY",
            "position_data": "IBKR_ONLY",
            "trade_data": "IBKR_ONLY",
            "public_market_data": "LONGBRIDGE_MCP" if public_tools else "LONGBRIDGE_MCP_UNAVAILABLE",
            "review_data": "IBKR_ONLY",
            "card_schema_version": "card_schema_v1",
        }

    def _build_decision_summary(
        self,
        action: str,
        overall_score: float,
        rating: str,
        key_reasons: list[str],
    ) -> str:
        action_map = {
            "add_batch": "建议分批建仓",
            "add_small": "建议小幅加仓",
            "add": "建议加仓",
            "add_on_pullback": "建议回调加仓",
            "add_right_side": "建议右侧加仓",
            "hold": "建议持有",
            "hold_no_add": "建议持有但暂不加仓",
            "reduce": "建议减仓",
            "reduce_now": "建议立即减仓",
            "reduce_batch": "建议分批减仓",
            "trim_on_rebound": "建议反弹减仓",
            "sell": "建议清仓",
            "sell_thesis_broken": "投资假设已破坏，建议清仓退出",
            "panic_blocked": "情绪化卖出请求已拦截，建议继续持有",
            "wait": "建议等待",
            "avoid": "建议规避",
            "watchlist": "建议观望",
        }
        base = action_map.get(action, f"建议{action}")
        score_note = f"综合评分{overall_score:.0f}分" if overall_score > 0 else ""
        reason_note = key_reasons[0][:40] if key_reasons else ""
        return " ".join(filter(None, [base, score_note, reason_note]))[:200]

    def _apply_weak_catalyst_language(self, output: dict[str, Any], card_pack: TradeDecisionCardPack) -> None:
        evt = card_pack.event_catalyst_card
        rg_flags = set((output.get("risk_gate") or {}).get("risk_flags") or [])
        weak = bool(
            "weak_catalyst_downgrade" in rg_flags
            or (evt and getattr(evt, "catalyst_strength", None) in {"weak", "no_catalyst"})
            or (evt and (getattr(evt, "score", 0) or 0) <= 1)
        )
        if not weak:
            return
        summary = str(output.get("decision_summary") or "")
        prefix = "弱催化不构成独立加仓理由，建议观察；"
        if "弱催化" not in summary and "不构成独立加仓理由" not in summary:
            output["decision_summary"] = (prefix + summary)[:200]
        reasons = list(output.get("key_reasons") or [])
        downgrade_reason = "弱催化：证据不足，不构成独立加仓理由"
        if downgrade_reason not in reasons:
            output["key_reasons"] = [downgrade_reason] + reasons[:4]

    # ------------------------------------------------------------------
    # Stage 03 - Investment Thesis helpers
    # ------------------------------------------------------------------
    def _attach_investment_thesis(self, card_pack: TradeDecisionCardPack) -> None:
        """Resolve and attach the per-symbol InvestmentThesis to the card_pack.

        Idempotent: does nothing when the thesis is already attached.
        """
        if card_pack.investment_thesis:
            return
        try:
            from app.services.investment_thesis import get_thesis

            thesis = get_thesis(card_pack.symbol)
            card_pack.investment_thesis = thesis.to_dict()
        except Exception:
            # A missing or broken thesis registry must NEVER break composition.
            card_pack.investment_thesis = {}

    def _apply_thesis_to_position(
        self,
        output: dict[str, Any],
        card_pack: TradeDecisionCardPack,
    ) -> None:
        """Override position_advice.max_position_pct and suggested_target with
        the thesis values. The Risk Gate still applies its own structural
        checks on top of these values.

        We only apply the override when the action is add-like (or hold with
        a position). For wait / avoid / watchlist (no add), the original
        zero-target behavior is preserved.
        """
        thesis = card_pack.investment_thesis or {}
        if not isinstance(thesis, dict) or not thesis:
            return
        try:
            thesis_max = float(thesis.get("max_position_pct") or 0)
        except (TypeError, ValueError):
            thesis_max = 0.0
        try:
            thesis_target = thesis.get("target_position_pct")
            thesis_target_f = float(thesis_target) if thesis_target is not None else None
        except (TypeError, ValueError):
            thesis_target_f = None

        if thesis_max <= 0:
            return

        final_action = str(output.get("action") or "")
        # For non-add actions we keep the original "0 target" semantics
        # so the wait/avoid/watchlist flows still mean "no entry".
        add_like = {
            "add", "add_small", "add_batch", "add_on_pullback",
            "add_right_side", "hold", "hold_no_add", "reduce",
            "reduce_now", "reduce_batch", "trim_on_rebound",
            "sell", "sell_thesis_broken",
        }
        if final_action not in add_like:
            return

        position_advice = output.get("position_advice") or {}
        current_max = position_advice.get("max_position_pct")
        try:
            current_max_f = float(current_max) if current_max is not None else 0.0
        except (TypeError, ValueError):
            current_max_f = 0.0
        # P3 - thesis.max_position_pct is the per-symbol authoritative
        # budget. When the thesis is configured with a positive max, we
        # always use it (whether the current value is smaller or larger),
        # so the Risk Gate and the final position_advice stay in sync.
        if current_max_f <= 0 or thesis_max != current_max_f:
            position_advice["max_position_pct"] = round(thesis_max, 6)

        # Only override suggested_target when the existing target is non-zero
        # (i.e. we actually intend to add / hold a position).
        try:
            current_target_f = float(position_advice.get("suggested_target_position_pct") or 0)
        except (TypeError, ValueError):
            current_target_f = 0.0
        if thesis_target_f is not None and thesis_target_f > 0 and current_target_f > 0:
            position_advice["suggested_target_position_pct"] = round(thesis_target_f, 6)

        # If the symbol is unknown and the thesis is conservative (5%),
        # surface that explicitly.
        if str(thesis.get("role") or "") == "unknown":
            position_advice.setdefault("position_size_label", "thesis_unknown")
        output["position_advice"] = position_advice


def _resolve_thesis_status(
    thesis: dict[str, Any],
    output: dict[str, Any],
    card_pack: TradeDecisionCardPack,
    result: "ComposerResult",
) -> str:
    """Return a short string describing thesis status.

    - 'unknown'  : no thesis configured for this symbol
    - 'intact'   : thesis known and no sell_triggers hit
    - 'broken'   : final action is reduce_now / sell_thesis_broken
    - 'stressed' : risk_gate flagged a thesis-related downgrade
    """
    if not thesis or not isinstance(thesis, dict) or not thesis.get("role") or thesis.get("role") == "unknown":
        return "unknown"
    final_action = str(output.get("action") or "")
    if final_action in {"reduce_now", "sell_thesis_broken"}:
        return "broken"
    rg = output.get("risk_gate") or {}
    flags = set(rg.get("risk_flags") or [])
    if flags & {"thesis_breakdown_detected", "thesis_broken_detected", "fundamental_red_action", "fundamental_red_blocked"}:
        return "broken"
    if flags & {"trend_break_severe_blocked", "trend_break_broken_blocked", "weak_catalyst_downgrade",
                "fundamental_orange_blocked", "fundamental_yellow_downgrade"}:
        return "stressed"
    return "intact"


def _build_thesis_constraints(
    thesis: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Compute headroom and explain max_position_pct vs current position."""
    position_advice = output.get("position_advice") or {}
    try:
        max_pct = float(position_advice.get("max_position_pct") or 0)
    except (TypeError, ValueError):
        max_pct = 0.0
    try:
        current_pct = float(position_advice.get("current_position_pct") or 0)
    except (TypeError, ValueError):
        current_pct = 0.0
    headroom = round(max_pct - current_pct, 6) if max_pct else 0.0
    role = (thesis or {}).get("role") or "unknown"
    return {
        "max_position_pct": max_pct,
        "current_position_pct": current_pct,
        "headroom_pct": headroom,
        "role": role,
        "review_frequency": (thesis or {}).get("review_frequency") or "unknown",
    }


def _build_risk_control_block(output: dict[str, Any], card_pack: TradeDecisionCardPack) -> dict[str, Any]:
    position = output.get("position_advice") or {}
    execution = output.get("execution_plan") or {}
    risk_gate = output.get("risk_gate") or {}
    rr = card_pack.risk_reward_card
    mkt = card_pack.market_trend_card
    fund = card_pack.fundamental_valuation_card

    max_pct = _safe_float_local(position.get("max_position_pct"))
    current_pct = _safe_float_local(position.get("current_position_pct"))
    target_pct = _safe_float_local(position.get("suggested_target_position_pct"))
    invalidation_conditions = list(execution.get("invalid_conditions") or [])
    recheck_triggers = list(execution.get("recheck_triggers") or [])
    plan = list(execution.get("plan") or [])
    risk_flags = list(risk_gate.get("risk_flags") or [])

    stop_add_conditions = _build_stop_add_conditions(output, card_pack, invalidation_conditions)
    data_limitations = list(output.get("data_limitations") or [])
    for card in (mkt, fund, rr):
        for item in getattr(card, "data_limitations", []) or []:
            if item and item not in data_limitations:
                data_limitations.append(item)

    return {
        "max_position_pct": max_pct,
        "current_position_pct": current_pct,
        "suggested_target_position_pct": target_pct,
        "position_limit_status": _position_limit_status(current_pct, max_pct),
        "invalidation_conditions": invalidation_conditions,
        "stop_add_conditions": stop_add_conditions,
        "recheck_triggers": recheck_triggers,
        "batch_plan": plan,
        "downside_scenarios": list(getattr(rr, "downside_scenarios", []) or []),
        "reward_risk_ratio": getattr(rr, "reward_risk_ratio", None) if rr else None,
        "risk_flags": risk_flags,
        "data_limitations": list(dict.fromkeys(str(x) for x in data_limitations if x)),
    }


def _build_stop_add_conditions(
    output: dict[str, Any],
    card_pack: TradeDecisionCardPack,
    invalidation_conditions: list[str],
) -> list[str]:
    rr = card_pack.risk_reward_card
    mkt = card_pack.market_trend_card
    fund = card_pack.fundamental_valuation_card
    conditions: list[str] = []
    stop_add_level = getattr(rr, "stop_add_level", None) if rr else None
    invalidation_level = getattr(rr, "invalidation_level", None) if rr else None
    if stop_add_level:
        conditions.append(f"跌破 stop_add_level {stop_add_level} 停止加仓")
    if invalidation_level:
        conditions.append(f"跌破 invalidation_level {invalidation_level} 重新评估")
    trend_break = getattr(mkt, "trend_break_level", None) if mkt else None
    if trend_break in {"warning", "broken", "severe"}:
        conditions.append(f"trend_break_level={trend_break} 时停止追加强加仓")
    fund_status = getattr(fund, "fundamental_status", None) if fund else None
    if fund_status in {"yellow", "orange", "red"}:
        conditions.append(f"fundamental_status={fund_status} 时停止加仓")
    conditions.extend(str(x) for x in invalidation_conditions if x)
    if not conditions:
        conditions.append("触发失效条件、仓位达到上限或风险收益比恶化时停止加仓")
    return list(dict.fromkeys(conditions))[:8]


def _position_limit_status(current_pct: float | None, max_pct: float | None) -> str:
    if current_pct is None or max_pct is None or max_pct <= 0:
        return "unknown"
    if current_pct > max_pct:
        return "over_limit"
    if abs(current_pct - max_pct) <= 1e-6:
        return "at_limit"
    if current_pct >= max_pct * 0.8:
        return "near_limit"
    return "below_limit"


def _safe_float_local(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    return _safe_float_local(value)


def _position_size_label(current_pct: float | None, target_pct: float | None) -> str:
    current = current_pct or 0
    target = target_pct or 0
    if target <= 0:
        return "none"
    if target <= current:
        return "keep"
    if target < 0.03:
        return "starter"
    if target < 0.08:
        return "small"
    if target < 0.15:
        return "medium"
    return "large"


def _trade_plan_conditions(plan_dict: dict[str, Any], action: str) -> list[dict]:
    conditions = list(plan_dict.get("execution_conditions") or [])
    if not conditions:
        conditions = ["按交易计划草案等待条件满足"]
    target_pct = _to_float(plan_dict.get("target_position_pct"))
    amount = _to_float(plan_dict.get("suggested_cash_amount")) or 0
    return [
        {
            "step": idx,
            "condition": str(condition)[:1200],
            "action": action,
            "amount": amount if amount > 0 else None,
            "target_position_pct": target_pct,
            "risk_check": "执行前必须通过 deterministic Risk Gate，并确认未触发失效条件",
            "note": str(plan_dict.get("summary") or "")[:500],
        }
        for idx, condition in enumerate(conditions[:8], start=1)
    ]


def _first_level(levels: Any) -> float | None:
    if not isinstance(levels, list):
        return None
    for level in levels:
        try:
            return float(level)
        except (TypeError, ValueError):
            continue
    return None
