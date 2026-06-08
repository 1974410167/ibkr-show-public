from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.eval_failure_mining import CORE_CONVERSION_TYPES
from app.agents.eval_harness import EXPECTED_FIELDS_BY_AGENT


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_failure_case_draft_id() -> str:
    return f"failure_case_draft_{uuid4().hex[:16]}"


@dataclass
class FailureCaseDraft:
    draft_id: str
    failure_id: str
    agent_name: str
    case_payload: dict[str, Any]
    conversion_reason: str
    conversion_priority: int
    quality_score: float
    quality_warnings: list[str] = field(default_factory=list)
    source_type: str = "synthetic_failure"
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FailureCaseConversionResult:
    failure_id: str
    draft_id: str | None
    case_id: str | None
    status: str
    reason: str
    case_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_eval_case_payload_from_failure(
    failure: dict,
    scenario: dict,
    simulation_result: dict,
    *,
    enabled: bool = False,
    case_tag: str = "failure_mined",
) -> dict[str, Any]:
    failure_type = failure.get("failure_type") or "other"
    agent_name = failure.get("agent_name") or scenario.get("agent_name")
    source_hash = _stable_hash({
        "failure_id": failure.get("failure_id"),
        "agent_name": agent_name,
        "failure_type": failure_type,
        "duplicate_key": failure.get("duplicate_key"),
        "scenario_id": scenario.get("scenario_id"),
    })[:12]
    case_id = f"synthetic_failure_case_{agent_name}_{failure_type}_{source_hash}"
    scenario_tags = list(scenario.get("tags") or [])
    tags = list(dict.fromkeys([
        "synthetic",
        "p3_5",
        case_tag,
        "correctness",
        "regression",
        agent_name,
        failure_type,
        *scenario_tags,
    ]))
    failed_dimensions = list(failure.get("failed_dimensions") or [])
    stress_dimensions = list(scenario.get("stress_dimensions") or [])
    metadata = {
        "p3_5_source": "failure_mining",
        "failure_id": failure.get("failure_id"),
        "failure_mining_run_id": failure.get("failure_mining_run_id"),
        "simulation_run_id": failure.get("simulation_run_id"),
        "simulation_result_id": failure.get("simulation_result_id"),
        "synthetic_scenario_id": scenario.get("scenario_id"),
        "failure_type": failure_type,
        "failure_tags": list(failure.get("failure_tags") or []),
        "failed_dimensions": failed_dimensions,
        "failed_checks": list(failure.get("failed_checks") or []),
        "judge_result": dict(failure.get("judge_result") or {}),
        "conversion_priority": failure.get("conversion_priority"),
        "original_output_excerpt": failure.get("output_excerpt") or "",
        "duplicate_key": failure.get("duplicate_key"),
        "source_agent_output_hash": _stable_hash(simulation_result.get("output") or failure.get("output_excerpt") or ""),
        "correctness_dimensions": list(dict.fromkeys([*failed_dimensions, *stress_dimensions])),
    }
    return {
        "case_id": case_id,
        "agent_name": agent_name,
        "title": f"[Failure Mined] {agent_name} - {failure_type} - {scenario.get('title', scenario.get('scenario_id'))}",
        "description": _build_description(failure, scenario),
        "source": "synthetic_failure",
        "enabled": enabled,
        "severity": failure.get("severity") or scenario.get("severity") or "medium",
        "category": scenario.get("category") or failure_type,
        "tags": tags,
        "input": {
            "user_question": scenario.get("user_question"),
            "synthetic_scenario_id": scenario.get("scenario_id"),
            "original_agent_output": simulation_result.get("output"),
        },
        "mock_context": {
            **dict(scenario.get("mock_context") or {}),
            "user_profile": dict(scenario.get("user_profile") or {}),
            "data_availability": dict(scenario.get("data_availability") or {}),
        },
        "mock_tool_outputs": {},
        "expected_behavior": {
            "expected_good_behavior": list(scenario.get("expected_good_behavior") or []),
            "must_address_failure_type": failure_type,
            "must_avoid_original_failure": True,
            "failed_dimensions": failed_dimensions,
            "recommendation": failure.get("recommendation") or "",
        },
        "expected_output_fields": EXPECTED_FIELDS_BY_AGENT.get(agent_name, []),
        "forbidden_behavior": list(dict.fromkeys([
            *(scenario.get("failure_traps") or []),
            *_forbidden_behavior_for_failure_type(failure_type),
        ])),
        "scoring_rubric": {
            "correctness": 40,
            "risk_and_data_grounding": 30,
            "actionability": 20,
            "format": 10,
        },
        "judge_enabled": bool(failure.get("should_convert_to_eval_case") and failure.get("severity") in {"high", "critical"}),
        "correctness_judge_enabled": True,
        "judge_rubric": {"rubric_key": f"{agent_name}_correctness"},
        "metadata": metadata,
        "source_run_id": failure.get("simulation_run_id"),
        "notes": "Generated as disabled draft by P3.5 failure-to-eval-case conversion.",
    }


