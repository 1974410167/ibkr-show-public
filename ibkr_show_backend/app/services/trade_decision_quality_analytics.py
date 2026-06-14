from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


LEVEL_KEYS = ("excellent", "good", "warning", "poor", "unknown")
ADD_LIKE_ACTIONS = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
REDUCE_LIKE_ACTIONS = {"reduce", "reduce_batch", "reduce_now", "trim_on_rebound", "sell", "sell_thesis_broken"}
HOLD_LIKE_ACTIONS = {"hold", "hold_no_add", "wait", "watchlist", "avoid", "panic_blocked"}


class TradeDecisionQualityAnalyticsService:
    def summarize(self, documents: list[dict]) -> dict:
        try:
            return self._summarize(documents)
        except Exception as exc:
            summary = _empty_summary()
            summary["data_limitations"].append(f"quality_analytics_failed:{type(exc).__name__}")
            return summary

    def _summarize(self, documents: list[dict]) -> dict:
        docs = [item for item in documents if isinstance(item, dict)]
        summary = _empty_summary()
        summary["total_count"] = len(docs)
        if not docs:
            summary["data_limitations"].append("no_trade_decision_documents")
            return summary

        scores: list[float] = []
        hard_failures: Counter[str] = Counter()
        warnings: Counter[str] = Counter()
        flags: Counter[str] = Counter()
        risk_flags: Counter[str] = Counter()
        fallback_nodes: Counter[str] = Counter()
        mismatch_pairs: Counter[str] = Counter()
        evaluated_docs: list[dict] = []

        risk_downgraded_count = 0
        risk_blocked_count = 0
        fallback_count = 0
        repair_count = 0
        failed_count = 0
        mismatch_count = 0
        comparable_action_count = 0
        ai_policy_evaluated_count = 0
        ai_policy_fallback_count = 0
        ai_policy_role_comparable_count = 0
        ai_policy_role_agree_count = 0
        ai_policy_target_gaps: list[float] = []
        ai_policy_challenges: Counter[str] = Counter()
        ai_policy_add_over_max_count = 0
        action_distribution: Counter[str] = Counter()
        final_action_distribution: Counter[str] = Counter()
        draft_action_distribution: Counter[str] = Counter()
        downgrade_reasons: Counter[str] = Counter()
        sanitization_reasons: Counter[str] = Counter()
        add_like_count = 0
        reduce_like_count = 0
        hold_like_count = 0
        actionable_count = 0
        hold_no_add_count = 0
        wait_count = 0
        watchlist_count = 0
        draft_to_final_downgrade_count = 0
        draft_final_comparable_count = 0
        trade_plan_sanitized_count = 0
        public_fallback_hold_count = 0
        public_fallback_count = 0
        ai_bias_consistent_count = 0
        ai_bias_comparable_count = 0
        ai_underweight_but_hold_count = 0
        ai_allow_add_but_hold_count = 0
        ai_prefer_pullback_add_but_wait_count = 0

        for doc in docs:
            quality = _dict(doc.get("decision_quality")) or _dict(_dict(doc.get("metadata")).get("decision_quality"))
            score = quality.get("score")
            is_evaluated = isinstance(score, (int, float)) and not isinstance(score, bool)
            if is_evaluated:
                evaluated_docs.append(doc)
                scores.append(float(score))
                summary["evaluated_count"] += 1
                passed = quality.get("passed")
                if passed is True:
                    summary["pass_count"] += 1
                elif passed is False:
                    summary["fail_count"] += 1

                level = str(quality.get("level") or "unknown")
                if level not in summary["level_distribution"]:
                    level = "unknown"
                summary["level_distribution"][level] += 1

                hard_failures.update(_string_list(quality.get("hard_failures")))
                warnings.update(_string_list(quality.get("warnings")))
                flags.update(_string_list(quality.get("flags")))
                structured = _structured_output_from_quality(quality)
                fallback_count += structured["fallback_count"]
                repair_count += structured["repair_count"]
                failed_count += structured["failed_count"]
            else:
                summary["level_distribution"]["unknown"] += 1

            trace_structured = _structured_output_from_run_trace(doc)
            fallback_nodes.update(trace_structured["fallback_nodes"])
            if not is_evaluated or not _dict(_dict(quality.get("checks")).get("structured_output_health")):
                fallback_count += trace_structured["fallback_count"]
                repair_count += trace_structured["repair_count"]
                failed_count += trace_structured["failed_count"]

            risk_gate = _dict(doc.get("risk_gate"))
            if risk_gate.get("downgraded") is True:
                risk_downgraded_count += 1
            if risk_gate.get("blocked") is True:
                risk_blocked_count += 1
            risk_flags.update(_string_list(risk_gate.get("risk_flags")))

            trade_plan_action = _trade_plan_action(doc)
            final_action = str(doc.get("final_action") or doc.get("action") or "")
            draft_action = str(doc.get("draft_action") or trade_plan_action or "")
            action_distribution[str(doc.get("action") or final_action or "unknown")] += 1
            final_action_distribution[final_action or "unknown"] += 1
            if draft_action:
                draft_action_distribution[draft_action] += 1
            if final_action in ADD_LIKE_ACTIONS:
                add_like_count += 1
                actionable_count += 1
            elif final_action in REDUCE_LIKE_ACTIONS:
                reduce_like_count += 1
                actionable_count += 1
            elif final_action in HOLD_LIKE_ACTIONS:
                hold_like_count += 1
            if final_action == "hold_no_add":
                hold_no_add_count += 1
            if final_action == "wait":
                wait_count += 1
            if final_action == "watchlist":
                watchlist_count += 1
            if trade_plan_action and final_action:
                comparable_action_count += 1
                if trade_plan_action != final_action:
                    mismatch_count += 1
                    mismatch_pairs[f"{trade_plan_action} -> {final_action}"] += 1
            if draft_action and final_action:
                draft_final_comparable_count += 1
                if draft_action != final_action:
                    draft_to_final_downgrade_count += 1

            assessment = _dict(doc.get("ai_policy_assessment"))
            status = str(assessment.get("status") or "")
            if status == "evaluated":
                ai_policy_evaluated_count += 1
                ai_policy_challenges[str(assessment.get("challenge_level") or "unknown")] += 1
                user_summary = _dict(doc.get("user_investment_policy_summary"))
                user_role = str(user_summary.get("asset_role") or "")
                ai_role = str(assessment.get("ai_assessed_asset_role") or "")
                if user_role and ai_role:
                    ai_policy_role_comparable_count += 1
                    if user_role == ai_role:
                        ai_policy_role_agree_count += 1
                user_target = _float(user_summary.get("user_preferred_target_position_pct"))
                ai_target = _float(assessment.get("ai_recommended_target_position_pct"))
                if user_target is not None and ai_target is not None:
                    ai_policy_target_gaps.append(abs(user_target - ai_target))
                ai_max = _float(assessment.get("ai_recommended_max_position_pct"))
                advice_target = _float(_dict(doc.get("position_advice")).get("suggested_target_position_pct"))
                if str(doc.get("action") or "") in {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"} and ai_max is not None and advice_target is not None and advice_target > ai_max + 1e-6:
                    ai_policy_add_over_max_count += 1
                ai_bias = str(assessment.get("recommended_action_bias") or "")
                ai_stance = str(assessment.get("ai_position_stance") or "")
                if ai_bias:
                    ai_bias_comparable_count += 1
                    if _ai_bias_matches_final(ai_bias, final_action):
                        ai_bias_consistent_count += 1
                if ai_stance == "underweight" and final_action in HOLD_LIKE_ACTIONS:
                    ai_underweight_but_hold_count += 1
                if ai_bias == "allow_add" and final_action in HOLD_LIKE_ACTIONS:
                    ai_allow_add_but_hold_count += 1
                if ai_bias == "prefer_pullback_add" and final_action in {"wait", "watchlist"}:
                    ai_prefer_pullback_add_but_wait_count += 1
            elif status == "fallback":
                ai_policy_fallback_count += 1

            risk_gate = _dict(doc.get("risk_gate"))
            downgrade_reasons.update(_string_list(risk_gate.get("risk_flags")))
            downgrade_reasons.update(_string_list(risk_gate.get("gate_reasons")))
            trade_plan = _dict(doc.get("trade_plan"))
            assessment_block = _dict(trade_plan.get("risk_reward_assessment"))
            notes = _string_list(assessment_block.get("sanitization_notes"))
            if notes:
                trade_plan_sanitized_count += 1
                sanitization_reasons.update(notes)
            snapshot = _dict(_dict(risk_gate.get("action_constraints")).get("snapshot"))
            public_fallback = _int(snapshot.get("public_fallback_count"))
            if public_fallback >= 2:
                public_fallback_count += 1
                if final_action in HOLD_LIKE_ACTIONS:
                    public_fallback_hold_count += 1

        summary["unevaluated_count"] = summary["total_count"] - summary["evaluated_count"]
        summary["pass_rate"] = _rate(summary["pass_count"], summary["evaluated_count"])
        summary["average_score"] = round(sum(scores) / len(scores), 2) if scores else None
        summary["risk_gate"] = {
            "downgraded_count": risk_downgraded_count,
            "blocked_count": risk_blocked_count,
            "downgrade_rate": _rate(risk_downgraded_count, summary["total_count"]),
            "top_flags": _top_items(risk_flags),
        }
        summary["structured_output"] = {
            "fallback_count": fallback_count,
            "repair_count": repair_count,
            "failed_count": failed_count,
            "fallback_nodes": _top_items(fallback_nodes),
        }
        summary["action_consistency"] = {
            "trade_plan_final_mismatch_count": mismatch_count,
            "trade_plan_final_mismatch_rate": _rate(mismatch_count, comparable_action_count),
            "top_mismatch_pairs": _top_items(mismatch_pairs),
        }
        summary["ai_policy_assessment"] = {
            "evaluated_count": ai_policy_evaluated_count,
            "fallback_count": ai_policy_fallback_count,
            "challenge_distribution": _top_items(ai_policy_challenges),
            "role_agreement_rate": _rate(ai_policy_role_agree_count, ai_policy_role_comparable_count),
            "user_preference_vs_ai_target_gap_avg": (
                round(sum(ai_policy_target_gaps) / len(ai_policy_target_gaps), 6) if ai_policy_target_gaps else None
            ),
            "add_like_over_ai_max_count": ai_policy_add_over_max_count,
        }
        summary["action_calibration"] = {
            "action_distribution": _top_items(action_distribution),
            "final_action_distribution": _top_items(final_action_distribution),
            "draft_action_distribution": _top_items(draft_action_distribution),
            "add_like_rate": _rate(add_like_count, summary["total_count"]),
            "reduce_like_rate": _rate(reduce_like_count, summary["total_count"]),
            "hold_like_rate": _rate(hold_like_count, summary["total_count"]),
            "watchlist_rate": _rate(watchlist_count, summary["total_count"]),
            "hold_no_add_rate": _rate(hold_no_add_count, summary["total_count"]),
            "wait_rate": _rate(wait_count, summary["total_count"]),
            "actionable_rate": _rate(actionable_count, summary["total_count"]),
            "risk_gate_downgrade_rate": _rate(risk_downgraded_count, summary["total_count"]),
            "trade_plan_sanitization_rate": _rate(trade_plan_sanitized_count, summary["total_count"]),
            "draft_to_final_downgrade_rate": _rate(draft_to_final_downgrade_count, draft_final_comparable_count),
            "ai_bias_to_final_action_consistency": _rate(ai_bias_consistent_count, ai_bias_comparable_count),
            "ai_underweight_but_hold_count": ai_underweight_but_hold_count,
            "ai_allow_add_but_hold_count": ai_allow_add_but_hold_count,
            "ai_prefer_pullback_add_but_wait_count": ai_prefer_pullback_add_but_wait_count,
            "risk_gate_downgrade_reason_distribution": _top_items(downgrade_reasons),
            "trade_plan_sanitization_reason_distribution": _top_items(sanitization_reasons),
            "public_fallback_to_hold_rate": _rate(public_fallback_hold_count, public_fallback_count),
        }
        summary["top_hard_failures"] = _top_items(hard_failures)
        summary["top_warnings"] = _top_items(warnings)
        summary["top_flags"] = _top_items(flags)
        summary["recent_trend"] = _recent_trend(evaluated_docs)

        if summary["unevaluated_count"] > 0:
            summary["data_limitations"].append("some_legacy_decisions_missing_quality")
        return summary


def _empty_summary() -> dict:
    return {
        "version": "trade_decision_quality_analytics_v1",
        "total_count": 0,
        "evaluated_count": 0,
        "unevaluated_count": 0,
        "pass_count": 0,
        "fail_count": 0,
        "pass_rate": 0.0,
        "average_score": None,
        "level_distribution": {key: 0 for key in LEVEL_KEYS},
        "risk_gate": {
            "downgraded_count": 0,
            "blocked_count": 0,
            "downgrade_rate": 0.0,
            "top_flags": [],
        },
        "structured_output": {
            "fallback_count": 0,
            "repair_count": 0,
            "failed_count": 0,
            "fallback_nodes": [],
        },
        "action_consistency": {
            "trade_plan_final_mismatch_count": 0,
            "trade_plan_final_mismatch_rate": 0.0,
            "top_mismatch_pairs": [],
        },
        "ai_policy_assessment": {
            "evaluated_count": 0,
            "fallback_count": 0,
            "challenge_distribution": [],
            "role_agreement_rate": 0.0,
            "user_preference_vs_ai_target_gap_avg": None,
            "add_like_over_ai_max_count": 0,
        },
        "action_calibration": {
            "action_distribution": [],
            "final_action_distribution": [],
            "draft_action_distribution": [],
            "add_like_rate": 0.0,
            "reduce_like_rate": 0.0,
            "hold_like_rate": 0.0,
            "watchlist_rate": 0.0,
            "hold_no_add_rate": 0.0,
            "wait_rate": 0.0,
            "actionable_rate": 0.0,
            "risk_gate_downgrade_rate": 0.0,
            "trade_plan_sanitization_rate": 0.0,
            "draft_to_final_downgrade_rate": 0.0,
            "ai_bias_to_final_action_consistency": 0.0,
            "ai_underweight_but_hold_count": 0,
            "ai_allow_add_but_hold_count": 0,
            "ai_prefer_pullback_add_but_wait_count": 0,
            "risk_gate_downgrade_reason_distribution": [],
            "trade_plan_sanitization_reason_distribution": [],
            "public_fallback_to_hold_rate": 0.0,
        },
        "top_hard_failures": [],
        "top_warnings": [],
        "top_flags": [],
        "recent_trend": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_limitations": [],
    }


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]


