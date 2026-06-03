from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_agent_change_impact_service, get_agent_eval_service, get_agent_regression_gate_service, get_agent_regression_profile_service, require_admin_session
from app.core.auth import AuthSession
from app.services.agent_change_impact_service import AgentChangeImpactService
from app.services.agent_eval_service import AgentEvalService
from app.services.agent_regression_gate_service import AgentRegressionGateService
from app.services.agent_regression_profile_service import RegressionProfileService

router = APIRouter(prefix="/admin/agent-eval", tags=["admin-agent-eval"])


class EvalRunRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list)
    agent_name: str | None = None
    replay_ids: list[str] = Field(default_factory=list)
    mode: str = "static"
    name: str | None = None


class EvalCaseUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    severity: str | None = None
    category: str | None = None
    input: dict | None = None
    mock_context: dict | None = None
    mock_tool_outputs: dict | None = None
    expected_behavior: dict | None = None
    expected_output_fields: list[str] | None = None
    expected_tools: list[str] | None = None
    expected_data_limitations: list[str] | None = None
    forbidden_behavior: list[str] | None = None
    scoring_rubric: dict | None = None
    notes: str | None = None
    metadata: dict | None = None
    judge_enabled: bool | None = None
    judge_rubric: dict | None = None
    judge_model_config: dict | None = None
    eval_scope: str | None = None
    node_name: str | None = None
    source_run_id: str | None = None
    source_llm_call_id: str | None = None
    source_node_trace_id: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model: str | None = None


class EvalCaseBulkUpdateRequest(BaseModel):
    case_ids: list[str] = Field(..., min_length=1)
    updates: dict


class EvalCaseCloneRequest(BaseModel):
    title: str | None = None
    enabled: bool | None = None


class EvalCaseArchiveRequest(BaseModel):
    reason: str | None = None


class BadCaseFeedbackCreateRequest(BaseModel):
    source_type: str
    source_id: str
    title: str
    agent_name: str = ""
    description: str = ""
    issue_type: str = "other"
    severity: str = "medium"
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    replay_id: str | None = None
    run_id: str | None = None
    eval_run_id: str | None = None
    case_id: str | None = None
    result_case_id: str | None = None
    evidence: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class BadCaseFeedbackUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    issue_type: str | None = None
    severity: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    notes: str | None = None
    metadata: dict | None = None


class CreateCaseFromFeedbackRequest(BaseModel):
    title: str | None = None
    enabled: bool | None = None


class AgentRegressionRunRequest(BaseModel):
    agent_name: str
    mode: str = "static"
    case_tag: str | None = None
    severity: str | None = None
    category: str | None = None
    include_disabled: bool = False
    include_judge: bool = False
    limit: int = 100
    gate: dict[str, Any] = Field(default_factory=dict)
    trigger: str = "manual"
    prompt: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    git: dict[str, Any] = Field(default_factory=dict)
    baseline_eval_run_id: str | None = None
    name: str | None = None
    include_node_eval: bool = False
    node_name: str | None = None


