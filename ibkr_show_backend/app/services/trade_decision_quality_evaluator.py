"""Deterministic quality evaluator for trade decision documents.

This evaluator is deliberately read-only: it does not call LLMs, tools,
repositories, or services, and it never mutates the decision output.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


QUALITY_VERSION = "trade_decision_quality_v1"

EXPECTED_GRAPH_NODES = [
    "build_account_facts",
    "load_user_investment_policy",
    "account_fit",
    "market_trend",
    "fundamental_valuation",
    "event_catalyst",
    "market_event_context",
    "build_card_pack",
    "ai_policy_assessment",
    "bull_thesis",
    "bear_thesis",
    "bull_rebuttal",
    "bear_rebuttal",
    "debate_judge",
    "trade_plan",
    "compose_decision",
    "persist_decision",
]
CORE_GRAPH_NODES = {
    "build_account_facts",
    "load_user_investment_policy",
    "build_card_pack",
    "ai_policy_assessment",
    "debate_judge",
    "trade_plan",
    "compose_decision",
    "persist_decision",
}
TOOL_FREE_LLM_NODES = {
    "bull_thesis",
    "bear_thesis",
    "bull_rebuttal",
    "bear_rebuttal",
    "debate_judge",
    "trade_plan",
    "ai_policy_assessment",
}
VALID_NODE_STATUSES = {"success", "completed", "fallback", "failed"}
ADD_LIKE_ACTIONS = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
AGGRESSIVE_ADD_ACTIONS = {"add", "add_batch", "add_right_side"}
REDUCE_LIKE_ACTIONS = {"reduce", "reduce_batch", "reduce_now", "trim_on_rebound"}
SELL_LIKE_ACTIONS = {"sell", "sell_thesis_broken"}
CONSERVATIVE_ACTIONS = {"hold", "hold_no_add", "wait", "watchlist", "avoid", "panic_blocked"}


class TradeDecisionQualityEvaluator:
    def evaluate(self, document: dict) -> dict:
        doc = deepcopy(document or {})
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        checks: dict[str, dict] = {}

        for name, check_fn in (
            ("graph_integrity", self._check_graph_integrity),
            ("data_source_integrity", self._check_data_source_integrity),
            ("structured_output_health", self._check_structured_output_health),
            ("asset_action_consistency", self._check_asset_action_consistency),
            ("position_consistency", self._check_position_consistency),
            ("risk_gate_integrity", self._check_risk_gate_integrity),
            ("ai_policy_assessment_integrity", self._check_ai_policy_assessment_integrity),
            ("action_calibration_integrity", self._check_action_calibration_integrity),
            ("risk_reward_source_integrity", self._check_risk_reward_source_integrity),
            ("evidence_card_completeness", self._check_evidence_card_completeness),
            ("output_contract_integrity", self._check_output_contract_integrity),
        ):
            result = check_fn(doc)
            checks[name] = result
            hard_failures.extend(result.get("hard_failures") or [])
            warnings.extend(result.get("warnings") or [])
            flags.extend(result.get("flags") or [])

        score = self._score(checks, hard_failures, warnings)
        level = self._level(score)
        passed = not hard_failures and score >= 55

        return {
            "version": QUALITY_VERSION,
            "score": score,
            "level": level,
            "passed": passed,
            "hard_failures": _dedupe(hard_failures),
            "warnings": _dedupe(warnings),
            "flags": _dedupe(flags),
            "checks": checks,
            "summary": self._summary(hard_failures, warnings),
            "fallback_used": False,
            "fallback_reason": None,
        }

    def _check_graph_integrity(self, doc: dict) -> dict:
        traces = _run_trace(doc)
        node_names = [str(item.get("node_name") or "") for item in traces if item.get("node_name")]
        missing_nodes = [name for name in EXPECTED_GRAPH_NODES if name not in node_names]
        unexpected_nodes = [name for name in node_names if name == "risk_reward"]
        failed_nodes = [str(item.get("node_name")) for item in traces if item.get("status") == "failed"]
        fallback_nodes = [str(item.get("node_name")) for item in traces if item.get("fallback_used") or item.get("status") == "fallback"]
        invalid_status_nodes = [
            str(item.get("node_name"))
            for item in traces
            if item.get("status") and str(item.get("status")) not in VALID_NODE_STATUSES
        ]
        hard_failures = []
        warnings = []
        flags = []
        for name in missing_nodes:
            if name in CORE_GRAPH_NODES:
                hard_failures.append(f"core_graph_node_missing:{name}")
                flags.append("core_graph_node_missing")
            else:
                warnings.append(f"graph_node_missing:{name}")
        if unexpected_nodes:
            hard_failures.append("standalone risk_reward node appeared in run_trace")
            flags.append("unexpected_risk_reward_node")
        for name in failed_nodes:
            warnings.append(f"graph_node_failed:{name}")
        for name in invalid_status_nodes:
            warnings.append(f"graph_node_invalid_status:{name}")
        return {
            "passed": not hard_failures,
            "missing_nodes": missing_nodes,
            "unexpected_nodes": unexpected_nodes,
            "failed_nodes": failed_nodes,
            "fallback_nodes": fallback_nodes,
            "node_count": len(node_names),
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_data_source_integrity(self, doc: dict) -> dict:
        metadata = _dict(doc.get("metadata"))
        violations: list[str] = []
        hard_failures: list[str] = []
        flags: list[str] = []
        for key in ("account_data_source", "trade_data_source", "position_data_source"):
            value = metadata.get(key)
            if value != "IBKR_ONLY":
                issue = f"{key}_not_ibkr_only:{value}"
                violations.append(issue)
                hard_failures.append(issue)
                flags.append("private_data_source_violation")
        for item in _run_trace(doc):
            node = str(item.get("node_name") or "")
            tools = item.get("tools_called") or []
            if node in TOOL_FREE_LLM_NODES and tools:
                issue = f"tool_free_node_called_tools:{node}"
                violations.append(issue)
                hard_failures.append(issue)
                flags.append("tool_free_llm_node_called_tool")
        return {
            "passed": not hard_failures,
            "account_data_source": metadata.get("account_data_source"),
            "trade_data_source": metadata.get("trade_data_source"),
            "position_data_source": metadata.get("position_data_source"),
            "public_market_data_source": metadata.get("public_market_data_source"),
            "tool_free_llm_nodes_ok": not any("tool_free_node" in v for v in violations),
            "violations": violations,
            "hard_failures": hard_failures,
            "warnings": [],
            "flags": flags,
        }

    def _check_structured_output_health(self, doc: dict) -> dict:
        structured = []
        fallback_nodes = []
        for item in _run_trace(doc):
            if item.get("structured_output") is not None:
                structured.append(_dict(item.get("structured_output")))
            if item.get("fallback_used") or item.get("status") == "fallback":
                fallback_nodes.append(str(item.get("node_name") or ""))
        repaired_count = sum(1 for item in structured if item.get("repaired"))
        repair_attempts_total = sum(int(item.get("repair_attempts") or 0) for item in structured)
        failed_count = sum(1 for item in structured if item.get("ok") is False)
        debate_fallback_count = sum(1 for name in fallback_nodes if name in {"bull_thesis", "bear_thesis", "bull_rebuttal", "bear_rebuttal", "debate_judge"})
        trade_plan_fallback = "trade_plan" in fallback_nodes
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        action = str(doc.get("action") or "")
        if repaired_count:
            warnings.append(f"structured_output_repaired_count:{repaired_count}")
            flags.append("structured_output_repaired")
        if failed_count:
            warnings.append(f"structured_output_failed_count:{failed_count}")
            flags.append("structured_output_failed")
        if debate_fallback_count:
            warnings.append(f"debate_fallback_count:{debate_fallback_count}")
            flags.append("debate_fallback")
            if doc.get("confidence") != "low" and "debate_judge" in fallback_nodes:
                hard_failures.append("debate_judge_fallback_without_low_confidence")
                flags.append("debate_judge_fallback_confidence_not_low")
        if trade_plan_fallback:
            warnings.append("trade_plan_fallback")
            flags.append("trade_plan_fallback")
            if action in {"add", "add_batch", "add_right_side"}:
                hard_failures.append("trade_plan_fallback_aggressive_action")
                flags.append("trade_plan_fallback_aggressive_action")
        return {
            "passed": not hard_failures,
            "structured_output_count": len(structured),
            "repaired_count": repaired_count,
            "repair_attempts_total": repair_attempts_total,
            "structured_output_failed_count": failed_count,
            "fallback_count": len(fallback_nodes),
            "debate_fallback_count": debate_fallback_count,
            "trade_plan_fallback": trade_plan_fallback,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_asset_action_consistency(self, doc: dict) -> dict:
        debate = _dict(doc.get("asset_debate")) or _dict(_card_pack(doc).get("debate_judge_card"))
        trade_plan = _dict(doc.get("trade_plan")) or _dict(_card_pack(doc).get("trade_plan_card"))
        risk_gate = _dict(doc.get("risk_gate"))
        action = str(doc.get("action") or "")
        stance = str(debate.get("asset_stance") or "")
        plan_action = str(trade_plan.get("portfolio_action") or "")
        reason_type = str(trade_plan.get("action_reason_type") or "")
        is_holding = _is_holding(doc)
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        if stance == "insufficient_data" and action in ADD_LIKE_ACTIONS:
            hard_failures.append("insufficient_data_add_like")
            flags.append("insufficient_data_add_like")
        if stance == "bearish" and not is_holding and action in ADD_LIKE_ACTIONS | REDUCE_LIKE_ACTIONS | SELL_LIKE_ACTIONS:
            hard_failures.append("bearish_no_position_invalid_action")
            flags.append("bearish_no_position_invalid_action")
        if stance == "bearish" and is_holding and action in ADD_LIKE_ACTIONS:
            hard_failures.append("bearish_holding_add_like")
            flags.append("bearish_holding_add_like")
        if stance == "bullish" and action in {"sell", "sell_thesis_broken"} and not risk_gate.get("gate_reasons"):
            warnings.append("bullish_sell_without_risk_gate_reason")
            flags.append("bullish_sell_without_reason")
        if stance == "neutral" and action in {"add_batch", "add_right_side"}:
            warnings.append("neutral_aggressive_add")
            flags.append("neutral_aggressive_add")
        if plan_action and plan_action != action:
            final_action = risk_gate.get("final_action")
            if not risk_gate.get("downgraded") and final_action != action:
                warnings.append("trade_plan_action_differs_without_risk_gate_explanation")
                flags.append("trade_plan_final_action_unexplained")
        if reason_type == "portfolio_risk_constraint" and action in ADD_LIKE_ACTIONS:
            warnings.append("portfolio_risk_constraint_with_add_like_action")
            flags.append("portfolio_risk_constraint_add_like")
        if reason_type == "insufficient_data" and action in ADD_LIKE_ACTIONS:
            hard_failures.append("insufficient_data_reason_add_like")
            flags.append("insufficient_data_reason_add_like")
        return {
            "passed": not hard_failures,
            "asset_stance": stance,
            "action": action,
            "trade_plan_action": plan_action,
            "action_reason_type": reason_type,
            "is_holding": is_holding,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_position_consistency(self, doc: dict) -> dict:
        advice = _dict(doc.get("position_advice"))
        action = str(doc.get("action") or "")
        current = _float(advice.get("current_position_pct"))
        target = _float(advice.get("suggested_target_position_pct"))
        max_pct = _float(advice.get("max_position_pct"))
        cash = _float(advice.get("suggested_cash_amount"))
        is_holding = _is_holding(doc)
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        for name, value in (("current_position_pct", current), ("target_position_pct", target), ("max_position_pct", max_pct), ("suggested_cash_amount", cash)):
            if value is not None and value < 0:
                hard_failures.append(f"negative_{name}")
                flags.append("negative_position_value")
        if target is not None and max_pct is not None and max_pct > 0 and target > max_pct + 1e-6:
            warnings.append("target_position_pct_exceeds_max_position_pct")
            flags.append("target_exceeds_max_position")
        if action in ADD_LIKE_ACTIONS and current is not None and target is not None and target <= current:
            warnings.append("add_like_action_without_target_increase")
            flags.append("add_target_not_above_current")
        if action in REDUCE_LIKE_ACTIONS and current is not None and target is not None and target >= current:
            warnings.append("reduce_like_action_without_target_decrease")
            flags.append("reduce_target_not_below_current")
        if action in SELL_LIKE_ACTIONS and target is not None and target > 0.001:
            warnings.append("sell_action_target_not_zero")
            flags.append("sell_target_not_zero")
        if not is_holding and action in REDUCE_LIKE_ACTIONS | SELL_LIKE_ACTIONS:
            hard_failures.append("no_position_sell_or_reduce")
            flags.append("no_position_sell_or_reduce")
        if not is_holding and action in {"watchlist", "avoid"} and target is not None and target > 0.001:
            warnings.append("watchlist_or_avoid_nonzero_target")
            flags.append("passive_nonzero_target")
        adjustment = target - current if target is not None and current is not None else None
        return {
            "passed": not hard_failures and not any(flag == "target_exceeds_max_position" for flag in flags),
            "current_position_pct": current,
            "target_position_pct": target,
            "max_position_pct": max_pct,
            "suggested_cash_amount": cash,
            "adjustment_pct": adjustment,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_risk_gate_integrity(self, doc: dict) -> dict:
        risk_gate = _dict(doc.get("risk_gate"))
        action = str(doc.get("action") or "")
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        if not risk_gate:
            return {
                "passed": False,
                "hard_failures": ["risk_gate_missing"],
                "warnings": [],
                "flags": ["risk_gate_missing"],
            }
        original = risk_gate.get("original_action")
        final = risk_gate.get("final_action")
        if not original:
            warnings.append("risk_gate_original_action_missing")
            flags.append("risk_gate_original_action_missing")
        if final != action:
            hard_failures.append("risk_gate_final_action_mismatch")
            flags.append("risk_gate_final_action_mismatch")
        if original and final and original != final and not risk_gate.get("downgraded"):
            warnings.append("risk_gate_downgraded_false_after_action_change")
            flags.append("risk_gate_downgrade_flag_missing")
        if risk_gate.get("blocked") and action not in CONSERVATIVE_ACTIONS:
            warnings.append("risk_gate_blocked_but_action_not_conservative")
            flags.append("risk_gate_blocked_nonconservative")
        gate_reasons = _list(risk_gate.get("gate_reasons"))
        visible = " ".join(_list(doc.get("data_limitations")) + _list(doc.get("review_warnings")))
        if gate_reasons and not any(reason in visible for reason in gate_reasons):
            warnings.append("risk_gate_reasons_not_surfaced")
            flags.append("risk_gate_reasons_not_surfaced")
        constraints = _dict(risk_gate.get("action_constraints"))
        if action in ADD_LIKE_ACTIONS and constraints.get("max_position_pct") is None:
            warnings.append("add_like_action_missing_risk_gate_max_position_pct")
            flags.append("risk_gate_missing_max_position")
        return {
            "passed": not hard_failures,
            "original_action": original,
            "final_action": final,
            "downgraded": bool(risk_gate.get("downgraded")),
            "blocked": bool(risk_gate.get("blocked")),
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_ai_policy_assessment_integrity(self, doc: dict) -> dict:
        assessment = _dict(doc.get("ai_policy_assessment")) or _dict(_card_pack(doc).get("ai_policy_assessment"))
        action = str(doc.get("action") or "")
        advice = _dict(doc.get("position_advice"))
        target = _float(advice.get("suggested_target_position_pct"))
        user_summary = _dict(doc.get("user_investment_policy_summary"))
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        if not assessment:
            hard_failures.append("ai_policy_assessment_missing")
            flags.append("ai_policy_assessment_missing")
            return {
                "passed": False,
                "status": None,
                "hard_failures": hard_failures,
                "warnings": warnings,
                "flags": flags,
            }
        status = str(assessment.get("status") or "")
        if status == "evaluated":
            required = [
                "ai_assessed_asset_role",
                "ai_role_confidence",
                "ai_recommended_target_position_pct",
                "ai_recommended_max_position_pct",
                "ai_position_stance",
                "challenge_level",
                "recommended_action_bias",
            ]
            missing = [key for key in required if assessment.get(key) in (None, "")]
            if missing:
                hard_failures.extend(f"ai_policy_field_missing:{key}" for key in missing)
                flags.append("ai_policy_evaluated_missing_fields")
            min_pct = _float(assessment.get("ai_recommended_min_position_pct"))
            ai_target = _float(assessment.get("ai_recommended_target_position_pct"))
            ai_max = _float(assessment.get("ai_recommended_max_position_pct"))
            if min_pct is not None and ai_target is not None and ai_max is not None and not (min_pct <= ai_target <= ai_max):
                hard_failures.append("ai_policy_position_order_invalid")
                flags.append("ai_policy_position_order_invalid")
            target_range = assessment.get("ai_recommended_target_position_range_pct")
            if isinstance(target_range, list) and len(target_range) == 2:
                low = _float(target_range[0])
                high = _float(target_range[1])
                if low is not None and high is not None and low > high:
                    hard_failures.append("ai_policy_target_range_invalid")
                    flags.append("ai_policy_target_range_invalid")
            if action in ADD_LIKE_ACTIONS and ai_max is not None and target is not None and target > ai_max + 1e-6:
                hard_failures.append("add_like_target_above_ai_policy_max")
                flags.append("add_like_over_ai_max")
            if user_summary and not assessment.get("prompt_key"):
                warnings.append("ai_policy_prompt_key_missing")
                flags.append("ai_policy_prompt_metadata_missing")
        elif status == "fallback":
            warnings.append("ai_policy_assessment_fallback")
            flags.append("ai_policy_fallback")
            challenge = str(assessment.get("challenge_level") or "")
            if challenge not in {"not_evaluated", "risk_warning"}:
                hard_failures.append("ai_policy_fallback_invalid_challenge_level")
                flags.append("ai_policy_fallback_invalid")
        elif status != "not_evaluated":
            warnings.append(f"ai_policy_unknown_status:{status}")
            flags.append("ai_policy_unknown_status")
        if action in ADD_LIKE_ACTIONS and not assessment.get("ai_recommended_max_position_pct") and user_summary.get("user_preferred_max_position_pct"):
            warnings.append("add_like_action_without_ai_policy_max_while_user_preference_present")
            flags.append("trade_plan_may_be_using_user_preference_without_ai_assessment")
        return {
            "passed": not hard_failures,
            "status": status,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_action_calibration_integrity(self, doc: dict) -> dict:
        action = str(doc.get("final_action") or doc.get("action") or "")
        draft_action = str(doc.get("draft_action") or _dict(doc.get("trade_plan")).get("portfolio_action") or "")
        risk_gate = _dict(doc.get("risk_gate"))
        gate_reasons = _list(risk_gate.get("gate_reasons"))
        risk_flags = set(_list(risk_gate.get("risk_flags")))
        trade_plan = _dict(doc.get("trade_plan"))
        sanitization_notes = _list(_dict(trade_plan.get("risk_reward_assessment")).get("sanitization_notes"))
        assessment = _dict(doc.get("ai_policy_assessment"))
        pack = _card_pack(doc)
        fund = _dict(pack.get("fundamental_valuation_card"))
        mkt = _dict(pack.get("market_trend_card"))
        fundamental_status = str(fund.get("fundamental_status") or "")
        trend_break = str(mkt.get("trend_break_level") or "")
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []

        if action in ADD_LIKE_ACTIONS and fundamental_status == "red":
            hard_failures.append("add_like_with_fundamental_red")
            flags.append("hard_risk_add_like")
        if action in ADD_LIKE_ACTIONS and trend_break == "severe":
            hard_failures.append("add_like_with_trend_break_severe")
            flags.append("hard_risk_add_like")

        ai_supports_add = (
            assessment.get("status") == "evaluated"
            and assessment.get("ai_position_stance") == "underweight"
            and assessment.get("recommended_action_bias") in {"allow_add", "prefer_pullback_add"}
        )
        has_hard_block = bool(risk_gate.get("blocked")) or bool(risk_flags & {
            "insufficient_data",
            "fundamental_red_action",
            "fundamental_red_blocked",
            "trend_break_severe_blocked",
            "trend_break_broken_blocked",
            "rr_below_one",
            "missing_position_limit",
            "position_limit_reached",
            "panic_sell_blocked",
            "target_above_ai_policy_max",
            "ai_policy_max_position_downgrade",
        })
        if ai_supports_add and not has_hard_block and action in CONSERVATIVE_ACTIONS:
            warnings.append("ai_underweight_allow_add_but_final_hold_like")
            flags.append("over_conservative_hold_like")
        if action in {"hold_no_add", "wait"} and not gate_reasons and not sanitization_notes:
            warnings.append("hold_like_without_clear_blocking_reason")
            flags.append("hold_like_without_clear_block")
        soft_only = risk_flags and risk_flags <= {"weak_catalyst_downgrade", "weak_catalyst_soft_warning", "weak_catalyst_downgrade_to_pullback"}
        if draft_action in ADD_LIKE_ACTIONS and action in CONSERVATIVE_ACTIONS and soft_only and assessment.get("recommended_action_bias") == "prefer_pullback_add":
            warnings.append("soft_risk_over_downgraded_add")
            flags.append("soft_risk_over_downgraded_add")
        return {
            "passed": not hard_failures,
            "draft_action": draft_action,
            "final_action": action,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_risk_reward_source_integrity(self, doc: dict) -> dict:
        metadata_rr = _dict(_dict(doc.get("metadata")).get("risk_reward"))
        card = _dict(_card_pack(doc).get("risk_reward_card"))
        card_limitations = _list(card.get("data_limitations"))
        node_names = [str(item.get("node_name") or "") for item in _run_trace(doc)]
        hard_failures: list[str] = []
        warnings: list[str] = []
        flags: list[str] = []
        if metadata_rr.get("source") != "trade_plan":
            hard_failures.append("risk_reward_source_not_trade_plan")
            flags.append("risk_reward_source_invalid")
        if metadata_rr.get("standalone_node_enabled") is not False:
            hard_failures.append("risk_reward_standalone_node_enabled")
            flags.append("risk_reward_standalone_enabled")
        if "risk_reward" in node_names:
            hard_failures.append("standalone risk_reward node appeared in run_trace")
            flags.append("unexpected_risk_reward_node")
        if not card:
            warnings.append("risk_reward_card_missing")
            flags.append("risk_reward_card_missing")
        elif "risk_reward_derived_from_trade_plan" not in card_limitations:
            warnings.append("risk_reward_card_missing_derived_marker")
            flags.append("risk_reward_card_missing_derived_marker")
        return {
            "passed": not hard_failures,
            "source": metadata_rr.get("source"),
            "standalone_node_enabled": metadata_rr.get("standalone_node_enabled"),
            "compat_card_present": bool(card),
            "hard_failures": hard_failures,
            "warnings": warnings,
            "flags": flags,
        }

    def _check_evidence_card_completeness(self, doc: dict) -> dict:
        pack = _card_pack(doc)
        required = [
            "account_fact_snapshot",
            "account_fit_card",
            "market_trend_card",
            "fundamental_valuation_card",
            "event_catalyst_card",
            "market_event_context_card",
            "bull_thesis_card",
            "bear_thesis_card",
            "bull_rebuttal_card",
            "bear_rebuttal_card",
            "debate_judge_card",
            "trade_plan_card",
            "risk_reward_card",
        ]
        missing = [key for key in required if not pack.get(key)]
        hard = [f"evidence_card_missing:{key}" for key in missing if key in {"account_fact_snapshot", "debate_judge_card", "trade_plan_card"}]
        warnings = [f"evidence_card_missing:{key}" for key in missing if key not in {"account_fact_snapshot", "debate_judge_card", "trade_plan_card"}]
        return {
            "passed": not hard,
            "missing_cards": missing,
            "hard_failures": hard,
            "warnings": warnings,
            "flags": ["evidence_card_missing"] if missing else [],
        }

    def _check_output_contract_integrity(self, doc: dict) -> dict:
        required = [
            "overall_score",
            "rating",
            "action",
            "draft_action",
            "risk_adjusted_action",
            "final_action",
            "action_downgrade_chain",
            "confidence",
            "decision_summary",
            "score_detail",
            "position_advice",
            "execution_plan",
            "key_reasons",
            "major_risks",
            "data_limitations",
            "evidence_used",
            "card_pack",
            "run_trace",
            "metadata",
            "asset_debate",
            "trade_plan",
            "risk_gate",
            "user_investment_policy_summary",
            "ai_policy_assessment",
        ]
        missing = [key for key in required if key not in doc]
        return {
            "passed": not missing,
            "missing_fields": missing,
            "hard_failures": [f"output_field_missing:{key}" for key in missing],
            "warnings": [],
            "flags": ["output_contract_missing_fields"] if missing else [],
        }

    def _score(self, checks: dict[str, dict], hard_failures: list[str], warnings: list[str]) -> int:
        score = 100
        score -= min(100, len(_dedupe(hard_failures)) * 15)
        score -= len(_dedupe(warnings)) * 4
        graph = checks.get("graph_integrity") or {}
        for node in graph.get("fallback_nodes") or []:
            score -= 1 if node == "market_event_context" else 2
        structured = checks.get("structured_output_health") or {}
        score -= min(5, int(structured.get("repaired_count") or 0))
        score -= int(structured.get("debate_fallback_count") or 0) * 5
        if structured.get("trade_plan_fallback"):
            score -= 10
        return max(0, min(100, int(score)))

    def _level(self, score: int) -> str:
        if score >= 90:
            return "excellent"
        if score >= 75:
            return "good"
        if score >= 55:
            return "warning"
        return "poor"

    def _summary(self, hard_failures: list[str], warnings: list[str]) -> str:
        if hard_failures:
            return f"决策结果存在 {len(_dedupe(hard_failures))} 个硬性一致性问题，需要排查。"
        if warnings:
            return f"决策链路可用，但存在 {len(_dedupe(warnings))} 个警告，建议回放检查。"
        return "决策链路完整，质量检查通过。"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_trace(doc: dict) -> list[dict]:
    trace = doc.get("run_trace")
    return trace if isinstance(trace, list) else []


def _card_pack(doc: dict) -> dict:
    return _dict(doc.get("card_pack"))


def _is_holding(doc: dict) -> bool:
    snapshot = _dict(_card_pack(doc).get("account_fact_snapshot"))
    if "is_holding" in snapshot:
        return bool(snapshot.get("is_holding"))
    position_context = _dict(snapshot.get("position_context"))
    if "is_holding" in position_context:
        return bool(position_context.get("is_holding"))
    current = _float(_dict(doc.get("position_advice")).get("current_position_pct"))
    return bool(current and current > 0)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out
