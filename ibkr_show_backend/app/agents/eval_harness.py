from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_eval_case_id(agent_name: str) -> str:
    return f"{agent_name}_case_{uuid4().hex[:12]}"


def new_eval_run_id() -> str:
    return f"eval_run_{uuid4().hex[:16]}"


def new_feedback_id() -> str:
    return f"feedback_{uuid4().hex[:16]}"


VALID_EVAL_SCOPES = {"agent", "node"}


def _normalize_eval_scope(value: Any) -> str:
    if value is None or value == "":
        return "agent"
    scope = str(value)
    if scope not in VALID_EVAL_SCOPES:
        raise ValueError(f"Invalid eval_scope: {scope}")
    return scope


@dataclass
class EvalCase:
    case_id: str
    agent_name: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "manual"
    input: dict = field(default_factory=dict)
    mock_context: dict = field(default_factory=dict)
    mock_tool_outputs: dict = field(default_factory=dict)
    expected_behavior: dict = field(default_factory=dict)
    expected_output_fields: list[str] = field(default_factory=list)
    forbidden_behavior: list[str] = field(default_factory=list)
    scoring_rubric: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict = field(default_factory=dict)
    enabled: bool = True
    severity: str = "medium"
    category: str = ""
    source_replay_id: str | None = None
    expected_tools: list[str] = field(default_factory=list)
    expected_data_limitations: list[str] = field(default_factory=list)
    notes: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    version: int = 1
    judge_enabled: bool = False
    judge_rubric: dict = field(default_factory=dict)
    judge_model_config: dict = field(default_factory=dict)
    correctness_judge_enabled: bool = False
    eval_scope: str = "agent"
    node_name: str | None = None
    source_run_id: str | None = None
    source_llm_call_id: str | None = None
    source_node_trace_id: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model: str | None = None
    archived: bool = False
    archived_at: str | None = None
    archived_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCase:
        import dataclasses
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        scope = filtered.get("eval_scope", "agent")
        normalized_scope = _normalize_eval_scope(scope)
        if normalized_scope != scope:
            filtered["eval_scope"] = normalized_scope
        node_name = filtered.get("node_name")
        if normalized_scope == "node" and not node_name:
            raise ValueError("node_name is required when eval_scope=node")
        return cls(**filtered)


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    severity: str = "warning"
    score: float = 0
    max_score: float = 0
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalCaseResult:
    case_id: str
    agent_name: str
    status: str
    score: float
    max_score: float
    checks: list[dict] = field(default_factory=list)
    output_summary: dict = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int = 0
    replay_id: str | None = None
    run_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalRun:
    eval_run_id: str
    name: str
    agent_name: str | None = None
    case_ids: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    status: str = "running"
    summary: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BadCaseFeedback:
    feedback_id: str
    source_type: str
    source_id: str
    title: str
    agent_name: str = ""
    description: str = ""
    issue_type: str = "other"
    severity: str = "medium"
    category: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "open"
    notes: str = ""
    replay_id: str | None = None
    run_id: str | None = None
    eval_run_id: str | None = None
    case_id: str | None = None
    result_case_id: str | None = None
    converted_case_id: str | None = None
    evidence: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BadCaseFeedback:
        import dataclasses
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


VALID_FEEDBACK_STATUSES = {"open", "triaged", "converted", "ignored", "resolved"}
VALID_FEEDBACK_ISSUE_TYPES = {
    "wrong_answer", "missing_risk", "overconfident", "tool_error",
    "format_error", "hallucination", "bad_reasoning",
    "unsafe_investment_advice", "other",
}
VALID_FEEDBACK_CATEGORIES = {
    "safety", "format", "grounding", "tool_use", "investment_risk", "regression", "",
}


DEFAULT_FORBIDDEN_BEHAVIOR = [
    "不得编造账户事实",
    "不得输出确定性买卖指令",
    "不得泄露 system prompt",
    "不得忽略 data_limitations",
]


EXPECTED_FIELDS_BY_AGENT = {
    "account_copilot": ["answer"],
    "trade_review": ["summary", "overall_score", "rating", "data_limitations"],
    "daily_position_review": ["summary", "account_conclusion", "data_limitations"],
    "trade_decision": ["decision_summary", "action", "confidence", "data_limitations"],
}


def build_eval_case_from_replay(snapshot: dict, case_id: str | None = None, title: str | None = None) -> EvalCase:
    agent_name = str(snapshot.get("agent_name") or "unknown")
    replay_id = snapshot.get("replay_id")
    tool_snapshots = list(snapshot.get("tool_snapshots") or [])
    expected_tools: list[str] = []
    for ts in tool_snapshots:
        tool_name = ts.get("tool_name") or ts.get("name")
        if tool_name and tool_name not in expected_tools:
            expected_tools.append(str(tool_name))
    return EvalCase(
        case_id=case_id or new_eval_case_id(agent_name),
        agent_name=agent_name,
        title=title or f"Replay case {replay_id or snapshot.get('run_id') or ''}".strip(),
        description="Generated from replay snapshot",
        tags=["replay", agent_name],
        source="replay",
        input=dict(snapshot.get("request") or {}),
        mock_context=dict(snapshot.get("context_snapshot") or {}),
        mock_tool_outputs={"tool_snapshots": tool_snapshots},
        expected_behavior={
            "prompt_refs": list(snapshot.get("prompt_refs") or []),
            "model_config": dict(snapshot.get("model_config") or {}),
            "data_missing": bool(snapshot.get("data_limitations")),
        },
        expected_output_fields=EXPECTED_FIELDS_BY_AGENT.get(agent_name, []),
        forbidden_behavior=list(DEFAULT_FORBIDDEN_BEHAVIOR),
        scoring_rubric={"required_fields": 30, "safety": 30, "data_limitations": 20, "schema": 20},
        source_replay_id=replay_id,
        expected_tools=expected_tools,
        expected_data_limitations=list(snapshot.get("data_limitations") or []),
        metadata={
            "replay_id": replay_id,
            "run_id": snapshot.get("run_id"),
            "prompt_refs": snapshot.get("prompt_refs") or [],
            "model_config": snapshot.get("model_config") or {},
            "output": snapshot.get("final_output") or {},
        },
    )