def _top_items(counter: Counter[str], limit: int = 10) -> list[dict]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _structured_output_from_quality(quality: dict) -> dict:
    check = _dict(_dict(quality.get("checks")).get("structured_output_health"))
    if not check:
        return {"fallback_count": 0, "repair_count": 0, "failed_count": 0}
    fallback_count = _int(check.get("fallback_count"))
    repair_count = _int(check.get("repaired_count"))
    failed_count = _int(check.get("structured_output_failed_count"))
    flags = set(_string_list(check.get("flags")))
    warnings = _string_list(check.get("warnings"))
    if fallback_count == 0 and any("fallback" in item for item in flags.union(warnings)):
        fallback_count = 1
    if repair_count == 0 and "structured_output_repaired" in flags:
        repair_count = 1
    if failed_count == 0 and "structured_output_failed" in flags:
        failed_count = 1
    return {"fallback_count": fallback_count, "repair_count": repair_count, "failed_count": failed_count}


def _structured_output_from_run_trace(doc: dict) -> dict:
    fallback_count = 0
    repair_count = 0
    failed_count = 0
    fallback_nodes: Counter[str] = Counter()
    for item in _list(doc.get("run_trace")):
        trace = _dict(item)
        node_name = str(trace.get("node_name") or trace.get("node") or "unknown")
        if trace.get("fallback_used") or trace.get("status") == "fallback":
            fallback_count += 1
            fallback_nodes[node_name] += 1
        structured = _dict(trace.get("structured_output"))
        if not structured:
            continue
        if structured.get("fallback_used"):
            fallback_count += 1
            fallback_nodes[node_name] += 1
        if structured.get("repaired"):
            repair_count += 1
        if structured.get("ok") is False:
            failed_count += 1
    return {
        "fallback_count": fallback_count,
        "repair_count": repair_count,
        "failed_count": failed_count,
        "fallback_nodes": fallback_nodes,
    }


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_plan_action(doc: dict) -> str:
    trade_plan = _dict(doc.get("trade_plan"))
    if trade_plan.get("portfolio_action"):
        return str(trade_plan.get("portfolio_action"))
    card_pack = _dict(doc.get("card_pack"))
    trade_plan_card = _dict(card_pack.get("trade_plan_card"))
    return str(trade_plan_card.get("portfolio_action") or "")