@router.get("/coverage")
def get_eval_coverage(
    agent_name: str | None = None,
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    limit: int = Query(default=1000, ge=1, le=5000),
    include_disabled: bool = True,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.get_eval_coverage(
        agent_name=agent_name, hours=hours, limit=limit, include_disabled=include_disabled,
    )


@router.get("/correctness-summary")
def get_correctness_summary(
    agent_name: str | None = None,
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    limit: int = Query(default=1000, ge=1, le=5000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    """Eval P3 Stage 06: 跨 Agent 正确性报告。

    返回 summary / by_agent / by_dimension / recent_failures。
    """
    return service.get_correctness_summary(
        agent_name=agent_name, hours=hours, limit=limit,
    )


@router.get("/cases")
def list_eval_cases(
    agent_name: str | None = None,
    source: str | None = None,
    enabled: bool | None = None,
    severity: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    source_replay_id: str | None = None,
    eval_scope: str | None = None,
    node_name: str | None = None,
    source_run_id: str | None = None,
    source_llm_call_id: str | None = None,
    prompt_key: str | None = None,
    model: str | None = None,
    include_archived: bool = False,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return {
        "items": service.list_cases(
            agent_name=agent_name, source=source, enabled=enabled,
            severity=severity, category=category, tag=tag,
            source_replay_id=source_replay_id,
            eval_scope=eval_scope, node_name=node_name,
            source_run_id=source_run_id, source_llm_call_id=source_llm_call_id,
            prompt_key=prompt_key, model=model,
            include_archived=include_archived,
            query=query, limit=limit,
        )
    }


@router.patch("/cases/bulk")
def bulk_update_eval_cases(
    payload: EvalCaseBulkUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        return service.bulk_update_cases(payload.case_ids, payload.updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/cases/{case_id}")
def get_eval_case(
    case_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    case = service.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return case


@router.post("/cases")
def create_eval_case(
    payload: dict,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        return service.create_case(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/cases/{case_id}")
def update_eval_case(
    case_id: str,
    payload: EvalCaseUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        result = service.update_case(case_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return result


@router.post("/cases/{case_id}/clone")
def clone_eval_case(
    case_id: str,
    payload: EvalCaseCloneRequest = EvalCaseCloneRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    result = service.clone_case(case_id, payload.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return result


@router.patch("/cases/{case_id}/archive")
def archive_eval_case(
    case_id: str,
    payload: EvalCaseArchiveRequest = EvalCaseArchiveRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    result = service.archive_case(case_id, reason=payload.reason)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return result


@router.patch("/cases/{case_id}/unarchive")
def unarchive_eval_case(
    case_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    result = service.unarchive_case(case_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return result


@router.post("/cases/seed")
def seed_eval_cases(
    force: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.seed_builtin_cases(force=force)


@router.post("/cases/from-replay/{replay_id}")
def create_eval_case_from_replay(
    replay_id: str,
    save: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    case = service.build_case_from_replay(replay_id, save=save)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay snapshot not found")
    return case


@router.post("/cases/from-llm-call/{call_id}")
def create_eval_case_from_llm_call(
    call_id: str,
    save: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        case = service.build_case_from_llm_call(call_id, save=save)
    except ValueError as exc:
        detail = str(exc)
        if "node_name" in detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM call not found")
    return case


@router.post("/cases/from-node-trace/{run_id}/{node_trace_id}")
def create_eval_case_from_node_trace(
    run_id: str,
    node_trace_id: str,
    save: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        case = service.build_case_from_node_trace(run_id, node_trace_id, save=save)
    except ValueError as exc:
        detail = str(exc)
        if "node_name" in detail or "node_trace" in detail or "run_id" in detail:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run or node trace not found")
    return case


@router.post("/runs")
def run_eval(
    payload: EvalRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.run_eval(
        case_ids=payload.case_ids,
        agent_name=payload.agent_name,
        replay_ids=payload.replay_ids,
        mode=payload.mode,
        name=payload.name,
    )


@router.post("/regression-runs")
def create_agent_regression_run(
    payload: AgentRegressionRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        return service.run_agent_regression_eval(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/runs")
def list_eval_runs(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    agent_name: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.list_eval_runs(hours=hours, agent_name=agent_name, limit=limit)


@router.get("/runs/compare")
def compare_eval_runs(
    baseline_run_id: str = Query(...),
    candidate_run_id: str = Query(...),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    result = service.compare_eval_runs(baseline_run_id, candidate_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or both eval runs not found")
    return result


@router.get("/runs/{eval_run_id}")
def get_eval_run(
    eval_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    run = service.get_eval_run(eval_run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found")
    return run


# ── Bad Case Feedback ────────────────────────────────────────────────


@router.get("/feedback")
def list_feedback(
    status: str | None = None,
    source_type: str | None = None,
    agent_name: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    issue_type: str | None = None,
    tag: str | None = None,
    eval_run_id: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.list_feedback(
        status=status, source_type=source_type, agent_name=agent_name,
        severity=severity, category=category, issue_type=issue_type,
        tag=tag, eval_run_id=eval_run_id, query=query, limit=limit,
    )


@router.post("/feedback")
def create_feedback(
    payload: BadCaseFeedbackCreateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        return service.create_feedback(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/feedback/{feedback_id}")
def get_feedback(
    feedback_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    feedback = service.get_feedback(feedback_id)
    if feedback is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    return feedback


@router.patch("/feedback/{feedback_id}")
def update_feedback(
    feedback_id: str,
    payload: BadCaseFeedbackUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        result = service.update_feedback(feedback_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    return result


@router.post("/feedback/{feedback_id}/create-case")
def create_eval_case_from_feedback(
    feedback_id: str,
    payload: CreateCaseFromFeedbackRequest = CreateCaseFromFeedbackRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    result = service.create_eval_case_from_feedback(feedback_id, payload.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    return result


@router.post("/runs/{eval_run_id}/feedback-from-failures")
def create_feedback_from_eval_run_failures(
    eval_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    try:
        return service.create_feedback_from_eval_run_failures(eval_run_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "Eval run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ── Regression Profiles ─────────────────────────────────────────────


class RegressionProfileUpsertRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    case_tag: str | None = None
    severity: str | None = None
    category: str | None = None
    include_disabled: bool | None = None
    include_judge: bool | None = None
    include_node_eval: bool | None = None
    node_name: str | None = None
    limit: int | None = None
    gate: dict[str, Any] | None = None
    trigger_policy: dict[str, Any] | None = None
    notes: str | None = None


class BuildPayloadRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


@router.get("/regression-profiles")
def list_regression_profiles(
    enabled: bool | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: RegressionProfileService = Depends(get_agent_regression_profile_service),
) -> dict:
    return service.list_regression_profiles(enabled=enabled, query=query, limit=limit)


@router.get("/regression-profiles/{agent_name}")
def get_regression_profile(
    agent_name: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: RegressionProfileService = Depends(get_agent_regression_profile_service),
) -> dict:
    profile = service.get_regression_profile(agent_name)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regression profile not found")
    return profile


@router.put("/regression-profiles/{agent_name}")
def upsert_regression_profile(
    agent_name: str,
    payload: RegressionProfileUpsertRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: RegressionProfileService = Depends(get_agent_regression_profile_service),
) -> dict:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        return service.upsert_regression_profile(agent_name, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/regression-profiles/{agent_name}/disable")
def disable_regression_profile(
    agent_name: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: RegressionProfileService = Depends(get_agent_regression_profile_service),
) -> dict:
    result = service.disable_regression_profile(agent_name)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regression profile not found")
    return result


@router.post("/regression-profiles/{agent_name}/build-payload")
def build_regression_payload(
    agent_name: str,
    payload: BuildPayloadRequest = BuildPayloadRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: RegressionProfileService = Depends(get_agent_regression_profile_service),
) -> dict:
    try:
        return service.build_regression_payload_from_profile(agent_name, payload.overrides or None)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Impact Analysis ──────────────────────────────────────────────────


class ImpactAnalysisChangedFilesRequest(BaseModel):
    changed_files: list[str] = Field(..., min_length=1)
    base_ref: str | None = None
    head_ref: str | None = None
    include_payload: bool = True


class ImpactAnalysisGitDiffRequest(BaseModel):
    base_ref: str
    head_ref: str
    include_payload: bool = True


@router.post("/impact-analysis/changed-files")
def analyze_impact_changed_files(
    payload: ImpactAnalysisChangedFilesRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentChangeImpactService = Depends(get_agent_change_impact_service),
) -> dict:
    try:
        return service.analyze_changed_files(
            payload.changed_files,
            base_ref=payload.base_ref,
            head_ref=payload.head_ref,
            include_payload=payload.include_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/impact-analysis/git-diff")
def analyze_impact_git_diff(
    payload: ImpactAnalysisGitDiffRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentChangeImpactService = Depends(get_agent_change_impact_service),
) -> dict:
    try:
        return service.analyze_git_diff(
            payload.base_ref,
            payload.head_ref,
            include_payload=payload.include_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Regression Gate ──────────────────────────────────────────────────


class RegressionGateDryRunRequest(BaseModel):
    changed_files: list[str] | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    max_agents: int = 10


@router.post("/regression-gate/dry-run")
def regression_gate_dry_run(
    payload: RegressionGateDryRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentRegressionGateService = Depends(get_agent_regression_gate_service),
) -> dict:
    try:
        return service.run_regression_gate(
            changed_files=payload.changed_files,
            base_ref=payload.base_ref,
            head_ref=payload.head_ref,
            dry_run=True,
            max_agents=payload.max_agents,
            save_report=True,
            trigger="api_dry_run",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/regression-gate/reports")
def list_regression_gate_reports(
    status: str | None = None,
    trigger: str | None = None,
    ok: bool | None = None,
    dry_run: bool | None = None,
    agent_name: str | None = None,
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentRegressionGateService = Depends(get_agent_regression_gate_service),
) -> dict:
    return service.list_reports(
        status=status, trigger=trigger, ok=ok, dry_run=dry_run,
        agent_name=agent_name, hours=hours, limit=limit,
    )


@router.get("/regression-gate/reports/{report_id}")
def get_regression_gate_report(
    report_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentRegressionGateService = Depends(get_agent_regression_gate_service),
) -> dict:
    report = service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate report not found")
    return report
