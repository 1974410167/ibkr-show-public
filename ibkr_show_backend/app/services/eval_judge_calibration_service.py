from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.agents.eval_failure_mining import SEVERITY_ORDER
from app.agents.eval_harness import EvalCase, new_eval_case_id
from app.agents.eval_judge_calibration import (
    JudgeCalibrationCaseDraft,
    JudgeCalibrationRun,
    JudgeCalibrationSignal,
    new_calibration_draft_id,
    new_calibration_run_id,
    new_calibration_signal_id,
    new_calibration_suggestion_id,
)
from app.agents.eval_simulation_scenarios import get_synthetic_scenario


DIMENSION_BY_FAILURE_TYPE = {
    "missing_risk_control": ["risk_awareness", "risk_control_quality"],
    "weak_signal_overstatement": ["no_signal_overstatement", "reasoning_consistency"],
    "data_insufficient_but_confident": ["data_grounding", "uncertainty_handling"],
    "hallucinated_account_data": ["factual_accuracy", "account_data_accuracy"],
    "irrelevant_news_attribution": ["attribution_quality", "news_relevance"],
    "result_only_trade_review": ["process_vs_outcome_separation"],
    "hindsight_bias": ["process_vs_outcome_separation", "reasoning_consistency"],
    "missing_position_sizing": ["position_sizing", "risk_control_quality"],
    "missing_actionability": ["actionability"],
}


