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
    "add", "add_small", "add_batch", "hold", "reduce", "reduce_batch",
    "sell", "wait", "avoid", "watchlist",
}

ACTION_ALIASES = {
    "buy": "add_batch", "buy_now": "add", "strong_buy": "add",
    "accumulate": "add_batch", "increase": "add",
    "add_on_dips": "add_small", "add_on_pullback": "add_small",
    "buy_on_dips": "add_small", "buy_on_pullback": "add_small",
    "hold_or_add": "add_small", "hold_or_add_small": "add_small",
    "hold_and_add": "add_small", "hold_add_small": "add_small",
    "wait_for_pullback": "wait", "wait_pullback": "wait",
    "do_nothing": "hold", "trim": "reduce", "partial_sell": "reduce_batch",
    "full_sell": "sell", "clear": "sell", "exit": "sell",
    "watch": "watchlist", "observe": "watchlist", "hold_wait": "wait",
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
        result = self._compose(card_pack)
        return {
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

        # Risk/reward score (15): from risk/reward card
        if rr and rr.score > 0:
            risk_reward_score = min(15, rr.score)
            if getattr(rr, "risk_assessment_reason", None):
                rr_reason = _reason_text("风险收益", rr.risk_assessment_reason, 500)
            elif rr.summary:
                rr_reason = _reason_text("风险收益", rr.summary, 500)
            else:
                rr_reason = f"风险收益比 {rr.reward_risk_ratio or 0:.1f}x，上行{(rr.upside_potential_pct or 0):.0f}%，下行{(rr.downside_risk_pct or 0):.0f}%"
        else:
            risk_reward_score = 0
            rr_reason = "风险收益数据不可用"

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
        should_act = action in {"add", "add_small", "add_batch", "hold", "reduce", "reduce_batch"}
        rr = card_pack.risk_reward_card

        plan: list[dict] = []
        invalid_conditions: list[str] = []
        recheck_triggers: list[str] = []

        if action == "add_batch":
            plan = [{
                "step": 1,
                "condition": "当前无持仓或持仓<2%",
                "action": "分批建仓，首笔不超过总仓位5%",
                "amount": None,
                "note": f"目标仓位{pos_advice.suggested_target_position_pct*100:.1f}%，最大{pos_advice.max_position_pct*100:.1f}%"
            }]
            if rr and rr.wait_for_pullback:
                plan[0]["condition"] = "等待回调5%以上"
                plan.append({
                    "step": 2,
                    "condition": "已持仓>2%",
                    "action": "持有，不追高",
                    "amount": None,
                    "note": "等待回调加仓机会"
                })
            recheck_triggers = ["回调超过5%", "公司财报大幅超预期", "市场系统性风险"]

        elif action == "add_small":
            plan = [{
                "step": 1,
                "condition": "现有仓位<5%",
                "action": "小幅加仓",
                "amount": int(pos_advice.suggested_cash_amount or 0) if pos_advice.suggested_cash_amount else None,
                "note": f"建议现金量${pos_advice.suggested_cash_amount:.0f}" if pos_advice.suggested_cash_amount else ""
            }]
            recheck_triggers = ["仓位超过8%", "下跌超过10%", "出现流动性问题"]

        elif action == "hold":
            plan = [{"step": 1, "condition": "持续持有", "action": "不操作", "amount": None, "note": "保持当前仓位"}]
            invalid_conditions = ["持仓超过15%", "单日下跌超过8%", "基本面出现重大恶化"]
            recheck_triggers = ["持仓超过目标仓位", "出现重大宏观风险"]

        elif action == "wait":
            plan = [{
                "step": 1,
                "condition": "等待更好买点",
                "action": "不建仓",
                "amount": None,
                "note": "当前估值或位置不适合建仓"
            }]
            invalid_conditions = ["估值回到合理区间", "出现催化剂"]
            recheck_triggers = ["PE回到历史低位", "有分析师上调评级", "技术面突破关键阻力位"]

        elif action == "avoid":
            plan = [{"step": 1, "condition": "规避", "action": "不建仓/清仓", "amount": None, "note": "风险收益比不具吸引力"}]
            invalid_conditions = ["所有买入条件均已失效"]
            recheck_triggers = ["风险收益比明显改善"]

        elif action in {"reduce", "reduce_batch", "sell"}:
            plan = [{
                "step": 1,
                "condition": "减仓",
                "action": f"{'分批' if action == 'reduce_batch' else ''}减仓{'/清仓' if action == 'sell' else ''}",
                "amount": None,
                "note": f"当前持仓{pos_advice.current_position_pct*100:.2f}%"
            }]
            recheck_triggers = ["持仓降到目标仓位", "出现更好再入场时机"]

        else:
            plan = [{"step": 1, "condition": "观望", "action": "不操作", "amount": None, "note": ""}]

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
            "hold": "建议持有",
            "reduce": "建议减仓",
            "reduce_batch": "建议分批减仓",
            "sell": "建议清仓",
            "wait": "建议等待",
            "avoid": "建议规避",
            "watchlist": "建议观望",
        }
        base = action_map.get(action, f"建议{action}")
        score_note = f"综合评分{overall_score:.0f}分" if overall_score > 0 else ""
        reason_note = key_reasons[0][:40] if key_reasons else ""
        return " ".join(filter(None, [base, score_note, reason_note]))[:200]