def score_failure_case_quality(failure: dict, scenario: dict, simulation_result: dict) -> dict[str, Any]:
    warnings: list[str] = []
    score = 0.0
    severity = failure.get("severity")
    if severity in {"high", "critical"}:
        score += 0.3
    else:
        warnings.append("failure severity is below high")
    if scenario.get("expected_good_behavior"):
        score += 0.2
    else:
        warnings.append("scenario expected_good_behavior is empty")
    if scenario.get("failure_traps"):
        score += 0.2
    else:
        warnings.append("scenario failure_traps is empty")
    if failure.get("failed_checks"):
        score += 0.1
    if failure.get("judge_result"):
        score += 0.1
    if int((failure.get("metadata") or {}).get("duplicate_count") or 1) > 1:
        score += 0.1
    output = simulation_result.get("output")
    if output or failure.get("failure_type") == "format_or_empty_output":
        score += 0.1
    else:
        warnings.append("simulation output is empty")
    if not failure.get("should_convert_to_eval_case"):
        warnings.append("failure is not marked should_convert_to_eval_case")
    if not scenario.get("user_question"):
        warnings.append("scenario user_question is empty")
    if failure.get("failure_type") == "other" and not failure.get("failed_checks") and not failure.get("judge_result"):
        warnings.append("failure_type is other without evidence")
    priority = int(failure.get("conversion_priority") or 0)
    eligible = (
        bool(failure.get("should_convert_to_eval_case"))
        and (severity in {"high", "critical"} or priority >= 80)
        and bool(scenario.get("user_question"))
        and bool(scenario.get("expected_good_behavior"))
        and bool(scenario.get("failure_traps"))
        and bool(output or failure.get("output_excerpt") or failure.get("failure_type") == "format_or_empty_output")
        and (failure.get("failure_type") != "other" or bool(failure.get("failed_checks") or failure.get("judge_result")))
        and score >= 0.6
    )
    return {"quality_score": min(score, 1.0), "warnings": warnings, "eligible": eligible}


def build_case_duplicate_key(failure: dict, scenario: dict) -> str:
    base = failure.get("duplicate_key")
    if base:
        return str(base)
    normalized_question = " ".join(str(scenario.get("user_question") or "").lower().split())
    return _stable_hash({
        "agent_name": failure.get("agent_name"),
        "failure_type": failure.get("failure_type"),
        "category": scenario.get("category"),
        "user_question": normalized_question,
    })


def _build_description(failure: dict, scenario: dict) -> str:
    return "\n".join([
        f"Original synthetic question: {scenario.get('user_question', '')}",
        f"Failure type: {failure.get('failure_type', '')}",
        f"Failure severity: {failure.get('severity', '')}",
        f"Failure recommendation: {failure.get('recommendation', '')}",
        "Why this should be an EvalCase: this failure captures a synthetic stress pattern that should not regress in future agent outputs.",
    ])


def _forbidden_behavior_for_failure_type(failure_type: str) -> list[str]:
    return {
        "data_insufficient_but_confident": ["不得在数据不足时给确定性结论"],
        "weak_signal_overstatement": ["不得把弱催化包装成强买入"],
        "hallucinated_account_data": ["不得编造账户数据"],
        "result_only_trade_review": ["不得只用结果判断交易对错"],
        "hindsight_bias": ["不得事后诸葛亮式复盘"],
        "irrelevant_news_attribution": ["不得把无关新闻强行归因"],
        "missing_risk_control": ["不得缺少风险、仓位和失效条件"],
        "missing_position_sizing": ["不得缺少仓位上限和分批计划"],
    }.get(failure_type, [])


def _stable_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
