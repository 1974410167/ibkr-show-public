from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from app.agents.eval_baseline_health import (
    ArchitectureSignal,
    BaselineHealthReport,
    BaselineRecommendation,
    new_baseline_report_id,
    new_recommendation_id,
)
from app.agents.eval_failure_mining import SEVERITY_ORDER
from app.agents.eval_simulation_scenarios import summarize_synthetic_scenarios


class BaselineHealthReportService:
    def __init__(
        self,
        *,
        report_repository: Any,
        simulation_repository: Any,
        failure_repository: Any,
        case_repository: Any | None = None,
        agent_eval_service: Any | None = None,
    ) -> None:
        self.report_repository = report_repository
        self.simulation_repository = simulation_repository
        self.failure_repository = failure_repository
        self.case_repository = case_repository
        self.agent_eval_service = agent_eval_service

    def generate_report(
        self,
        *,
        simulation_run_id: str | None = None,
        failure_mining_run_id: str | None = None,
        include_converted_cases: bool = True,
        include_correctness_summary: bool = True,
        name: str | None = None,
    ) -> dict[str, Any]:
        simulation_run = self.simulation_repository.get_run(simulation_run_id) if simulation_run_id else None
        simulation_results = self.simulation_repository.list_results(simulation_run_id, limit=10000) if simulation_run_id else []
        mining_run = self.failure_repository.get_failure_mining_run(failure_mining_run_id) if failure_mining_run_id else None
        failures = self.failure_repository.list_failure_items(
            failure_mining_run_id=failure_mining_run_id,
            simulation_run_id=simulation_run_id,
            limit=10000,
        )
        all_converted_cases = self._list_converted_cases() if include_converted_cases else []
        converted_cases = self._filter_converted_cases(
            all_converted_cases,
            failure_mining_run_id=failure_mining_run_id,
            simulation_run_id=simulation_run_id,
        )
        correctness_summary = self._correctness_summary(include_correctness_summary)
        synthetic_summary = summarize_synthetic_scenarios()

        by_agent = self._build_by_agent(simulation_results, failures, converted_cases)
        by_failure_type = self._build_by_failure_type(failures)
        by_dimension = self._build_by_dimension(failures)
        high_priority = self._high_priority_failures(failures)
        converted_case_summary = self._converted_case_summary(converted_cases)
        recommendations = self._recommendations(by_agent, by_failure_type, by_dimension)
        architecture_signals = self._architecture_signals(failures)
        judge_signals = self._judge_calibration_signals(failures)
        summary = self._summary(
            synthetic_summary=synthetic_summary,
            simulation_results=simulation_results,
            failures=failures,
            converted_cases=converted_cases,
            by_dimension=by_dimension,
            global_converted_case_count=len(all_converted_cases),
        )
        markdown = self._markdown(
            summary=summary,
            by_agent=by_agent,
            by_failure_type=by_failure_type,
            by_dimension=by_dimension,
            high_priority_failures=high_priority,
            recommendations=recommendations,
            architecture_signals=architecture_signals,
            judge_calibration_signals=judge_signals,
        )
        report = BaselineHealthReport(
            report_id=new_baseline_report_id(),
            name=name or "Eval P3.5 baseline health report",
            simulation_run_id=simulation_run_id,
            failure_mining_run_id=failure_mining_run_id,
            status="completed" if failures or simulation_results else "completed_with_warnings",
            summary=summary,
            by_agent=by_agent,
            by_failure_type=by_failure_type,
            by_dimension=by_dimension,
            high_priority_failures=high_priority,
            converted_case_summary=converted_case_summary,
            recommendations=recommendations,
            architecture_signals=architecture_signals,
            judge_calibration_signals=judge_signals,
            markdown_report=markdown,
            metadata={
                "simulation_run_found": simulation_run is not None if simulation_run_id else None,
                "failure_mining_run_found": mining_run is not None if failure_mining_run_id else None,
                "include_converted_cases": include_converted_cases,
                "include_correctness_summary": include_correctness_summary,
                "correctness_summary": correctness_summary,
            },
        ).to_dict()
        return self.report_repository.save_report(report)

    def list_reports(self, *, agent_name: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        return self.report_repository.list_reports(agent_name=agent_name, status=status, limit=limit)

    def get_report(self, report_id: str) -> dict | None:
        return self.report_repository.get_report(report_id)

    def _summary(
        self,
        *,
        synthetic_summary: dict,
        simulation_results: list[dict],
        failures: list[dict],
        converted_cases: list[dict],
        by_dimension: list[dict],
        global_converted_case_count: int,
    ) -> dict:
        severity = Counter(item.get("severity") for item in failures)
        priorities = [int(item.get("conversion_priority") or 0) for item in failures]
        top_failure_type = _top(Counter(item.get("failure_type") for item in failures))
        weakest_dimension = by_dimension[0]["dimension"] if by_dimension else None
        score = self._health_score(failures)
        return {
            "scenario_count": synthetic_summary.get("total_count", 0),
            "simulation_result_count": len(simulation_results),
            "failure_count": len(failures),
            "critical_failure_count": severity.get("critical", 0),
            "high_failure_count": severity.get("high", 0),
            "medium_failure_count": severity.get("medium", 0),
            "low_failure_count": severity.get("low", 0),
            "affected_agent_count": len({item.get("agent_name") for item in failures if item.get("agent_name")}),
            "suggested_eval_case_count": sum(1 for item in failures if item.get("should_convert_to_eval_case")),
            "converted_case_count": len(converted_cases),
            "global_converted_case_count": global_converted_case_count,
            "avg_conversion_priority": int(mean(priorities)) if priorities else 0,
            "top_failure_type": top_failure_type,
            "weakest_dimension": weakest_dimension,
            "overall_health_score": score,
        }

    def _build_by_agent(self, simulation_results: list[dict], failures: list[dict], converted_cases: list[dict]) -> list[dict]:
        agents = {item.get("agent_name") for item in simulation_results + failures if item.get("agent_name")}
        rows = []
        for agent in sorted(agents):
            agent_failures = [item for item in failures if item.get("agent_name") == agent]
            agent_results = [item for item in simulation_results if item.get("agent_name") == agent]
            converted = [case for case in converted_cases if case.get("agent_name") == agent]
            failure_count = len(agent_failures)
            result_count = len(agent_results)
            type_counter = Counter(item.get("failure_type") for item in agent_failures)
            dim_counter = Counter(dim for item in agent_failures for dim in (item.get("failed_dimensions") or []))
            row = {
                "agent_name": agent,
                "scenario_count": result_count,
                "simulation_result_count": result_count,
                "failure_count": failure_count,
                "critical_count": sum(1 for item in agent_failures if item.get("severity") == "critical"),
                "high_count": sum(1 for item in agent_failures if item.get("severity") == "high"),
                "failure_rate": failure_count / result_count if result_count else (1.0 if failure_count else 0.0),
                "top_failure_types": [key for key, _count in type_counter.most_common(5)],
                "weakest_dimensions": [key for key, _count in dim_counter.most_common(5)],
                "suggested_eval_case_count": sum(1 for item in agent_failures if item.get("should_convert_to_eval_case")),
                "converted_case_count": len(converted),
                "health_score": self._health_score(agent_failures),
                "diagnosis": self._agent_diagnosis(agent, type_counter, dim_counter),
            }
            rows.append(row)
        rows.sort(key=lambda item: (item["critical_count"], item["high_count"], item["failure_count"]), reverse=True)
        return rows

    def _build_by_failure_type(self, failures: list[dict]) -> list[dict]:
        rows = []
        for failure_type, count in Counter(item.get("failure_type") for item in failures).most_common():
            items = [item for item in failures if item.get("failure_type") == failure_type]
            critical = sum(1 for item in items if item.get("severity") == "critical")
            high = sum(1 for item in items if item.get("severity") == "high")
            rows.append({
                "failure_type": failure_type,
                "count": count,
                "critical_count": critical,
                "high_count": high,
                "affected_agents": sorted({item.get("agent_name") for item in items if item.get("agent_name")}),
                "example_failure_ids": [item.get("failure_id") for item in items[:5]],
                "suggested_action": self._action_for_failure_type(failure_type),
                "priority": "critical" if critical else "high" if high or failure_type in {"missing_risk_control", "hallucinated_account_data"} else "medium",
            })
        return rows

    def _build_by_dimension(self, failures: list[dict]) -> list[dict]:
        bucket: dict[str, list[dict]] = defaultdict(list)
        for item in failures:
            for dim in item.get("failed_dimensions") or ["unspecified"]:
                bucket[dim].append(item)
        rows = []
        for dim, items in bucket.items():
            scores = []
            for item in items:
                raw = (item.get("judge_result") or {}).get("raw") or {}
                score = (raw.get("dimension_scores") or {}).get(dim)
                if isinstance(score, (int, float)):
                    scores.append(float(score))
            rows.append({
                "dimension": dim,
                "failed_count": len(items),
                "avg_score": round(mean(scores), 3) if scores else None,
                "affected_agents": sorted({item.get("agent_name") for item in items if item.get("agent_name")}),
                "example_failure_ids": [item.get("failure_id") for item in items[:5]],
                "severity_mix": dict(Counter(item.get("severity") for item in items)),
                "recommendation": self._action_for_dimension(dim),
            })
        rows.sort(key=lambda item: item["failed_count"], reverse=True)
        return rows

    def _high_priority_failures(self, failures: list[dict]) -> list[dict]:
        candidates = [
            item for item in failures
            if item.get("severity") in {"critical", "high"} or int(item.get("conversion_priority") or 0) >= 80
        ]
        candidates.sort(key=lambda item: (int(item.get("conversion_priority") or 0), SEVERITY_ORDER.get(item.get("severity"), 0)), reverse=True)
        seen = set()
        rows = []
        for item in candidates:
            key = item.get("duplicate_key") or item.get("failure_id")
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "failure_id": item.get("failure_id"),
                "agent_name": item.get("agent_name"),
                "scenario_id": item.get("scenario_id"),
                "failure_type": item.get("failure_type"),
                "severity": item.get("severity"),
                "conversion_priority": item.get("conversion_priority"),
                "user_question": item.get("user_question"),
                "output_excerpt": str(item.get("output_excerpt") or "")[:500],
                "recommendation": item.get("recommendation"),
                "should_convert_to_eval_case": item.get("should_convert_to_eval_case"),
                "converted_case_id": item.get("converted_case_id") or (item.get("metadata") or {}).get("converted_case_id"),
            })
        return rows[:20]

    def _converted_case_summary(self, cases: list[dict]) -> dict:
        return {
            "converted_case_count": len(cases),
            "by_agent": dict(Counter(case.get("agent_name") for case in cases)),
            "enabled_count": sum(1 for case in cases if case.get("enabled") is True),
            "disabled_count": sum(1 for case in cases if case.get("enabled") is not True),
        }

    def _recommendations(self, by_agent: list[dict], by_failure_type: list[dict], by_dimension: list[dict]) -> list[dict]:
        recs = []
        for row in by_failure_type[:5]:
            area = "tool_data" if row["failure_type"] in {"data_insufficient_but_confident", "tool_or_runtime_error"} else "prompt"
            if row["failure_type"] == "scenario_missing_required_context":
                area = "simulation_scenario"
            if row["failure_type"] in {"missing_risk_control", "weak_signal_overstatement"}:
                area = "node_check"
            recs.append(BaselineRecommendation(
                recommendation_id=new_recommendation_id(),
                priority=row["priority"],
                area=area,
                failure_type=row["failure_type"],
                title=f"Address {row['failure_type']} failures",
                rationale=f"{row['count']} failures across {', '.join(row['affected_agents']) or 'unknown agents'}.",
                suggested_action=row["suggested_action"],
                evidence={"example_failure_ids": row["example_failure_ids"]},
            ).to_dict())
        for row in by_dimension[:3]:
            recs.append(BaselineRecommendation(
                recommendation_id=new_recommendation_id(),
                priority="high" if row["failed_count"] > 2 else "medium",
                area="eval_case",
                dimension=row["dimension"],
                title=f"Strengthen eval coverage for {row['dimension']}",
                rationale=f"{row['failed_count']} failures mention this dimension.",
                suggested_action=row["recommendation"],
                evidence={"example_failure_ids": row["example_failure_ids"]},
            ).to_dict())
        return recs

    def _architecture_signals(self, failures: list[dict]) -> list[dict]:
        architecture_failures = [
            item for item in failures
            if item.get("failure_type") != "scenario_missing_required_context"
        ]
        failure_types = Counter(item.get("failure_type") for item in architecture_failures)
        dims = Counter(dim for item in architecture_failures for dim in (item.get("failed_dimensions") or []))
        signals = []
        if failure_types.get("weak_signal_overstatement", 0) + failure_types.get("missing_risk_control", 0) >= 2:
            signals.append(ArchitectureSignal(
                "need_decision_separation",
                0.7,
                "Trade decision failures suggest final recommendation may need stronger separation between signal, risk, and action.",
                {"failure_types": dict(failure_types)},
            ).to_dict())
        if failure_types.get("missing_risk_control", 0) >= 2 or dims.get("risk_awareness", 0) >= 2:
            signals.append(ArchitectureSignal(
                "need_stronger_risk_gate",
                0.75,
                "Risk-related failures appear repeatedly and should be gated before final output.",
                {"failure_types": dict(failure_types), "dimensions": dict(dims)},
            ).to_dict())
        if failure_types.get("data_insufficient_but_confident", 0) + failure_types.get("hallucinated_account_data", 0) >= 2:
            signals.append(ArchitectureSignal(
                "need_unified_evidence_pack",
                0.7,
                "Grounding failures suggest evidence availability and output grounding need a unified contract.",
                {"failure_types": dict(failure_types)},
            ).to_dict())
        if not signals:
            signals.append(ArchitectureSignal(
                "no_architecture_change_needed",
                0.6,
                "No repeated architecture-level pattern is visible; start with prompt, checks, and data handling.",
                {"failure_count": len(architecture_failures)},
            ).to_dict())
        return signals

    def _judge_calibration_signals(self, failures: list[dict]) -> list[dict]:
        signals = []
        for item in failures:
            judge = item.get("judge_result") or {}
            checks = item.get("failed_checks") or []
            if any(str(check.get("severity")) in {"fatal", "critical"} for check in checks) and judge.get("passed") is True:
                signals.append({
                    "signal_type": "judge_too_lenient",
                    "affected_agent": item.get("agent_name"),
                    "example_failure_ids": [item.get("failure_id")],
                    "suggested_rubric_update": "Add calibration case for rule-critical failure that judge passed.",
                    "priority": "high",
                })
            if not item.get("failed_dimensions"):
                signals.append({
                    "signal_type": "dimension_missing",
                    "affected_agent": item.get("agent_name"),
                    "example_failure_ids": [item.get("failure_id")],
                    "suggested_rubric_update": "Map this failure_type to at least one correctness dimension.",
                    "priority": "medium",
                })
        return signals[:20]

    def _markdown(self, **sections: Any) -> str:
        summary = sections["summary"]
        lines = [
            "# Eval P3.5 Baseline Health Report",
            "",
            "## Summary",
            f"- Overall health score: {summary.get('overall_health_score')}",
            f"- Failures: {summary.get('failure_count')} (critical={summary.get('critical_failure_count')}, high={summary.get('high_failure_count')})",
            f"- Suggested EvalCases: {summary.get('suggested_eval_case_count')}",
            "",
            "## By Agent",
        ]
        for row in sections["by_agent"]:
            lines.append(f"- {row['agent_name']}: failures={row['failure_count']}, health={row['health_score']}, diagnosis={row['diagnosis']}")
        lines.extend(["", "## Top Failure Types"])
        for row in sections["by_failure_type"][:10]:
            lines.append(f"- {row['failure_type']}: {row['count']} ({row['priority']})")
        lines.extend(["", "## Weakest Dimensions"])
        for row in sections["by_dimension"][:10]:
            lines.append(f"- {row['dimension']}: {row['failed_count']}")
        lines.extend(["", "## High Priority Failures"])
        for row in sections["high_priority_failures"][:10]:
            lines.append(f"- {row['failure_id']} {row['agent_name']} {row['failure_type']} priority={row['conversion_priority']}")
        lines.extend(["", "## Recommendations"])
        for row in sections["recommendations"][:10]:
            lines.append(f"- [{row['priority']}] {row['title']}: {row['suggested_action']}")
        lines.extend(["", "## Architecture Signals"])
        for row in sections["architecture_signals"]:
            lines.append(f"- {row['signal_type']} ({row['confidence']}): {row['rationale']}")
        lines.extend(["", "## Judge Calibration Signals"])
        for row in sections["judge_calibration_signals"][:10]:
            lines.append(f"- {row['signal_type']}: {row['suggested_rubric_update']}")
        lines.extend(["", "## Next Actions", "- Prioritize high conversion-priority failures and add targeted disabled EvalCases before enabling regression gates."])
        return "\n".join(lines)

    def _list_converted_cases(self) -> list[dict]:
        if self.case_repository is None:
            return []
        try:
            return self.case_repository.list_cases(source="synthetic_failure", include_archived=True, limit=10000)
        except TypeError:
            return self.case_repository.list_cases(source="synthetic_failure", limit=10000)

    def _filter_converted_cases(
        self,
        cases: list[dict],
        *,
        failure_mining_run_id: str | None,
        simulation_run_id: str | None,
    ) -> list[dict]:
        if failure_mining_run_id:
            return [
                case for case in cases
                if (case.get("metadata") or {}).get("failure_mining_run_id") == failure_mining_run_id
            ]
        if simulation_run_id:
            return [
                case for case in cases
                if (case.get("metadata") or {}).get("simulation_run_id") == simulation_run_id
            ]
        return cases

    def _correctness_summary(self, enabled: bool) -> dict:
        if not enabled or self.agent_eval_service is None:
            return {}
        try:
            return self.agent_eval_service.get_correctness_summary(limit=1000)
        except Exception:
            return {}

    def _health_score(self, failures: list[dict]) -> float:
        if not failures:
            return 1.0
        count = len(failures)
        critical = sum(1 for item in failures if item.get("severity") == "critical") / count
        high = sum(1 for item in failures if item.get("severity") == "high") / count
        judge_failed = sum(1 for item in failures if (item.get("judge_result") or {}).get("passed") is False) / count
        risk = sum(1 for item in failures if item.get("failure_type") in {"missing_risk_control", "missing_actionability"}) / count
        return round(max(0.0, 1.0 - critical * 0.45 - high * 0.25 - judge_failed * 0.1 - risk * 0.1), 3)

    def _agent_diagnosis(self, agent: str, failure_types: Counter, dimensions: Counter) -> str:
        top = _top(failure_types)
        if top == "scenario_missing_required_context":
            return "synthetic scenario context is incomplete; fix scenario configuration before judging agent behavior."
        if agent == "trade_decision" and top in {"missing_risk_control", "weak_signal_overstatement"}:
            return "risk control and signal overstatement are dominant weaknesses."
        if agent == "account_copilot" and top == "hallucinated_account_data":
            return "hallucinated account data risk is the top issue."
        if agent == "daily_position_review":
            return "attribution quality is the main area to inspect."
        if agent == "trade_review":
            return "process vs outcome separation needs tightening."
        return f"top weakness: {top or _top(dimensions) or 'none'}."

    def _action_for_failure_type(self, failure_type: str) -> str:
        return {
            "scenario_missing_required_context": "Fix synthetic scenario required context fields before judging agent output quality.",
            "missing_risk_control": "Strengthen prompt and rule checks for risk, position sizing, and invalidation conditions.",
            "weak_signal_overstatement": "Require concrete catalyst evidence before strong buy or high-confidence language.",
            "data_insufficient_but_confident": "Improve data availability checks and force explicit data limitation language.",
            "hallucinated_account_data": "Block account fact claims unless backed by explicit account fields.",
            "irrelevant_news_attribution": "Add timing and position-impact checks before news attribution.",
            "result_only_trade_review": "Evaluate process quality separately from outcome quality.",
            "tool_or_runtime_error": "Improve tool fallback and runtime error handling.",
        }.get(failure_type, "Review examples and add targeted checks or EvalCases.")

    def _action_for_dimension(self, dimension: str) -> str:
        return {
            "scenario_context": "Add required real-executor context fields or date strategies to synthetic scenarios.",
            "risk_awareness": "Add risk gate and stronger expected behavior around downside/invalidation.",
            "actionability": "Require concrete next steps, triggers, and constraints.",
            "data_grounding": "Require evidence references and explicit missing-data handling.",
            "factual_accuracy": "Add account/data factuality checks.",
            "process_vs_outcome": "Add trade review cases separating process and outcome.",
        }.get(dimension, "Add targeted examples and checks for this dimension.")


def _top(counter: Counter) -> str | None:
    return counter.most_common(1)[0][0] if counter else None
