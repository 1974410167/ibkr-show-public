"""
TradeDecision Risk Gate - deterministic gating layer that runs after the composer
and before the final action is published.

Goals:
1. Make actions safe by enforcing hard risk constraints:
   - No "add" actions without a position limit.
   - No "add" actions without invalidation conditions.
   - No confident add when public data is broadly fallback.
   - No "add" / "add_batch" when catalyst is weak.
   - No "add" when current position already meets/exceeds max position.
   - Detect and block panic-driven "sell" asks when thesis is intact.
2. Expand the action vocabulary with explicit semantics:
   - hold_no_add, add_on_pullback, add_right_side, trim_on_rebound,
     reduce_now, sell_thesis_broken, panic_blocked.
3. Surface `risk_gate` block in decision_output so downstream consumers
   (frontend / eval) can see the reasons for any downgrade.

The gate is intentionally deterministic and does NOT call LLM/MCP.
All inputs come from the card pack + composer output that the caller passes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
)


# Action vocabulary - keep aligned with the composer's ALLOWED_ACTIONS plus
# the new explicit gate actions. The composer remains the source of truth for
# its own ALLOWED_ACTIONS set; the gate adds entries the composer may emit
# (e.g. add_on_pullback, hold_no_add) and includes legacy add* / hold / sell.
RISK_GATE_ACTIONS = {
    # Legacy / composer
    "add",
    "add_small",
    "add_batch",
    "hold",
    "reduce",
    "reduce_batch",
    "sell",
    "wait",
    "avoid",
    "watchlist",
    # New explicit gate actions
    "hold_no_add",
    "add_on_pullback",
    "add_right_side",
    "trim_on_rebound",
    "reduce_now",
    "sell_thesis_broken",
    "panic_blocked",
}

ADD_LIKE_ACTIONS = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
STRONG_ADD_ACTIONS = {"add", "add_batch", "add_right_side"}
HOLD_LIKE_ACTIONS = {"hold", "hold_no_add", "wait", "watchlist", "avoid"}
EXIT_LIKE_ACTIONS = {"sell", "sell_thesis_broken", "reduce", "reduce_batch", "trim_on_rebound", "reduce_now"}

# Tokens that suggest the user is in a panic state and wants to dump a position
# for non-thesis reasons. Matched against user_question + decision summary.
PANIC_TOKENS_ZH = (
    "清仓", "割肉", "受不了", "暴跌", "恐慌", "大跌", "赶紧卖", "全卖", "都卖", "卖掉", "快卖", "我要卖", "全部卖出", "都卖了",
)
PANIC_TOKENS_EN = (
    "panic sell", "sell everything", "dump it", "cut loss", "cut my losses",
    "i can't take it", "market crash", "blood bath", "bloodbath",
)


@dataclass
class RiskGateResult:
    original_action: str
    final_action: str
    blocked: bool
    downgraded: bool
    gate_reasons: list[str]
    required_disclosures: list[str]
    risk_flags: list[str]
    action_constraints: dict
    # P2 - confidence cap the composer must apply to decision_output.confidence
    confidence_cap: str | None = None
    # True when the gate was unable to run (e.g. exception). P1 fail-safe.
    failed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_action": self.original_action,
            "final_action": self.final_action,
            "blocked": self.blocked,
            "downgraded": self.downgraded,
            "gate_reasons": list(self.gate_reasons),
            "required_disclosures": list(self.required_disclosures),
            "risk_flags": list(self.risk_flags),
            "action_constraints": dict(self.action_constraints),
            "confidence_cap": self.confidence_cap,
            "failed": self.failed,
            "error": self.error,
        }


# Confidence ordering for P2 cap enforcement. Lower index = lower confidence.
CONFIDENCE_ORDER = ["low", "medium", "high"]


def _clamp_confidence(current: str | None, cap: str | None) -> str:
    """Lower `current` to the cap when cap is lower (more conservative)."""
    if not cap:
        return current or "low"
    cur_idx = CONFIDENCE_ORDER.index(current) if current in CONFIDENCE_ORDER else 0
    cap_idx = CONFIDENCE_ORDER.index(cap) if cap in CONFIDENCE_ORDER else 0
    # Use the LOWER (more conservative) of the two.
    chosen = CONFIDENCE_ORDER[min(cur_idx, cap_idx)]
    return chosen


class RiskGate:
    """Deterministic risk gate applied to a composed trade decision.

    Inputs:
      decision_output: dict produced by TradeDecisionComposer.compose
      card_pack: TradeDecisionCardPack
      user_question: optional str

    Output:
      RiskGateResult with final action, reasons, flags, constraints.
    """

    def evaluate(
        self,
        decision_output: dict[str, Any],
        card_pack: TradeDecisionCardPack,
        user_question: str | None = None,
    ) -> RiskGateResult:
        original_action = str(decision_output.get("action") or "watchlist")
        final_action = original_action
        reasons: list[str] = []
        flags: list[str] = []
        disclosures: list[str] = []
        constraints: dict[str, Any] = {}

        snapshot = card_pack.account_fact_snapshot
        acc = card_pack.account_fit_card
        mkt = card_pack.market_trend_card
        fund = card_pack.fundamental_valuation_card
        evt = card_pack.event_catalyst_card
        rr = card_pack.risk_reward_card

        public_fallback_count = _count_public_fallback(card_pack)

        position_advice = decision_output.get("position_advice") or {}
        max_pct = _safe_float(position_advice.get("max_position_pct"))
        current_pct = _safe_float(position_advice.get("current_position_pct"))
        suggested_target_pct = _safe_float(position_advice.get("suggested_target_position_pct"))
        ai_policy = _dict(getattr(card_pack, "ai_policy_assessment", None))
        ai_status = str(ai_policy.get("status") or "")
        ai_max_pct = _safe_float(ai_policy.get("ai_recommended_max_position_pct")) if ai_status == "evaluated" else None
        ai_target_range = ai_policy.get("ai_recommended_target_position_range_pct") if ai_status == "evaluated" else None
        ai_position_stance = str(ai_policy.get("ai_position_stance") or "") if ai_status == "evaluated" else None
        ai_action_bias = str(ai_policy.get("recommended_action_bias") or "") if ai_status == "evaluated" else None
        ai_supports_pullback_add = _ai_supports_pullback_add(ai_status, ai_position_stance, ai_action_bias)
        if ai_status == "evaluated":
            constraints["ai_recommended_max_position_pct"] = ai_max_pct
            constraints["ai_recommended_target_position_range_pct"] = ai_target_range
            constraints["ai_position_stance"] = ai_position_stance
            constraints["ai_recommended_action_bias"] = ai_action_bias

        execution_plan = decision_output.get("execution_plan") or {}
        invalid_conditions = list(execution_plan.get("invalid_conditions") or [])

        # -- 0. Panic detection runs first because it short-circuits the rest
        #    of the add-style downgrades.
        panic = self._detect_panic(user_question=user_question, decision_output=decision_output, card_pack=card_pack)
        if panic:
            final_action = "panic_blocked"
            reasons.append("用户问题或决策摘要含恐慌/清仓意图，但基本面、趋势、仓位、风险收益均不支持卖出")
            flags.append("panic_sell_blocked")
            disclosures.append("已识别为情绪化卖出请求并拦截；继续按原计划持有并观察")
            return RiskGateResult(
                original_action=original_action,
                final_action=final_action,
                blocked=True,
                downgraded=original_action != final_action,
                gate_reasons=reasons,
                required_disclosures=disclosures,
                risk_flags=flags,
                action_constraints={
                    "snapshot": {
                        "current_position_pct": current_pct,
                        "max_position_pct": max_pct,
                        "public_fallback_count": public_fallback_count,
                    },
                    "panic_match": panic,
                },
                confidence_cap="low",
            )

        # -- 1. Missing position limit blocks any add-style action.
        if final_action in ADD_LIKE_ACTIONS and (max_pct is None or max_pct <= 0):
            final_action = _downgrade_to_hold_no_add(final_action, snapshot)
            reasons.append("缺少最大仓位上限，不能输出加仓建议")
            flags.append("missing_position_limit")
            constraints["required"] = ["max_position_pct"]

        # -- 2. Strong add without invalidation conditions must be downgraded.
        if final_action in STRONG_ADD_ACTIONS and not invalid_conditions:
            final_action = "add_on_pullback" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append("缺少失效条件，强加仓已降级")
            flags.append("missing_invalidation_conditions")
            constraints["required"] = list(set(constraints.get("required", []) + ["invalid_conditions"]))

        # -- 3. Data insufficiency forces confidence<=medium and removes add.
        insufficient_data = public_fallback_count >= 2
        if insufficient_data:
            if final_action in ADD_LIKE_ACTIONS:
                final_action = _downgrade_to_hold_no_add(final_action, snapshot)
                reasons.append("公开市场数据不足/质量偏低，禁止输出加仓")
                flags.append("insufficient_data")
            # Confidence is capped; surfaced as a required disclosure.
            if str(decision_output.get("confidence") or "").lower() == "high":
                disclosures.append("公开数据不足，confidence 应不高于 medium")

        # -- 4. Weak catalyst must not trigger add / add_batch. It may only
        # keep add_right_side when risk/reward, trend, and fundamentals are
        # independently strong enough to overcome the weak catalyst.
        weak_catalyst = _is_weak_catalyst(evt)
        rr_ratio_for_weak = _safe_float(getattr(rr, "reward_risk_ratio", None)) if rr else None
        trend_for_weak = _get_trend_break_level(mkt)
        fund_for_weak = _get_fundamental_status(fund)
        weak_right_side_allowed = (
            final_action == "add_right_side"
            and rr_ratio_for_weak is not None
            and rr_ratio_for_weak >= 2.0
            and trend_for_weak == "none"
            and fund_for_weak in {"green", "yellow"}
        )
        weak_pullback_allowed = (
            final_action == "add_on_pullback"
            and ai_supports_pullback_add
            and (rr_ratio_for_weak is None or rr_ratio_for_weak >= 1.5)
            and trend_for_weak in {"none", "warning", "unknown"}
            and fund_for_weak in {"green", "yellow", "unknown"}
        )
        if final_action in ADD_LIKE_ACTIONS and weak_catalyst and not weak_right_side_allowed:
            if weak_pullback_allowed:
                reasons.append("催化偏弱，但 AI 支持回调加仓，保留 add_on_pullback 并要求条件触发")
                flags.append("weak_catalyst_soft_warning")
            elif final_action in {"add", "add_batch", "add_right_side", "add_small"} and ai_supports_pullback_add and (rr_ratio_for_weak is None or rr_ratio_for_weak >= 1.5):
                final_action = "add_on_pullback"
                reasons.append("催化偏弱，强加仓已降级为回调加仓")
                flags.append("weak_catalyst_downgrade_to_pullback")
            else:
                final_action = "wait" if not _is_holding(snapshot) else "hold_no_add"
                reasons.append("催化偏弱，加仓已降级为回调加仓或暂不加仓")
                flags.append("weak_catalyst_downgrade")
        elif weak_catalyst and original_action in ADD_LIKE_ACTIONS and not weak_right_side_allowed:
            reasons.append("催化偏弱，不构成独立加仓理由")
            flags.append("weak_catalyst_downgrade")

        # -- 5. Already at/above max position or account is concentrated/poor.
        if final_action in ADD_LIKE_ACTIONS:
            at_position_limit = (max_pct is not None and current_pct is not None and max_pct > 0 and current_pct >= max_pct)
            poor_fit = bool(acc and acc.account_fit_level in ("concentrated", "poor"))
            if at_position_limit or poor_fit:
                final_action = "hold_no_add"
                reasons.append("已达仓位上限或账户适配度低，禁止继续加仓")
                flags.append("position_limit_reached")

        # -- 5b. AI policy assessment is an additional soft constraint, never
        # a Risk Gate bypass. It can downgrade add-like actions when the draft
        # target or current position exceeds AI's independently assessed max.
        if ai_status == "evaluated":
            if ai_action_bias in {"hold_no_add", "avoid", "prefer_reduce"} and final_action in ADD_LIKE_ACTIONS:
                final_action = _downgrade_to_hold_no_add(final_action, snapshot)
                reasons.append(f"AI 仓位评估动作为 {ai_action_bias}，禁止加仓")
                flags.append("ai_policy_bias_blocks_add")
            if ai_max_pct is not None and ai_max_pct > 0:
                ai_limit_hit = current_pct is not None and current_pct >= ai_max_pct
                ai_target_above = suggested_target_pct is not None and suggested_target_pct > ai_max_pct + 1e-6
                if final_action in ADD_LIKE_ACTIONS and (ai_limit_hit or ai_target_above):
                    final_action = _downgrade_to_hold_no_add(final_action, snapshot)
                    reasons.append("目标仓位超过 AI 独立评估最大仓位，已降级")
                    flags.append("ai_policy_max_position_downgrade")
                if ai_target_above:
                    flags.append("target_above_ai_policy_max")
                    constraints["suggested_target_position_pct"] = round(min(suggested_target_pct, ai_max_pct), 6)

        # -- 6. Technical trend-break level (Stage 02) gates the action directly.
        #    severe  => no add;  broken => only hold_no_add / wait / trim_on_rebound;
        #    warning => allow hold but ban chasing-add.
        trend_break_level = _get_trend_break_level(mkt)
        original_add_like = original_action in ADD_LIKE_ACTIONS
        if trend_break_level == "severe" and (final_action in ADD_LIKE_ACTIONS or original_add_like):
            if final_action in ADD_LIKE_ACTIONS:
                final_action = _downgrade_to_hold_no_add(final_action, snapshot)
            reasons.append("技术面 severe trend break，禁止加仓")
            flags.append("trend_break_severe_blocked")
        if trend_break_level == "broken" and (final_action in ADD_LIKE_ACTIONS or original_add_like):
            if final_action in ADD_LIKE_ACTIONS:
                final_action = "hold_no_add" if _is_holding(snapshot) else "wait"
            reasons.append("技术面 broken trend，禁止加仓")
            flags.append("trend_break_broken_blocked")
        if trend_break_level == "warning" and (final_action in {"add", "add_batch", "add_right_side"} or original_action in {"add", "add_batch", "add_right_side"}):
            if final_action in {"add", "add_batch", "add_right_side"}:
                if ai_supports_pullback_add and _fundamental_status_not_bad(card_pack) and _rr_allows_pullback(rr):
                    final_action = "add_on_pullback"
                else:
                    final_action = "add_on_pullback" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append("技术面 trend break warning，禁止追涨加仓")
            flags.append("trend_break_warning_downgrade")

        # -- 6b. Investment Thesis (Stage 03) gates the action directly.
        thesis = card_pack.investment_thesis or {}
        thesis_max = _safe_float(thesis.get("max_position_pct")) if isinstance(thesis, dict) else None
        thesis_risk = str(thesis.get("risk_class") or "unknown") if isinstance(thesis, dict) else "unknown"
        thesis_role = str(thesis.get("role") or "unknown") if isinstance(thesis, dict) else "unknown"

        # 6b.1 - already at/over thesis max position => hold_no_add
        if (
            final_action in ADD_LIKE_ACTIONS
            and thesis_max
            and current_pct is not None
            and thesis_max > 0
            and current_pct >= thesis_max
        ):
            final_action = "hold_no_add"
            reasons.append("已达到投资假设最大仓位，禁止继续加仓")
            flags.append("thesis_position_limit")

        # 6b.2 - extreme risk_class => no add_batch / add / add_right_side
        if thesis_risk == "extreme" and final_action in {"add", "add_batch", "add_right_side"}:
            final_action = "add_on_pullback" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append("高波动/极端标的，禁止强加仓；最多回调加仓")
            flags.append("thesis_extreme_risk_blocked")

        # 6b.3 - sell_triggers hit (textual match via thesis helper) => reduce_now / sell_thesis_broken
        try:
            from app.services.investment_thesis import evaluate_sell_triggers
            sell_triggers_hit = evaluate_sell_triggers(
                _thesis_dataclass_from_dict(thesis),
                trend_break_level=trend_break_level,
                fundamental_red=_is_fundamental_red(fund),
            )
        except Exception:
            sell_triggers_hit = []
        if sell_triggers_hit and final_action in {"hold", "watchlist", "wait", "add_on_pullback", "hold_no_add"} and _is_holding(snapshot):
            final_action = "sell_thesis_broken" if thesis_risk in {"extreme", "high_growth"} else "reduce_now"
            reasons.append(f"投资假设 sell_triggers 命中: {'; '.join(sell_triggers_hit[:2])}")
            flags.append("thesis_sell_trigger_hit")

        # 6b.4 - no_add_triggers hit => hold_no_add
        try:
            from app.services.investment_thesis import evaluate_no_add_triggers
            no_add_triggers_hit = evaluate_no_add_triggers(
                _thesis_dataclass_from_dict(thesis),
                position_pct=current_pct,
                trend_break_level=trend_break_level,
                catalyst_strength=(getattr(evt, "catalyst_strength", None) if evt else None),
            )
        except Exception:
            no_add_triggers_hit = []
        if no_add_triggers_hit and final_action in ADD_LIKE_ACTIONS:
            final_action = "hold_no_add" if _is_holding(snapshot) else "wait"
            reasons.append(f"投资假设 no_add_triggers 命中: {'; '.join(no_add_triggers_hit[:2])}")
            flags.append("thesis_no_add_trigger_hit")

        # 6b.5 - unknown thesis on a high-risk action => wait / hold_no_add
        if thesis_role == "unknown" and thesis_max is None and final_action in {"add", "add_batch", "add_right_side"}:
            final_action = "wait" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append("未配置投资假设，禁止强加仓")
            flags.append("thesis_unknown_blocked")

        # -- 6c. FundamentalChangeEngine status (Stage 04) gates the action directly.
        fundamental_status = _get_fundamental_status(fund)
        thesis_broken = bool(getattr(fund, "thesis_broken", False)) if fund else False

        # 6c.1 - red OR thesis_broken => reduce_now / sell_thesis_broken
        if (fundamental_status == "red" or thesis_broken) and _is_holding(snapshot):
            target_action = (
                "sell_thesis_broken" if thesis_broken or thesis_risk in {"extreme", "high_growth"} else "reduce_now"
            )
            if final_action in {
                "hold", "watchlist", "wait", "add_on_pullback", "hold_no_add",
                "add", "add_batch", "add_right_side", "add_small",
            }:
                final_action = target_action
            reasons.append("基本面 red 或 投资假设被破坏，已转为减仓/退出")
            flags.append("fundamental_red_action")
            if thesis_broken:
                flags.append("thesis_broken_detected")
        elif (fundamental_status == "red" or thesis_broken) and not _is_holding(snapshot):
            # Not holding yet — block entry
            if final_action in ADD_LIKE_ACTIONS:
                final_action = "wait"
                reasons.append("基本面 red，禁止建仓")
                flags.append("fundamental_red_blocked")

        # 6c.2 - orange => hold_no_add / wait
        if fundamental_status == "orange" and final_action in ADD_LIKE_ACTIONS:
            final_action = "hold_no_add" if _is_holding(snapshot) else "wait"
            reasons.append("基本面 orange，禁止加仓")
            flags.append("fundamental_orange_blocked")

        # 6c.3 - yellow => ban strong add_batch
        if fundamental_status == "yellow" and final_action in {"add", "add_batch", "add_right_side"}:
            if ai_supports_pullback_add and _rr_allows_pullback(rr):
                final_action = "add_on_pullback"
            else:
                final_action = "add_on_pullback" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append("基本面 yellow，禁止强加仓")
            flags.append("fundamental_yellow_downgrade")

        # -- 6d. RiskRewardEngine R-multiple (Stage 05) gates the action directly.
        rr_ratio = _safe_float(getattr(rr, "reward_risk_ratio", None)) if rr else None
        rr_downside = _safe_float(getattr(rr, "downside_risk_pct", None)) if rr else None
        # 6d.1 - ratio < 1.0 => reduce_now / wait
        if rr_ratio is not None and rr_ratio < 1.0 and final_action in ADD_LIKE_ACTIONS:
            if _is_holding(snapshot):
                final_action = "reduce_now"
            else:
                final_action = "wait"
            reasons.append(f"风险收益比 {rr_ratio:.2f} < 1.0，禁止加仓")
            flags.append("rr_below_one")
        # 6d.2 - ratio < 1.5 (but >= 1.0) => hold_no_add / wait
        elif rr_ratio is not None and rr_ratio < 1.5 and final_action in ADD_LIKE_ACTIONS:
            final_action = "hold_no_add" if _is_holding(snapshot) else "wait"
            reasons.append(f"风险收益比 {rr_ratio:.2f} 偏低，暂不加仓")
            flags.append("rr_below_one_five")
        # 6d.3 - very high downside risk => no add_batch
        if rr_downside is not None and rr_downside > 30 and final_action in {"add", "add_batch", "add_right_side"}:
            final_action = "add_on_pullback" if not _is_holding(snapshot) else "hold_no_add"
            reasons.append(f"下行风险 {rr_downside:.1f}% 过高，禁止强加仓")
            flags.append("rr_downside_too_high")

        # -- 7. Severe trend breakdown => suggest reduce_now / sell_thesis_broken.
        #     We do NOT override a clear "hold" or "wait" recommendation.
        severe_breakdown = _is_severe_breakdown(mkt, evt, fund)
        if severe_breakdown and final_action in {"hold", "watchlist", "wait", "add_on_pullback"} and _is_holding(snapshot):
            # The user question did not contain panic; treat this as thesis
            # broken and steer to reduce_now, but only if holding.
            final_action = "reduce_now"
            reasons.append("趋势/事件/基本面出现严重破坏，已转为减仓")
            flags.append("thesis_breakdown_detected")

        # -- 8. Suggested target above max position is a constraint error.
        if (
            max_pct is not None
            and suggested_target_pct is not None
            and max_pct > 0
            and suggested_target_pct > max_pct + 1e-6
        ):
            flags.append("target_above_max_position")
            constraints["suggested_target_position_pct"] = round(min(suggested_target_pct, max_pct), 6)

        return RiskGateResult(
            original_action=original_action,
            final_action=final_action,
            blocked=original_action != final_action and final_action in {"panic_blocked", "sell_thesis_broken"},
            downgraded=original_action != final_action,
            gate_reasons=reasons,
            required_disclosures=disclosures,
            risk_flags=flags,
            action_constraints={
                **constraints,
                "max_position_pct": max_pct,
                "snapshot": {
                    "current_position_pct": current_pct,
                    "max_position_pct": max_pct,
                    "public_fallback_count": public_fallback_count,
                    "catalyst_strength": getattr(evt, "catalyst_strength", None) if evt else None,
                    "trend_stance": getattr(mkt, "stance", None) if mkt else None,
                    "trend_break_level": trend_break_level,
                },
            },
            confidence_cap=_compute_confidence_cap(
                public_fallback_count=public_fallback_count,
                mkt=mkt,
                fund=fund,
                rr=rr,
                flags=flags,
            ),
        )

    # ------------------------------------------------------------------
    # Panic detection
    # ------------------------------------------------------------------
    def _detect_panic(
        self,
        user_question: str | None,
        decision_output: dict[str, Any],
        card_pack: TradeDecisionCardPack,
    ) -> list[str]:
        """Heuristic panic detection: returns the matched tokens if user is
        asking to dump a position while fundamentals/trend/position/risk
        do NOT support selling. Returns [] when no panic detected.
        """
        text = " ".join(
            str(x or "")
            for x in [
                user_question or "",
                decision_output.get("decision_summary") or "",
                " ".join(decision_output.get("key_reasons") or []),
            ]
        )
        if not text:
            return []
        lowered = text.lower()
        matched: list[str] = []
        for tok in PANIC_TOKENS_ZH:
            if tok in text:
                matched.append(tok)
        for tok in PANIC_TOKENS_EN:
            if tok in lowered:
                matched.append(tok)
        if not matched:
            return []

        # Only treat as a real panic dump if the user actually holds a
        # position. A "should I clear my position" question for a symbol
        # they don't own is just a hypothetical, not a panic dump.
        snapshot = card_pack.account_fact_snapshot
        if not _is_holding(snapshot):
            return []

        # Confirm fundamentals/trend/position/risk are NOT supporting a sell.
        fund = card_pack.fundamental_valuation_card
        mkt = card_pack.market_trend_card
        rr = card_pack.risk_reward_card

        fund_severe = _is_severe_breakdown_for(fund)
        mkt_severe = _is_severe_breakdown_for(mkt)
        trend_break_level = _get_trend_break_level(mkt)
        # Stage 02 - if TechnicalSignalEngine says the trend is broken or severe,
        # a "clear the position" request is justified, not panic.
        trend_severe = trend_break_level in {"broken", "severe"}
        # The old code read rr.thesis_broken but RiskRewardCard has
        # risk_reward_thesis_broken (the new field name set by
        # RiskRewardEngine.risk_reward_thesis_broken). We also read
        # fund.thesis_broken (set by FundamentalChangeEngine) so a
        # fundamental thesis break can also bypass the panic block.
        thesis_broken = (
            bool(fund and getattr(fund, "thesis_broken", False))
            or bool(rr and getattr(rr, "risk_reward_thesis_broken", False))
        )
        position_over = _position_over(card_pack)

        if fund_severe or mkt_severe or trend_severe or thesis_broken or position_over:
            # Not panic — fundamentals or risk actually justify a sell.
            return []

        # The user is asking to dump a position while nothing else supports
        # the sell — treat as panic.
        return matched[:3]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_trend_break_level(mkt: MarketTrendCard | None) -> str:
    """Resolve the trend_break_level from a MarketTrendCard.

    Falls back to "unknown" when the card is missing or the value is empty.
    """
    if not mkt:
        return "unknown"
    level = getattr(mkt, "trend_break_level", None) or "unknown"
    return str(level)


def _get_fundamental_status(fund: FundamentalValuationCard | None) -> str:
    """Resolve the fundamental_status from a FundamentalValuationCard.

    Defaults to "unknown" when the card is missing or the field is empty.
    """
    if not fund:
        return "unknown"
    level = getattr(fund, "fundamental_status", None) or "unknown"
    return str(level)


def _thesis_dataclass_from_dict(thesis: dict[str, Any] | None):
    """Build a lightweight InvestmentThesis-shaped object for the helper
    `evaluate_no_add_triggers` / `evaluate_sell_triggers` functions.

    The helpers only need role / risk_class / max_position_pct and a few
    string list fields, so we can construct a real InvestmentThesis from the
    dict the card_pack carries.
    """
    if not thesis or not isinstance(thesis, dict):
        from app.services.investment_thesis import DEFAULT_THESIS
        return DEFAULT_THESIS
    from app.services.investment_thesis import InvestmentThesis
    return InvestmentThesis(
        symbol=str(thesis.get("symbol") or ""),
        role=str(thesis.get("role") or "unknown"),
        risk_class=str(thesis.get("risk_class") or "unknown"),
        max_position_pct=float(thesis.get("max_position_pct") or 0),
        target_position_pct=thesis.get("target_position_pct"),
        core_thesis=list(thesis.get("core_thesis") or []),
        add_rules=list(thesis.get("add_rules") or []),
        hold_rules=list(thesis.get("hold_rules") or []),
        sell_triggers=list(thesis.get("sell_triggers") or []),
        no_add_triggers=list(thesis.get("no_add_triggers") or []),
        review_frequency=str(thesis.get("review_frequency") or "unknown"),
        metadata=dict(thesis.get("metadata") or {}),
    )


def _is_fundamental_red(fund: FundamentalValuationCard | None) -> bool:
    if not fund:
        return False
    if fund.stance == CardStance.BEARISH and (fund.score or 0) <= 1:
        return True
    return False


def _is_holding(snapshot: AccountFactSnapshot | None) -> bool:
    if not snapshot:
        return False
    if isinstance(snapshot, dict):
        return bool(snapshot.get("is_holding"))
    return bool(getattr(snapshot, "is_holding", False))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _ai_supports_pullback_add(ai_status: str, ai_position_stance: str | None, ai_action_bias: str | None) -> bool:
    return (
        ai_status == "evaluated"
        and ai_position_stance in {"underweight", "no_position"}
        and ai_action_bias in {"allow_add", "prefer_pullback_add"}
    )


def _fundamental_status_not_bad(card_pack: TradeDecisionCardPack) -> bool:
    status = _get_fundamental_status(card_pack.fundamental_valuation_card)
    return status not in {"red", "orange"}


def _rr_allows_pullback(rr: RiskRewardCard | None) -> bool:
    ratio = _safe_float(getattr(rr, "reward_risk_ratio", None)) if rr else None
    return ratio is None or ratio >= 1.5


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _downgrade_to_hold_no_add(original_action: str, snapshot: AccountFactSnapshot) -> str:
    """Pick a non-add action that still reflects the current state."""
    if _is_holding(snapshot):
        return "hold_no_add"
    return "wait"


def _count_public_fallback(card_pack: TradeDecisionCardPack) -> int:
    count = 0
    for card in (
        card_pack.market_trend_card,
        card_pack.fundamental_valuation_card,
        card_pack.event_catalyst_card,
    ):
        if card is None:
            count += 1
            continue
        if isinstance(card, BaseTradeDecisionCard):
            if card.stance == CardStance.INSUFFICIENT_DATA:
                count += 1
            elif card.evidence_quality == "low" and card.score <= 1:
                count += 1
    return count


def _low_quality_evidence(card: BaseTradeDecisionCard | None) -> bool:
    if not card:
        return True
    if card.stance == CardStance.INSUFFICIENT_DATA:
        return True
    if card.evidence_quality == "low" and card.score <= 1:
        return True
    return False


def _is_weak_catalyst(evt: EventCatalystCard | None) -> bool:
    if not evt:
        return True
    if evt.catalyst_strength in ("weak", "no_catalyst"):
        return True
    if evt.score is not None and evt.score <= 1:
        return True
    if not evt.key_events and (evt.recent_news_count or 0) <= 1:
        return True
    return False


def _is_severe_breakdown(
    mkt: MarketTrendCard | None,
    evt: EventCatalystCard | None,
    fund: FundamentalValuationCard | None,
) -> bool:
    if mkt and mkt.stance == CardStance.BEARISH and mkt.score is not None and mkt.score <= 1:
        return True
    if fund and fund.stance == CardStance.BEARISH and fund.score is not None and fund.score <= 1:
        return True
    if evt and evt.catalyst_strength == "weak" and evt.sentiment == "negative" and (evt.score or 0) <= 1:
        return True
    return False


def _is_severe_breakdown_for(card: BaseTradeDecisionCard | None) -> bool:
    if not card:
        return False
    return card.stance == CardStance.BEARISH and (card.score or 0) <= 1


def _position_over(card_pack: TradeDecisionCardPack) -> bool:
    snapshot = card_pack.account_fact_snapshot
    if not snapshot:
        return False
    if isinstance(snapshot, dict):
        position_pct = snapshot.get("position_pct")
    else:
        position_pct = getattr(snapshot, "position_pct", None)
    if position_pct is None:
        return False
    try:
        return float(position_pct) > 0.5
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Application helper
# ---------------------------------------------------------------------------

def apply_risk_gate(
    decision_output: dict[str, Any],
    card_pack: TradeDecisionCardPack,
    user_question: str | None = None,
) -> tuple[dict[str, Any], RiskGateResult]:
    """Run the gate, return (mutated decision_output, gate_result).

    The decision_output dict is updated in place:
      - action may be downgraded
      - risk_gate block is attached
      - data_limitations and review_warnings gain the gate's reasons
      - confidence is clamped to risk_gate.confidence_cap (P2)
    """
    gate = RiskGate()
    result = gate.evaluate(decision_output, card_pack, user_question=user_question)
    decision_output["action"] = result.final_action
    decision_output["risk_gate"] = result.to_dict()

    # Accumulate gate reasons into data_limitations / review_warnings
    if result.gate_reasons:
        dl = list(decision_output.get("data_limitations") or [])
        for reason in result.gate_reasons:
            if reason and reason not in dl:
                dl.append(reason)
        decision_output["data_limitations"] = dl

    if result.risk_flags:
        rw = list(decision_output.get("review_warnings") or [])
        for flag in result.risk_flags:
            label = f"risk_gate:{flag}"
            if label not in rw:
                rw.append(label)
        decision_output["review_warnings"] = rw

    if result.required_disclosures:
        existing = decision_output.get("required_disclosures")
        if not isinstance(existing, list):
            existing = []
        for d in result.required_disclosures:
            if d and d not in existing:
                existing.append(d)
        decision_output["required_disclosures"] = existing

    # P2 - actually downgrade confidence. Never raise.
    if result.confidence_cap:
        current = decision_output.get("confidence")
        new_conf = _clamp_confidence(current, result.confidence_cap)
        if new_conf != current:
            decision_output["confidence"] = new_conf

    return decision_output, result


def _compute_confidence_cap(
    *,
    public_fallback_count: int,
    mkt: MarketTrendCard | None,
    fund: FundamentalValuationCard | None,
    rr: RiskRewardCard | None,
    flags: list[str],
) -> str | None:
    """Return the most conservative confidence cap implied by the inputs.

    P2 rules:
      - insufficient_data flag => cap at medium
      - public_fallback_count >= 3 => low
      - weak_catalyst_downgrade => medium
      - trend_break_level=unknown AND mkt evidence_quality=low => medium
      - fundamental_status=unknown AND fund evidence_quality=low => medium
      - any panic/red action flag => low
    """
    flags_set = set(flags or [])

    # Red / panic always downgrades to low
    if flags_set & {
        "panic_sell_blocked",
        "fundamental_red_action",
        "fundamental_red_blocked",
        "thesis_broken_detected",
    }:
        return "low"

    # Three or more public-data fallbacks
    if public_fallback_count >= 3:
        return "low"

    if "weak_catalyst_downgrade" in flags_set:
        return "medium"

    # Insufficient data flag (set by the engine when public_fallback_count>=2)
    if "insufficient_data" in flags_set:
        return "medium"

    # Trend / fundamental evidence quality is low AND status unknown
    mkt_quality = getattr(mkt, "evidence_quality", None) if mkt else None
    fund_quality = getattr(fund, "evidence_quality", None) if fund else None
    if mkt and mkt_quality == "low" and getattr(mkt, "trend_break_level", "unknown") == "unknown":
        return "medium"
    if fund and fund_quality == "low" and getattr(fund, "fundamental_status", "unknown") == "unknown":
        return "medium"

    return None


def make_fail_safe_result(
    original_action: str,
    snapshot: AccountFactSnapshot | None,
    error: str,
) -> RiskGateResult:
    """Build a fail-safe RiskGateResult for use when the gate itself raises.

    The composer catches the exception, builds this result, and applies
    conservative defaults to decision_output.
    """
    final = "hold_no_add" if (snapshot is not None and _is_holding(snapshot)) else "wait"
    return RiskGateResult(
        original_action=original_action,
        final_action=final,
        blocked=False,
        downgraded=original_action != final,
        gate_reasons=[
            "RiskGate 执行失败，已按保守策略降级",
        ],
        required_disclosures=[
            f"RiskGate 内部错误: {error[:120]}",
        ],
        risk_flags=["risk_gate_failed"],
        action_constraints={
            "snapshot": {
                "current_position_pct": getattr(snapshot, "position_pct", None) if snapshot else None,
                "max_position_pct": None,
                "public_fallback_count": None,
            },
            "fail_safe": True,
        },
        confidence_cap="low",
        failed=True,
        error=error,
    )


__all__ = [
    "RiskGate",
    "RiskGateResult",
    "apply_risk_gate",
    "make_fail_safe_result",
    "RISK_GATE_ACTIONS",
    "ADD_LIKE_ACTIONS",
    "STRONG_ADD_ACTIONS",
    "HOLD_LIKE_ACTIONS",
    "EXIT_LIKE_ACTIONS",
]
