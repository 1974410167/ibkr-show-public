from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_agent_change_impact_service, get_agent_eval_service, get_agent_regression_gate_service, get_agent_regression_profile_service, get_baseline_health_report_service, get_eval_failure_mining_service, get_eval_simulation_service, get_failure_to_eval_case_service, get_judge_calibration_service, require_admin_session
from app.agents.eval_simulation_scenarios import (
    filter_synthetic_scenarios,
    get_synthetic_scenario,
    summarize_synthetic_scenarios,
)
from app.core.auth import AuthSession
from app.services.agent_change_impact_service import AgentChangeImpactService
from app.services.agent_eval_service import AgentEvalService
from app.services.agent_regression_gate_service import AgentRegressionGateService
from app.services.agent_regression_profile_service import RegressionProfileService
from app.services.eval_simulation_service import SyntheticSimulationService
from app.services.eval_failure_mining_service import SyntheticFailureMiningService
from app.services.eval_failure_to_case_service import FailureToEvalCaseService
from app.services.eval_baseline_health_service import BaselineHealthReportService
from app.services.eval_judge_calibration_service import JudgeCalibrationService

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


class SyntheticSimulationRunRequest(BaseModel):
    scenario_ids: list[str] = Field(default_factory=list)
    agent_name: str | None = None
    tag: str | None = None
    severity: str | None = None
    category: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    dry_run: bool = True
    executor_mode: str = "auto"
    async_run: bool = False
    name: str | None = None


class FailureMiningRunRequest(BaseModel):
    simulation_run_id: str
    include_dry_run_results: bool = False
    include_judge: bool = False
    judge_model_config: dict[str, Any] = Field(default_factory=dict)
    min_severity: str | None = None
    max_failures: int = Field(default=100, ge=1, le=500)
    deduplicate: bool = True
    name: str | None = None


class FailureCasePreviewRequest(BaseModel):
    enabled: bool = False


class FailureCaseConvertRequest(BaseModel):
    enabled: bool = False
    force: bool = False


class FailureCaseBatchConvertRequest(BaseModel):
    failure_mining_run_id: str | None = None
    failure_ids: list[str] = Field(default_factory=list)
    min_priority: int = 80
    max_cases: int = Field(default=20, ge=1, le=100)
    enabled: bool = False
    force: bool = False


class BaselineHealthReportRequest(BaseModel):
    simulation_run_id: str | None = None
    failure_mining_run_id: str | None = None
    include_converted_cases: bool = True
    include_correctness_summary: bool = True
    name: str | None = None


class JudgeCalibrationRunRequest(BaseModel):
    failure_mining_run_id: str | None = None
    baseline_report_id: str | None = None
    agent_name: str | None = None
    min_priority: int = Field(default=50, ge=0, le=100)
    deduplicate: bool = True
    name: str | None = None


class JudgeCalibrationCasePreviewRequest(BaseModel):
    enabled: bool = False


class JudgeCalibrationCaseCreateRequest(BaseModel):
    enabled: bool = False
    force: bool = False


class JudgeCalibrationBatchCreateRequest(BaseModel):
    calibration_run_id: str
    min_priority: int = Field(default=70, ge=0, le=100)
    max_cases: int = Field(default=20, ge=1, le=100)
    enabled: bool = False
    force: bool = False


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


@router.get("/synthetic-scenarios")
def list_admin_synthetic_scenarios(
    agent_name: str | None = None,
    tag: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
) -> dict:
    return {
        "items": filter_synthetic_scenarios(
            agent_name=agent_name,
            tag=tag,
            severity=severity,
            category=category,
            limit=limit,
        ),
        "summary": summarize_synthetic_scenarios(),
    }


@router.get("/synthetic-scenarios/{scenario_id}")
def get_admin_synthetic_scenario(
    scenario_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
) -> dict:
    scenario = get_synthetic_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Synthetic scenario not found")
    return scenario