class JudgeCalibrationService:
    def __init__(
        self,
        *,
        calibration_repository: Any,
        failure_repository: Any,
        simulation_repository: Any,
        baseline_report_repository: Any | None = None,
        case_repository: Any | None = None,
    ) -> None:
        self.calibration_repository = calibration_repository
        self.failure_repository = failure_repository
        self.simulation_repository = simulation_repository
        self.baseline_report_repository = baseline_report_repository
        self.case_repository = case_repository

    def detect_calibration_signals(
        self,
        *,
        failure_mining_run_id: str | None = None,
        baseline_report_id: str | None = None,
        agent_name: str | None = None,
        min_priority: int = 50,
        deduplicate: bool = True,
        name: str | None = None,
    ) -> dict[str, Any]:
        if not failure_mining_run_id and not baseline_report_id:
            raise ValueError("failure_mining_run_id or baseline_report_id is required")

        source_type = "baseline_report" if baseline_report_id else "failure_mining_run"
        source_id = baseline_report_id or failure_mining_run_id or ""
        failures = self._load_failures(failure_mining_run_id=failure_mining_run_id, baseline_report_id=baseline_report_id)
        if agent_name:
            failures = [failure for failure in failures if failure.get("agent_name") == agent_name]

        calibration_run_id = new_calibration_run_id()
        signals = []
        for failure in failures:
            for signal in self._signals_for_failure(failure):
                if signal["priority"] >= int(min_priority):
                    signal["calibration_run_id"] = calibration_run_id
                    signals.append(signal)
        signals.extend(self._duplicate_stability_signals(failures, calibration_run_id=calibration_run_id, min_priority=min_priority))

        deduplicated_count = 0
        if deduplicate:
            signals, deduplicated_count = self._deduplicate_signals(signals)
        signals.sort(key=lambda item: int(item.get("priority") or 0), reverse=True)
        suggestions = build_judge_improvement_suggestions(signals)
        summary = self._summary(signals, deduplicated_count=deduplicated_count)
        run = JudgeCalibrationRun(
            calibration_run_id=calibration_run_id,
            source_type=source_type,
            source_id=source_id,
            status="completed" if signals else "completed_with_warnings",
            config={
                "failure_mining_run_id": failure_mining_run_id,
                "baseline_report_id": baseline_report_id,
                "agent_name": agent_name,
                "min_priority": min_priority,
                "deduplicate": deduplicate,
                "name": name,
            },
            summary=summary,
            signals=signals[:100],
            suggestions=suggestions,
            metadata={"stage": "p3_5_stage_06", "source": "judge_calibration_loop"},
        ).to_dict()
        self.calibration_repository.save_run(run)
        for signal in signals:
            self.calibration_repository.save_signal(signal)
        return {"calibration_run": run, "signals": signals, "suggestions": suggestions, "summary": summary}

    def list_runs(self, *, agent_name: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        return self.calibration_repository.list_runs(agent_name=agent_name, status=status, limit=limit)

    def get_run_with_signals(self, calibration_run_id: str, *, limit: int = 1000) -> dict | None:
        run = self.calibration_repository.get_run(calibration_run_id)
        if run is None:
            return None
        signals = self.calibration_repository.list_signals(calibration_run_id=calibration_run_id, limit=limit)
        suggestions = run.get("suggestions") or build_judge_improvement_suggestions(signals)
        return {"calibration_run": run, "signals": signals, "suggestions": suggestions, "summary": run.get("summary") or {}}

    def list_signals(self, **kwargs: Any) -> dict[str, Any]:
        signals = self.calibration_repository.list_signals(**kwargs)
        return {"items": signals, "summary": self._summary(signals, deduplicated_count=0)}

    def get_signal(self, signal_id: str) -> dict | None:
        return self.calibration_repository.get_signal(signal_id)

    def preview_calibration_case(self, signal_id: str, *, enabled: bool = False) -> dict[str, Any]:
        signal, failure, scenario, simulation_result = self._load_case_sources(signal_id)
        quality = score_calibration_case_quality(signal, failure, scenario, simulation_result)
        payload = build_calibration_case_from_signal(
            signal,
            failure,
            scenario,
            simulation_result,
            enabled=enabled,
        )
        duplicate = self.find_existing_case_for_signal(signal, failure, scenario)
        warnings = list(quality["warnings"])
        if duplicate:
            warnings.append(f"duplicate case exists: {duplicate.get('case_id')}")
        draft = JudgeCalibrationCaseDraft(
            draft_id=new_calibration_draft_id(),
            signal_id=signal_id,
            failure_id=signal.get("failure_id"),
            agent_name=signal.get("agent_name") or "",
            case_payload=payload,
            expected_judge_behavior=payload["expected_behavior"]["expected_judge_behavior"],
            calibration_reason=signal.get("disagreement_reason") or signal.get("recommendation") or "",
            quality_score=float(quality["quality_score"]),
            quality_warnings=warnings,
            metadata={
                "eligible": quality["eligible"],
                "duplicate_case_id": duplicate.get("case_id") if duplicate else None,
            },
        ).to_dict()
        return {"draft": draft, "quality": quality, "duplicate": duplicate}

    def create_calibration_case(self, signal_id: str, *, enabled: bool = False, force: bool = False) -> dict[str, Any]:
        if self.case_repository is None:
            raise ValueError("case_repository is required")
        preview = self.preview_calibration_case(signal_id, enabled=enabled)
        draft = preview["draft"]
        quality = preview["quality"]
        duplicate = preview["duplicate"]
        if duplicate and not force:
            return _case_result(signal_id, draft["draft_id"], duplicate.get("case_id"), "duplicate", "Matching calibration EvalCase already exists", draft["case_payload"], {"existing_case_id": duplicate.get("case_id")})
        if not quality["eligible"] and not force:
            return _case_result(signal_id, draft["draft_id"], None, "skipped", "Calibration signal quality is below conversion threshold", draft["case_payload"], {"quality": quality})
        payload = dict(draft["case_payload"])
        if duplicate and force:
            payload["case_id"] = f"{payload['case_id']}_forced"
        saved = self.case_repository.save_case(EvalCase.from_dict(payload).to_dict())
        self._mark_signal_converted(signal_id, saved["case_id"], status="saved")
        return _case_result(signal_id, draft["draft_id"], saved["case_id"], "saved", "Calibration EvalCase saved as disabled draft" if not enabled else "Calibration EvalCase saved", saved, {"quality": quality, "forced": force})

    def batch_create_calibration_cases(
        self,
        *,
        calibration_run_id: str,
        min_priority: int = 70,
        max_cases: int = 20,
        enabled: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        signals = self.calibration_repository.list_signals(
            calibration_run_id=calibration_run_id,
            min_priority=min_priority,
            should_create_calibration_case=True,
            limit=10000,
        )
        signals.sort(key=lambda item: int(item.get("priority") or 0), reverse=True)
        results = []
        for signal in signals[: max(1, min(int(max_cases), 100))]:
            try:
                results.append(self.create_calibration_case(signal["signal_id"], enabled=enabled, force=force))
            except Exception as exc:
                results.append(_case_result(signal.get("signal_id", ""), None, None, "error", str(exc), {}, {}))
        return {
            "created_count": sum(1 for item in results if item["status"] == "saved"),
            "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
            "duplicate_count": sum(1 for item in results if item["status"] == "duplicate"),
            "error_count": sum(1 for item in results if item["status"] == "error"),
            "results": results,
        }

    def find_existing_case_for_signal(self, signal: dict, failure: dict | None, scenario: dict | None) -> dict | None:
        if self.case_repository is None:
            return None
        duplicate_key = build_calibration_case_duplicate_key(signal, failure, scenario)
        candidates = self.case_repository.list_cases(
            agent_name=signal.get("agent_name"),
            source="judge_calibration_mined",
            include_archived=True,
            limit=10000,
        )
        for case in candidates:
            metadata = case.get("metadata") or {}
            if metadata.get("calibration_signal_id") == signal.get("signal_id"):
                return case
            if metadata.get("duplicate_key") == duplicate_key:
                return case
        return None

    def _load_failures(self, *, failure_mining_run_id: str | None, baseline_report_id: str | None) -> list[dict]:
        if failure_mining_run_id:
            return self.failure_repository.list_failure_items(failure_mining_run_id=failure_mining_run_id, limit=10000)
        if not self.baseline_report_repository:
            return []
        report = self.baseline_report_repository.get_report(baseline_report_id or "")
        if not report:
            return []
        report_failure_mining_run_id = report.get("failure_mining_run_id")
        if report_failure_mining_run_id:
            return self.failure_repository.list_failure_items(failure_mining_run_id=report_failure_mining_run_id, limit=10000)
        failures = []
        for row in report.get("high_priority_failures") or []:
            failure = self.failure_repository.get_failure_item(row.get("failure_id") or "")
            if failure:
                failures.append(failure)
        return failures

    def _signals_for_failure(self, failure: dict) -> list[dict[str, Any]]:
        signals = []
        checks = failure.get("failed_checks") or []
        judge = _judge_raw(failure.get("judge_result") or {})
        failed_dimensions = list(failure.get("failed_dimensions") or [])
        mapped_dimensions = DIMENSION_BY_FAILURE_TYPE.get(failure.get("failure_type"), [])
        high_checks = [check for check in checks if _severity_rank(_check_severity(check)) >= _severity_rank("high")]
        critical_checks = [check for check in checks if _severity_rank(_check_severity(check)) >= _severity_rank("critical")]
        judge_passed = _judge_passed(judge)
        score = _judge_score(judge)
        confidence = _judge_confidence(judge)

        if (critical_checks or high_checks) and (judge_passed is True or score >= 0.75):
            signals.append(self._signal(
                "judge_too_lenient",
                failure,
                priority=95 if critical_checks else 85,
                severity="critical" if critical_checks else "high",
                rule_check_status="failed_high",
                judge_status="passed_or_high_score",
                affected_dimensions=_dimensions_from_checks(checks) or mapped_dimensions,
                disagreement_reason="Rule checks found high/critical failure, but judge passed or scored the output highly.",
                recommendation="Increase judge weight for high/critical rule failures and require explicit failed_dimensions.",
            ))
        if not high_checks and judge_passed is False and (_generic_reasons(judge) or (score < 0.6 and not judge.get("failed_dimensions"))):
            signals.append(self._signal(
                "judge_too_strict",
                failure,
                priority=75,
                severity="medium",
                rule_check_status="passed_or_warning_only",
                judge_status="failed_without_specific_dimensions",
                affected_dimensions=list(judge.get("failed_dimensions") or []),
                disagreement_reason="Judge failed the output while rule checks were clean or low severity, without specific evidence.",
                recommendation="Require concrete evidence and failed_dimensions before judge marks a low-signal case failed.",
            ))
        if _rule_judge_conflict(checks, judge):
            signals.append(self._signal(
                "judge_rule_conflict",
                failure,
                priority=80,
                severity=failure.get("severity") or "high",
                rule_check_status="failed_dimension",
                judge_status="high_dimension_score",
                affected_dimensions=_conflicting_dimensions(checks, judge),
                disagreement_reason="Rule checks and judge dimension scores point in opposite directions.",
                recommendation="Align judge dimension scoring with rule check dimensions for this agent.",
            ))
        missing = [dim for dim in mapped_dimensions if dim not in set(judge.get("failed_dimensions") or []) and dim not in (judge.get("dimension_scores") or {})]
        if mapped_dimensions and missing:
            signals.append(self._signal(
                "judge_missing_dimension",
                failure,
                priority=78 if failure.get("severity") in {"critical", "high"} else 60,
                severity=failure.get("severity") or "medium",
                rule_check_status="failed_known_dimension",
                judge_status="dimension_missing",
                affected_dimensions=missing,
                disagreement_reason="Failure type maps to key judge dimensions that are absent from judge failed_dimensions or dimension_scores.",
                recommendation="Add explicit judge rubric coverage for the missing dimensions.",
            ))
        if failure.get("severity") in {"critical", "high"} and confidence < 0.5 and judge:
            signals.append(self._signal(
                "judge_low_confidence",
                failure,
                priority=72,
                severity=failure.get("severity") or "high",
                rule_check_status="high_severity_failure",
                judge_status="low_confidence",
                affected_dimensions=failed_dimensions or mapped_dimensions,
                disagreement_reason="Judge confidence is low on a high-severity synthetic failure.",
                recommendation="Create calibration examples to stabilize judge confidence on this pattern.",
            ))
        if _parse_or_schema_error(judge):
            signals.append(self._signal(
                "judge_parse_or_schema_error",
                failure,
                priority=90,
                severity="high",
                rule_check_status="unknown",
                judge_status="parse_or_schema_error",
                affected_dimensions=["parser"],
                disagreement_reason="Judge result indicates parse failure, schema error, or missing required fields.",
                recommendation="Strengthen judge JSON normalization and prompt constraints.",
            ))
        return signals

    def _duplicate_stability_signals(self, failures: list[dict], *, calibration_run_id: str, min_priority: int) -> list[dict]:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for failure in failures:
            key = failure.get("duplicate_key") or f"{failure.get('agent_name')}:{failure.get('failure_type')}:{failure.get('category')}"
            buckets[key].append(failure)
        signals = []
        for items in buckets.values():
            if len(items) < 2:
                continue
            scores = [_judge_score(_judge_raw(item.get("judge_result") or {})) for item in items if item.get("judge_result")]
            statuses = {_judge_passed(_judge_raw(item.get("judge_result") or {})) for item in items if item.get("judge_result")}
            if len(scores) < 2:
                continue
            if (max(scores) - min(scores) > 0.3) or len(statuses - {None}) > 1:
                failure = items[0]
                signal = self._signal(
                    "judge_unstable_on_duplicates",
                    failure,
                    priority=85,
                    severity="high",
                    rule_check_status="similar_failures",
                    judge_status="inconsistent_scores",
                    affected_dimensions=list({dim for item in items for dim in (item.get("failed_dimensions") or [])}),
                    disagreement_reason="Similar duplicate failures received materially different judge scores or pass/fail labels.",
                    recommendation="Add calibration examples and tighten judge schema for repeated failure patterns.",
                )
                signal["calibration_run_id"] = calibration_run_id
                signal["evidence"]["duplicate_failure_ids"] = [item.get("failure_id") for item in items]
                signal["evidence"]["judge_scores"] = scores
                if signal["priority"] >= int(min_priority):
                    signals.append(signal)
        return signals

    def _signal(
        self,
        signal_type: str,
        failure: dict,
        *,
        priority: int,
        severity: str,
        rule_check_status: str,
        judge_status: str,
        affected_dimensions: list[str],
        disagreement_reason: str,
        recommendation: str,
    ) -> dict[str, Any]:
        duplicate_key = _signal_duplicate_key(signal_type, failure, affected_dimensions)
        return JudgeCalibrationSignal(
            signal_id=new_calibration_signal_id(),
            signal_type=signal_type,
            agent_name=failure.get("agent_name") or "",
            failure_id=failure.get("failure_id"),
            simulation_result_id=failure.get("simulation_result_id"),
            scenario_id=failure.get("scenario_id"),
            severity=severity,
            priority=priority,
            rule_check_status=rule_check_status,
            judge_status=judge_status,
            failed_checks=list(failure.get("failed_checks") or []),
            judge_result=dict(failure.get("judge_result") or {}),
            disagreement_reason=disagreement_reason,
            affected_dimensions=affected_dimensions,
            evidence={
                "failure_type": failure.get("failure_type"),
                "failed_dimensions": failure.get("failed_dimensions") or [],
                "failed_checks": failure.get("failed_checks") or [],
                "judge_result": failure.get("judge_result") or {},
                "output_excerpt": failure.get("output_excerpt"),
            },
            recommendation=recommendation,
            should_create_calibration_case=priority >= 70 and signal_type != "other",
            duplicate_key=duplicate_key,
            metadata={
                "failure_mining_run_id": failure.get("failure_mining_run_id"),
                "simulation_run_id": failure.get("simulation_run_id"),
                "failure_type": failure.get("failure_type"),
                "stage": "p3_5_stage_06",
            },
        ).to_dict()

    def _deduplicate_signals(self, signals: list[dict]) -> tuple[list[dict], int]:
        buckets: dict[str, dict] = {}
        duplicate_count = 0
        for signal in signals:
            key = signal.get("duplicate_key") or signal.get("signal_id")
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = signal
                continue
            duplicate_count += 1
            metadata = dict(existing.get("metadata") or {})
            metadata["duplicate_count"] = int(metadata.get("duplicate_count") or 1) + 1
            existing["metadata"] = metadata
            existing.setdefault("evidence", {}).setdefault("duplicate_signal_ids", []).append(signal.get("signal_id"))
            if int(signal.get("priority") or 0) > int(existing.get("priority") or 0):
                signal["metadata"] = metadata
                signal.setdefault("evidence", {})["duplicate_signal_ids"] = existing.get("evidence", {}).get("duplicate_signal_ids", [])
                buckets[key] = signal
        return list(buckets.values()), duplicate_count

    def _summary(self, signals: list[dict], *, deduplicated_count: int) -> dict[str, Any]:
        return {
            "signal_count": len(signals),
            "case_candidate_count": sum(1 for item in signals if item.get("should_create_calibration_case")),
            "deduplicated_count": deduplicated_count,
            "by_agent": dict(Counter(item.get("agent_name") for item in signals)),
            "by_signal_type": dict(Counter(item.get("signal_type") for item in signals)),
            "by_severity": dict(Counter(item.get("severity") for item in signals)),
            "top_dimensions": dict(Counter(dim for item in signals for dim in (item.get("affected_dimensions") or [])).most_common(10)),
        }

    def _load_case_sources(self, signal_id: str) -> tuple[dict, dict | None, dict | None, dict | None]:
        signal = self.calibration_repository.get_signal(signal_id)
        if signal is None:
            raise ValueError("Judge calibration signal not found")
        failure = self.failure_repository.get_failure_item(signal.get("failure_id") or "") if signal.get("failure_id") else None
        scenario = get_synthetic_scenario(signal.get("scenario_id") or "")
        simulation_result = self.simulation_repository.get_result(signal.get("simulation_result_id") or "") if signal.get("simulation_result_id") else None
        return signal, failure, scenario, simulation_result

    def _mark_signal_converted(self, signal_id: str, case_id: str, *, status: str) -> None:
        signal = self.calibration_repository.get_signal(signal_id)
        if not signal:
            return
        metadata = dict(signal.get("metadata") or {})
        metadata.update({"converted_case_id": case_id, "conversion_status": status})
        signal["metadata"] = metadata
        signal["converted_case_id"] = case_id
        self.calibration_repository.save_signal(signal)


def build_judge_improvement_suggestions(signals: list[dict]) -> list[dict]:
    suggestions = []
    by_type = Counter(item.get("signal_type") for item in signals)
    by_dimension = Counter(dim for item in signals for dim in (item.get("affected_dimensions") or []))
    examples_by_type: dict[str, list[str]] = defaultdict(list)
    for signal in signals:
        examples_by_type[signal.get("signal_type") or "other"].append(signal.get("signal_id"))
    rules = [
        ("judge_too_lenient", "global_rubric", "Strengthen critical rule check handling", "Judge is passing outputs with high/critical rule failures.", "If a critical rule check fails, judge should not pass unless explicit evidence overturns the rule."),
        ("judge_too_strict", "judge_prompt", "Require evidence for strict failures", "Judge is failing outputs without concrete failed dimensions.", "Require failure_reasons and failed_dimensions to include specific evidence before passed=false."),
        ("judge_missing_dimension", "agent_rubric", "Add missing dimension coverage", "Judge omits dimensions implied by mined failure types.", "Extend agent-specific rubric questions and dimension mapping for repeated missing dimensions."),
        ("judge_unstable_on_duplicates", "calibration_case", "Add duplicate-pattern calibration examples", "Similar failures receive unstable judge decisions.", "Add paired calibration cases and tighten JSON schema to reduce free-form interpretation."),
        ("judge_parse_or_schema_error", "parser", "Strengthen judge JSON parser guardrails", "Judge result was unparseable or missing required fields.", "Improve normalize_correctness_judge_result and prompt JSON-only constraints."),
    ]
    for signal_type, target, title, problem, suggested_change in rules:
        count = by_type.get(signal_type, 0)
        if count <= 0:
            continue
        suggestions.append({
            "suggestion_id": new_calibration_suggestion_id(),
            "priority": min(100, 60 + count * 10),
            "target": target,
            "agent_name": None,
            "dimension": _most_common_dimension(signals, signal_type, by_dimension),
            "title": title,
            "problem": problem,
            "suggested_change": suggested_change,
            "evidence": {"signal_count": count},
            "example_signal_ids": examples_by_type[signal_type][:5],
        })
    suggestions.sort(key=lambda item: int(item["priority"]), reverse=True)
    return suggestions


def build_calibration_case_from_signal(
    signal: dict,
    failure: dict | None,
    scenario: dict | None,
    simulation_result: dict | None,
    *,
    enabled: bool = False,
) -> dict[str, Any]:
    agent_name = signal.get("agent_name") or (failure or {}).get("agent_name") or ""
    signal_type = signal.get("signal_type") or "other"
    expected = _expected_judge_behavior(signal)
    metadata = {
        "p3_5_source": "judge_calibration",
        "calibration_signal_id": signal.get("signal_id"),
        "signal_type": signal_type,
        "failure_id": signal.get("failure_id"),
        "failure_mining_run_id": (failure or {}).get("failure_mining_run_id") or (signal.get("metadata") or {}).get("failure_mining_run_id"),
        "simulation_run_id": (failure or {}).get("simulation_run_id") or (signal.get("metadata") or {}).get("simulation_run_id"),
        "simulation_result_id": signal.get("simulation_result_id"),
        "scenario_id": signal.get("scenario_id"),
        "expected_judge_behavior": expected,
        "original_judge_result": signal.get("judge_result") or {},
        "failed_checks": signal.get("failed_checks") or [],
        "disagreement_reason": signal.get("disagreement_reason"),
        "duplicate_key": build_calibration_case_duplicate_key(signal, failure, scenario),
    }
    user_question = (scenario or {}).get("user_question") or (simulation_result or {}).get("user_question") or (failure or {}).get("user_question") or ""
    return EvalCase(
        case_id=f"judge_calib_mined_{agent_name}_{signal_type}_{(signal.get('signal_id') or '')[-8:]}",
        agent_name=agent_name,
        title=f"Judge calibration: {signal_type}",
        description=signal.get("disagreement_reason") or signal.get("recommendation") or "",
        tags=list(dict.fromkeys([
            "judge_calibration",
            "p3_5",
            "synthetic",
            "calibration_mined",
            "correctness",
            "regression",
            signal_type,
            agent_name,
        ])),
        source="judge_calibration_mined",
        input={"user_question": user_question},
        mock_context={"scenario": scenario or {}, "failure": failure or {}, "simulation_result": simulation_result or {}},
        expected_behavior={
            "expected_judge_behavior": expected,
            "why_current_judge_behavior_is_bad": signal.get("disagreement_reason"),
        },
        forbidden_behavior=[
            "不得忽略 critical rule check",
            "不得无证据 failed",
            "不得漏掉关键维度",
            "不得输出无法解析 JSON",
        ],
        severity=signal.get("severity") or "medium",
        category="judge_calibration",
        metadata=metadata,
        enabled=enabled,
        judge_enabled=True,
        correctness_judge_enabled=True,
    ).to_dict()


def score_calibration_case_quality(signal: dict, failure: dict | None, scenario: dict | None, simulation_result: dict | None) -> dict[str, Any]:
    warnings = []
    if int(signal.get("priority") or 0) < 70:
        warnings.append("priority below 70")
    if signal.get("signal_type") in {None, "", "other"}:
        warnings.append("signal_type is other")
    if not signal.get("disagreement_reason"):
        warnings.append("missing disagreement_reason")
    if not (signal.get("failed_checks") or signal.get("judge_result")):
        warnings.append("missing failed_checks and judge_result")
    if not ((scenario or {}).get("user_question") or (simulation_result or {}).get("user_question") or (failure or {}).get("user_question")):
        warnings.append("missing user_question")
    if not _expected_judge_behavior(signal).get("should"):
        warnings.append("expected judge behavior is unclear")
    score = max(0.0, 1.0 - len(warnings) * 0.18)
    return {"eligible": not warnings, "quality_score": round(score, 3), "warnings": warnings}


def build_calibration_case_duplicate_key(signal: dict, failure: dict | None, scenario: dict | None) -> str:
    dims = ",".join(sorted(signal.get("affected_dimensions") or []))
    failure_type = (failure or {}).get("failure_type") or (signal.get("metadata") or {}).get("failure_type") or "unknown"
    category = (scenario or {}).get("category") or failure_type
    return f"{signal.get('agent_name')}:{signal.get('signal_type')}:{dims}:{failure_type}:{category}"


def _case_result(signal_id: str, draft_id: str | None, case_id: str | None, status: str, reason: str, case_payload: dict, metadata: dict) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "draft_id": draft_id,
        "case_id": case_id,
        "status": status,
        "reason": reason,
        "case_payload": case_payload,
        "metadata": metadata,
    }


def _expected_judge_behavior(signal: dict) -> dict[str, Any]:
    dims = list(signal.get("affected_dimensions") or [])
    signal_type = signal.get("signal_type")
    should = {
        "judge_too_lenient": "Judge should fail or sharply downgrade this output when high/critical rule checks fail.",
        "judge_too_strict": "Judge should not fail without concrete evidence, failed_dimensions, and specific failure_reasons.",
        "judge_rule_conflict": "Judge should align dimension scores with failed rule-check dimensions or explain an evidence-backed override.",
        "judge_missing_dimension": "Judge should include the affected dimensions in dimension_scores and failed_dimensions when evidence supports failure.",
        "judge_unstable_on_duplicates": "Judge should score similar duplicate failures consistently.",
        "judge_low_confidence": "Judge should surface uncertainty and rely on calibration examples for high-severity ambiguous cases.",
        "judge_parse_or_schema_error": "Judge should return valid JSON matching the correctness judge schema.",
    }.get(signal_type, "Judge should make an evidence-grounded decision using the correctness rubric.")
    return {
        "should": should,
        "should_fail_dimensions": dims,
        "should_not_misjudge_dimensions": [dim for dim in dims if dim],
        "reason": signal.get("disagreement_reason") or signal.get("recommendation"),
    }


def _judge_raw(judge_result: dict) -> dict:
    raw = judge_result.get("raw") if isinstance(judge_result, dict) else {}
    if isinstance(raw, dict):
        merged = {**judge_result, **raw}
        return merged
    return judge_result if isinstance(judge_result, dict) else {}


def _judge_passed(judge: dict) -> bool | None:
    value = judge.get("passed")
    return value if isinstance(value, bool) else None


def _judge_score(judge: dict) -> float:
    value = judge.get("overall_score", judge.get("score", 0))
    return float(value) if isinstance(value, (int, float)) else 0.0


def _judge_confidence(judge: dict) -> float:
    value = judge.get("confidence", 1)
    return float(value) if isinstance(value, (int, float)) else 1.0


def _check_severity(check: dict) -> str:
    return str(check.get("severity") or check.get("level") or "low")


def _severity_rank(severity: str) -> int:
    normalized = "critical" if severity == "fatal" else severity
    return SEVERITY_ORDER.get(normalized, 1)


def _dimensions_from_checks(checks: list[dict]) -> list[str]:
    dims = []
    for check in checks:
        details = check.get("details") or {}
        dim = details.get("dimension") or check.get("dimension") or check.get("check_name")
        if dim:
            dims.append(str(dim))
    return list(dict.fromkeys(dims))


def _generic_reasons(judge: dict) -> bool:
    reasons = judge.get("failure_reasons") or []
    if not reasons:
        return True
    text = " ".join(str(reason).lower() for reason in reasons)
    return any(word in text for word in ["bad", "poor", "不够好", "问题", "一般"]) and len(text) < 80


def _rule_judge_conflict(checks: list[dict], judge: dict) -> bool:
    scores = judge.get("dimension_scores") or {}
    for dim in _dimensions_from_checks(checks):
        if scores.get(dim) is not None and isinstance(scores.get(dim), (int, float)) and float(scores[dim]) >= 0.8:
            return True
    return False


def _conflicting_dimensions(checks: list[dict], judge: dict) -> list[str]:
    scores = judge.get("dimension_scores") or {}
    return [dim for dim in _dimensions_from_checks(checks) if isinstance(scores.get(dim), (int, float)) and float(scores[dim]) >= 0.8]


def _parse_or_schema_error(judge: dict) -> bool:
    if not judge:
        return False
    return bool(judge.get("parse_failed") or judge.get("schema_error") or judge.get("missing_required_fields") or judge.get("error_code") in {"parse_failed", "schema_error"})


def _signal_duplicate_key(signal_type: str, failure: dict, affected_dimensions: list[str]) -> str:
    dims = ",".join(sorted(affected_dimensions))
    return f"{failure.get('agent_name')}:{signal_type}:{dims}:{failure.get('failure_type')}:{failure.get('scenario_id')}"


def _most_common_dimension(signals: list[dict], signal_type: str, fallback: Counter) -> str | None:
    counter = Counter(dim for item in signals if item.get("signal_type") == signal_type for dim in (item.get("affected_dimensions") or []))
    if counter:
        return counter.most_common(1)[0][0]
    return fallback.most_common(1)[0][0] if fallback else None
