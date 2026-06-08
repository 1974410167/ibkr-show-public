from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VALID_SIMULATION_RUN_STATUSES = {"running", "completed", "failed", "completed_with_errors"}
VALID_SIMULATION_RESULT_STATUSES = {"passed", "failed", "skipped", "error"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_simulation_run_id() -> str:
    return f"simulation_run_{uuid4().hex[:16]}"


def new_simulation_result_id() -> str:
    return f"simulation_result_{uuid4().hex[:16]}"


@dataclass
class SyntheticSimulationRun:
    simulation_run_id: str
    name: str
    scenario_ids: list[str] = field(default_factory=list)
    agent_names: list[str] = field(default_factory=list)
    status: str = "running"
    config: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyntheticSimulationResult:
    simulation_result_id: str
    simulation_run_id: str
    scenario_id: str
    agent_name: str
    status: str
    user_question: str
    output: dict[str, Any] | str = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    run_trace: list[dict[str, Any]] = field(default_factory=list)
    node_outputs: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    source_run_id: str | None = None
    source_task_id: str | None = None
    source_document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