@router.post("/simulations/run")
def run_synthetic_simulation(
    payload: SyntheticSimulationRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticSimulationService = Depends(get_eval_simulation_service),
) -> dict:
    try:
        if payload.async_run:
            return service.start_scenarios_async(
                scenario_ids=payload.scenario_ids or None,
                agent_name=payload.agent_name,
                tag=payload.tag,
                severity=payload.severity,
                category=payload.category,
                limit=payload.limit,
                dry_run=payload.dry_run,
                executor_mode=payload.executor_mode,
                name=payload.name,
            )
        return service.run_scenarios(
            scenario_ids=payload.scenario_ids or None,
            agent_name=payload.agent_name,
            tag=payload.tag,
            severity=payload.severity,
            category=payload.category,
            limit=payload.limit,
            dry_run=payload.dry_run,
            executor_mode=payload.executor_mode,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/simulations/runs")
def list_synthetic_simulation_runs(
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticSimulationService = Depends(get_eval_simulation_service),
) -> dict:
    return {"items": service.list_runs(agent_name=agent_name, status=status, limit=limit)}


@router.get("/simulations/runs/{simulation_run_id}")
def get_synthetic_simulation_run(
    simulation_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticSimulationService = Depends(get_eval_simulation_service),
) -> dict:
    result = service.get_run_with_results(simulation_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Synthetic simulation run not found")
    return result


@router.get("/simulations/results/{simulation_result_id}")
def get_synthetic_simulation_result(
    simulation_result_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticSimulationService = Depends(get_eval_simulation_service),
) -> dict:
    result = service.get_result(simulation_result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Synthetic simulation result not found")
    return result


@router.post("/failure-mining/run")
def run_failure_mining(
    payload: FailureMiningRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticFailureMiningService = Depends(get_eval_failure_mining_service),
) -> dict:
    try:
        return service.mine_simulation_run(
            payload.simulation_run_id,
            include_dry_run_results=payload.include_dry_run_results,
            include_judge=payload.include_judge,
            judge_model_config=payload.judge_model_config,
            min_severity=payload.min_severity,
            max_failures=payload.max_failures,
            deduplicate=payload.deduplicate,
            name=payload.name,
        )
    except ValueError as exc:
        if str(exc) == "Simulation run not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/failure-mining/runs")
def list_failure_mining_runs(
    simulation_run_id: str | None = None,
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticFailureMiningService = Depends(get_eval_failure_mining_service),
) -> dict:
    return {
        "items": service.list_failure_mining_runs(
            simulation_run_id=simulation_run_id,
            agent_name=agent_name,
            status=status,
            limit=limit,
        )
    }


@router.get("/failure-mining/runs/{failure_mining_run_id}")
def get_failure_mining_run(
    failure_mining_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticFailureMiningService = Depends(get_eval_failure_mining_service),
) -> dict:
    result = service.get_failure_mining_run_with_failures(failure_mining_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failure mining run not found")
    return result


@router.get("/failure-mining/failures")
def list_failure_mining_failures(
    failure_mining_run_id: str | None = None,
    simulation_run_id: str | None = None,
    agent_name: str | None = None,
    failure_type: str | None = None,
    min_severity: str | None = None,
    should_convert_to_eval_case: bool | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticFailureMiningService = Depends(get_eval_failure_mining_service),
) -> dict:
    return service.list_failure_items(
        failure_mining_run_id=failure_mining_run_id,
        simulation_run_id=simulation_run_id,
        agent_name=agent_name,
        failure_type=failure_type,
        min_severity=min_severity,
        should_convert_to_eval_case=should_convert_to_eval_case,
        limit=limit,
    )


@router.get("/failure-mining/failures/{failure_id}")
def get_failure_mining_failure(
    failure_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: SyntheticFailureMiningService = Depends(get_eval_failure_mining_service),
) -> dict:
    failure = service.get_failure_item(failure_id)
    if failure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failure item not found")
    return failure


@router.post("/failure-mining/failures/{failure_id}/preview-case")
def preview_failure_eval_case(
    failure_id: str,
    payload: FailureCasePreviewRequest = FailureCasePreviewRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: FailureToEvalCaseService = Depends(get_failure_to_eval_case_service),
) -> dict:
    try:
        return service.preview_case_from_failure(failure_id, enabled=payload.enabled)
    except ValueError as exc:
        if str(exc) in {"Failure item not found", "Synthetic scenario not found", "Simulation result not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/failure-mining/failures/{failure_id}/convert-case")
def convert_failure_eval_case(
    failure_id: str,
    payload: FailureCaseConvertRequest = FailureCaseConvertRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: FailureToEvalCaseService = Depends(get_failure_to_eval_case_service),
) -> dict:
    try:
        return service.convert_failure_to_case(failure_id, enabled=payload.enabled, force=payload.force)
    except ValueError as exc:
        if str(exc) in {"Failure item not found", "Synthetic scenario not found", "Simulation result not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/failure-mining/convert-cases")
def batch_convert_failure_eval_cases(
    payload: FailureCaseBatchConvertRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: FailureToEvalCaseService = Depends(get_failure_to_eval_case_service),
) -> dict:
    return service.batch_convert_failures(
        failure_mining_run_id=payload.failure_mining_run_id,
        failure_ids=payload.failure_ids or None,
        min_priority=payload.min_priority,
        max_cases=payload.max_cases,
        enabled=payload.enabled,
        force=payload.force,
    )


@router.post("/baseline-health/reports")
def create_baseline_health_report(
    payload: BaselineHealthReportRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: BaselineHealthReportService = Depends(get_baseline_health_report_service),
) -> dict:
    return service.generate_report(
        simulation_run_id=payload.simulation_run_id,
        failure_mining_run_id=payload.failure_mining_run_id,
        include_converted_cases=payload.include_converted_cases,
        include_correctness_summary=payload.include_correctness_summary,
        name=payload.name,
    )


@router.get("/baseline-health/reports")
def list_baseline_health_reports(
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: BaselineHealthReportService = Depends(get_baseline_health_report_service),
) -> dict:
    return {"items": service.list_reports(agent_name=agent_name, status=status, limit=limit)}


@router.get("/baseline-health/reports/{report_id}")
def get_baseline_health_report(
    report_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: BaselineHealthReportService = Depends(get_baseline_health_report_service),
) -> dict:
    report = service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline health report not found")
    return report


@router.get("/baseline-health/reports/{report_id}/markdown")
def get_baseline_health_report_markdown(
    report_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: BaselineHealthReportService = Depends(get_baseline_health_report_service),
) -> dict:
    report = service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline health report not found")
    return {"report_id": report_id, "markdown_report": report.get("markdown_report") or ""}


@router.post("/judge-calibration/run")
def run_judge_calibration(
    payload: JudgeCalibrationRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    try:
        return service.detect_calibration_signals(
            failure_mining_run_id=payload.failure_mining_run_id,
            baseline_report_id=payload.baseline_report_id,
            agent_name=payload.agent_name,
            min_priority=payload.min_priority,
            deduplicate=payload.deduplicate,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/judge-calibration/runs")
def list_judge_calibration_runs(
    agent_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    return {"items": service.list_runs(agent_name=agent_name, status=status, limit=limit)}


@router.get("/judge-calibration/runs/{calibration_run_id}")
def get_judge_calibration_run(
    calibration_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    result = service.get_run_with_signals(calibration_run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Judge calibration run not found")
    return result


@router.get("/judge-calibration/signals")
def list_judge_calibration_signals(
    calibration_run_id: str | None = None,
    agent_name: str | None = None,
    signal_type: str | None = None,
    min_priority: int | None = Query(default=None, ge=0, le=100),
    should_create_calibration_case: bool | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    return service.list_signals(
        calibration_run_id=calibration_run_id,
        agent_name=agent_name,
        signal_type=signal_type,
        min_priority=min_priority,
        should_create_calibration_case=should_create_calibration_case,
        limit=limit,
    )


@router.get("/judge-calibration/signals/{signal_id}")
def get_judge_calibration_signal(
    signal_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    signal = service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Judge calibration signal not found")
    return signal


@router.post("/judge-calibration/signals/{signal_id}/preview-case")
def preview_judge_calibration_case(
    signal_id: str,
    payload: JudgeCalibrationCasePreviewRequest = JudgeCalibrationCasePreviewRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    try:
        return service.preview_calibration_case(signal_id, enabled=payload.enabled)
    except ValueError as exc:
        if str(exc) == "Judge calibration signal not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/judge-calibration/signals/{signal_id}/create-case")
def create_judge_calibration_case(
    signal_id: str,
    payload: JudgeCalibrationCaseCreateRequest = JudgeCalibrationCaseCreateRequest(),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    try:
        return service.create_calibration_case(signal_id, enabled=payload.enabled, force=payload.force)
    except ValueError as exc:
        if str(exc) == "Judge calibration signal not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/judge-calibration/create-cases")
def batch_create_judge_calibration_cases(
    payload: JudgeCalibrationBatchCreateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: JudgeCalibrationService = Depends(get_judge_calibration_service),
) -> dict:
    return service.batch_create_calibration_cases(
        calibration_run_id=payload.calibration_run_id,
        min_priority=payload.min_priority,
        max_cases=payload.max_cases,
        enabled=payload.enabled,
        force=payload.force,
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