def _ai_bias_matches_final(ai_bias: str, final_action: str) -> bool:
    if ai_bias == "allow_add":
        return final_action in ADD_LIKE_ACTIONS
    if ai_bias == "prefer_pullback_add":
        return final_action == "add_on_pullback"
    if ai_bias in {"hold_no_add", "avoid"}:
        return final_action in HOLD_LIKE_ACTIONS
    if ai_bias == "prefer_reduce":
        return final_action in REDUCE_LIKE_ACTIONS or final_action == "hold_no_add"
    return False


def _recent_trend(evaluated_docs: list[dict]) -> list[dict]:
    sorted_docs = sorted(evaluated_docs, key=lambda doc: str(doc.get("created_at") or ""))[-20:]
    return [
        {
            "id": str(doc.get("id") or ""),
            "symbol": str(doc.get("symbol") or ""),
            "created_at": str(doc.get("created_at") or ""),
            "score": _score_or_none(_quality(doc).get("score")),
            "level": str(_quality(doc).get("level") or "unknown"),
            "passed": _passed_or_none(_quality(doc).get("passed")),
            "action": str(doc.get("action") or ""),
        }
        for doc in sorted_docs
    ]


def _score_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _passed_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _quality(doc: dict) -> dict:
    return _dict(doc.get("decision_quality")) or _dict(_dict(doc.get("metadata")).get("decision_quality"))
