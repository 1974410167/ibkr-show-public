from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_baseline_report_id() -> str:
    return f"baseline_health_report_{uuid4().hex[:16]}"


def new_recommendation_id() -> str:
    return f"baseline_recommendation_{uuid4().hex[:12]}"


@dataclass
class BaselineRecommendation:
    recommendation_id: str
    priority: str
    area: str
    title: str
    rationale: str
    suggested_action: str
    agent_name: str | None = None
    failure_type: str | None = None
    dimension: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureSignal:
    signal_type: str
    confidence: float
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BaselineHealthReport:
    report_id: str
    name: str
    simulation_run_id: str | None = None
    failure_mining_run_id: str | None = None
    generated_at: str = field(default_factory=utc_now_iso)
    status: str = "completed"
    summary: dict[str, Any] = field(default_factory=dict)
    by_agent: list[dict[str, Any]] = field(default_factory=list)
    by_failure_type: list[dict[str, Any]] = field(default_factory=list)
    by_dimension: list[dict[str, Any]] = field(default_factory=list)
    high_priority_failures: list[dict[str, Any]] = field(default_factory=list)
    converted_case_summary: dict[str, Any] = field(default_factory=dict)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    architecture_signals: list[dict[str, Any]] = field(default_factory=list)
    judge_calibration_signals: list[dict[str, Any]] = field(default_factory=list)
    markdown_report: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
