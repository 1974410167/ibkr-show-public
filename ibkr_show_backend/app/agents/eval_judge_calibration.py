from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SIGNAL_TYPES = {
    "judge_too_lenient",
    "judge_too_strict",
    "judge_rule_conflict",
    "judge_missing_dimension",
    "judge_unstable_on_duplicates",
    "judge_low_confidence",
    "judge_parse_or_schema_error",
    "rubric_gap",
    "prompt_gap",
    "other",
}
SEVERITIES = {"low", "medium", "high", "critical"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_calibration_run_id() -> str:
    return f"judge_calibration_run_{uuid4().hex[:16]}"


def new_calibration_signal_id() -> str:
    return f"judge_calibration_signal_{uuid4().hex[:16]}"


def new_calibration_draft_id() -> str:
    return f"judge_calibration_draft_{uuid4().hex[:16]}"


def new_calibration_suggestion_id() -> str:
    return f"judge_calibration_suggestion_{uuid4().hex[:16]}"


@dataclass
class JudgeCalibrationSignal:
    signal_id: str
    signal_type: str
    agent_name: str
    failure_id: str | None = None
    simulation_result_id: str | None = None
    scenario_id: str | None = None
    severity: str = "medium"
    priority: int = 50
    rule_check_status: str = ""
    judge_status: str = ""
    failed_checks: list[dict[str, Any]] = field(default_factory=list)
    judge_result: dict[str, Any] = field(default_factory=dict)
    disagreement_reason: str = ""
    affected_dimensions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    should_create_calibration_case: bool = False
    duplicate_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["signal_type"] not in SIGNAL_TYPES:
            data["signal_type"] = "other"
        if data["severity"] not in SEVERITIES:
            data["severity"] = "medium"
        data["priority"] = max(0, min(int(data["priority"]), 100))
        data["affected_dimensions"] = list(dict.fromkeys(data["affected_dimensions"]))
        return data


@dataclass
class JudgeCalibrationCaseDraft:
    draft_id: str
    signal_id: str
    failure_id: str | None
    agent_name: str
    case_payload: dict[str, Any]
    expected_judge_behavior: dict[str, Any]
    calibration_reason: str
    quality_score: float
    quality_warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JudgeCalibrationRun:
    calibration_run_id: str
    source_type: str
    source_id: str
    status: str = "completed"
    config: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
