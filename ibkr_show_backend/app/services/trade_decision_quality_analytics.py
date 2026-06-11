from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


LEVEL_KEYS = ("excellent", "good", "warning", "poor", "unknown")


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
            final_action = str(doc.get("action") or "")
            if trade_plan_action and final_action:
                comparable_action_count += 1
                if trade_plan_action != final_action:
                    mismatch_count += 1
                    mismatch_pairs[f"{trade_plan_action} -> {final_action}"] += 1

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


def _trade_plan_action(doc: dict) -> str:
    trade_plan = _dict(doc.get("trade_plan"))
    if trade_plan.get("portfolio_action"):
        return str(trade_plan.get("portfolio_action"))
    card_pack = _dict(doc.get("card_pack"))
    trade_plan_card = _dict(card_pack.get("trade_plan_card"))
    return str(trade_plan_card.get("portfolio_action") or "")


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
