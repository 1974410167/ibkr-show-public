from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.deps import (
    get_agent_task_repository,
    get_longbridge_external_data_client,
    get_trade_decision_account_facts_builder,
    get_trade_decision_agent,
    get_trade_decision_outcome_replay_service,
    get_trade_decision_repository,
    require_authenticated_session,
)
from app.schemas.agent_tasks import AgentTaskListResponse, AgentTaskResponse
from app.core.auth import AuthSession
from app.schemas.trade_decision import (
    TradeDecisionAnalyzeAutoRequest,
    TradeDecisionAnalyzeEntryRequest,
    TradeDecisionAnalyzeHoldingRequest,
    TradeDecisionHealthResponse,
    TradeDecisionHoldingsResponse,
    TradeDecisionListResponse,
    TradeDecisionOutcomeItem,
    TradeDecisionOutcomeListResponse,
    TradeDecisionOutcomeSummary,
    TradeDecisionResult,
)
from app.agents.trade_decision_graph.graph import TRADE_DECISION_GRAPH_EDGES, TRADE_DECISION_GRAPH_NODES
from app.agents.versions import TRADE_DECISION_GRAPH_VERSION
from app.services.llm_service import LLMClientError, LLMConfigError
from app.services.longbridge_service import LongbridgeExternalDataClient, normalize_longbridge_symbol
from app.services.agent_task_repository import AgentTaskRepository
from app.services.agent_task_progress import AgentTaskProgressReporter
from app.services.trade_decision_agent import TradeDecisionAgent, TradeDecisionAgentError
from app.services.trade_decision_quality_analytics import TradeDecisionQualityAnalyticsService
from app.services.trade_decision_outcome_replay import TradeDecisionOutcomeReplayService
from app.services.trade_decision_repository import TradeDecisionRepository

router = APIRouter(prefix="/agent/trade-decision", tags=["trade-decision-agent"])
AGENT_NAME = "trade_decision"


def _public_decision(document: dict, *, include_details: bool = True) -> TradeDecisionResult:
    return TradeDecisionResult(
        id=document["id"],
        decision_type=document["decision_type"],
        symbol=document["symbol"],
        user_question=document.get("user_question"),
        overall_score=document["overall_score"],
        rating=document["rating"],
        action=document["action"],
        draft_action=document.get("draft_action"),
        risk_adjusted_action=document.get("risk_adjusted_action"),
        final_action=document.get("final_action"),
        action_change_reason=document.get("action_change_reason"),
        action_downgrade_chain=document.get("action_downgrade_chain") or [],
        confidence=document["confidence"],
        decision_summary=document["decision_summary"],
        score_detail=document["score_detail"],
        position_advice=document["position_advice"],
        execution_plan=document["execution_plan"],
        key_reasons=document.get("key_reasons") or [],
        major_risks=document.get("major_risks") or [],
        review_warnings=document.get("review_warnings") or [],
        data_limitations=document.get("data_limitations") or [],
        evidence_used=document.get("evidence_used") or [],
        data_source_summary=document.get("data_source_summary") or {},
        card_pack=document.get("card_pack") or {} if include_details else {},
        asset_debate=document.get("asset_debate") or {} if include_details else {},
        trade_plan=document.get("trade_plan") or {} if include_details else {},
        risk_gate=document.get("risk_gate") or {} if include_details else {},
        user_investment_policy_summary=document.get("user_investment_policy_summary"),
        ai_policy_assessment=document.get("ai_policy_assessment") or {},
        decision_quality=document.get("decision_quality") or {},
        run_trace=(document.get("run_trace") or document.get("evidence_pack", {}).get("tool_trace") or []) if include_details else [],
        metadata=document.get("metadata") or {},
        evidence_summary=document.get("evidence_summary") or {} if include_details else {},
        run_trace_summary=document.get("run_trace_summary") or {},
        fallback_used=document.get("fallback_used", False),
        fallback_reason=document.get("fallback_reason"),
        llm_error_summary=document.get("llm_error_summary") or {},
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _public_task(document: dict, *, include_events: bool = True) -> AgentTaskResponse:
    payload = dict(document)
    if not include_events:
        payload["graph_events"] = []
    return AgentTaskResponse(**payload)


def _run_decision_task(task_id: str, task_repository: AgentTaskRepository, agent: TradeDecisionAgent) -> None:
    task = task_repository.mark_running(task_id)
    if task is None:
        return
    payload = task.get("payload") or {}
    try:
        if task.get("task_type") == "entry_decision":
            document = agent.analyze_entry(
                symbol=str(payload.get("symbol") or ""),
                question=payload.get("question"),
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        elif task.get("task_type") == "trade_decision":
            document = agent.analyze_trade_decision(
                symbol=str(payload.get("symbol") or ""),
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        elif task.get("task_type") == "holding_decision":
            document = agent.analyze_holding(
                symbol=str(payload.get("symbol") or ""),
                question=payload.get("question"),
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        else:
            raise TradeDecisionAgentError("TASK_TYPE_INVALID", "Unsupported trade decision task type")
        task_repository.sync_graph_from_run_trace(task_id, document.get("run_trace") or [], final_status="success")
        task_repository.mark_completed(task_id, result_id=document["id"])
    except LLMClientError as exc:
        task_repository.mark_graph_failed(task_id, exc.message)
        task_repository.mark_failed(task_id, error_code=exc.error_code, error_message=exc.message)
    except (ValueError, LLMConfigError, TradeDecisionAgentError) as exc:
        error_code = getattr(exc, "error_code", "TASK_FAILED")
        error_message = getattr(exc, "message", str(exc))
        task_repository.mark_graph_failed(task_id, error_message)
        task_repository.mark_failed(task_id, error_code=error_code, error_message=error_message)
    except Exception as exc:
        task_repository.mark_graph_failed(task_id, str(exc))
        task_repository.mark_failed(task_id, error_code="TASK_FAILED", error_message=str(exc))


@router.get("/health", response_model=TradeDecisionHealthResponse)
def get_trade_decision_health(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
    longbridge_client: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> TradeDecisionHealthResponse:
    longbridge_health = longbridge_client.health()
    return TradeDecisionHealthResponse(
        **agent.health(
            longbridge_configured=bool(longbridge_health.get("configured")),
            trade_review_available=True,
        )
    )


@router.get("/holdings", response_model=TradeDecisionHoldingsResponse)
def list_decision_holdings(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    account_facts_builder=Depends(get_trade_decision_account_facts_builder),
) -> TradeDecisionHoldingsResponse:
    return TradeDecisionHoldingsResponse(items=account_facts_builder.list_current_holdings())


@router.post("/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_trade_decision_task(
    payload: TradeDecisionAnalyzeAutoRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    normalized = normalize_longbridge_symbol(payload.symbol)
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="trade_decision",
        label=f"{normalized} 交易决策",
        payload={"symbol": normalized, "force_refresh": payload.force_refresh},
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=TRADE_DECISION_GRAPH_VERSION,
        nodes=TRADE_DECISION_GRAPH_NODES,
        edges=TRADE_DECISION_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_decision_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.post("/holding/{symbol}/analyze", response_model=TradeDecisionResult)
def analyze_holding_decision(
    symbol: str,
    payload: TradeDecisionAnalyzeHoldingRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
) -> TradeDecisionResult:
    try:
        document = agent.analyze_holding(symbol=symbol, question=payload.question)
        return _public_decision(document)
    except LLMClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error_code": exc.error_code, "message": exc.message}) from exc
    except (ValueError, LLMConfigError, TradeDecisionAgentError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/holding/{symbol}/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_holding_decision_task(
    symbol: str,
    payload: TradeDecisionAnalyzeHoldingRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    normalized = normalize_longbridge_symbol(symbol)
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="holding_decision",
        label=f"{normalized} 持仓决策",
        payload={"symbol": normalized, "question": payload.question, "force_refresh": payload.force_refresh},
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=TRADE_DECISION_GRAPH_VERSION,
        nodes=TRADE_DECISION_GRAPH_NODES,
        edges=TRADE_DECISION_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_decision_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.post("/entry/analyze", response_model=TradeDecisionResult)
def analyze_entry_decision(
    payload: TradeDecisionAnalyzeEntryRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
) -> TradeDecisionResult:
    try:
        document = agent.analyze_entry(symbol=payload.symbol, question=payload.question)
        return _public_decision(document)
    except LLMClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error_code": exc.error_code, "message": exc.message}) from exc
    except (ValueError, LLMConfigError, TradeDecisionAgentError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/entry/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_entry_decision_task(
    payload: TradeDecisionAnalyzeEntryRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeDecisionAgent = Depends(get_trade_decision_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    normalized = normalize_longbridge_symbol(payload.symbol)
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="entry_decision",
        label=f"{normalized} 建仓建议",
        payload={"symbol": normalized, "question": payload.question, "force_refresh": payload.force_refresh},
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=TRADE_DECISION_GRAPH_VERSION,
        nodes=TRADE_DECISION_GRAPH_NODES,
        edges=TRADE_DECISION_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_decision_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.get("/tasks", response_model=AgentTaskListResponse)
def list_trade_decision_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskListResponse:
    return AgentTaskListResponse(items=[_public_task(item, include_events=False) for item in task_repository.list_tasks(agent=AGENT_NAME, limit=limit)])


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
def get_trade_decision_task(
    task_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = task_repository.get_task(task_id)
    if task is None or task.get("agent") != AGENT_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
    return _public_task(task)


@router.get("/recent", response_model=TradeDecisionListResponse)
def list_recent_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    decision_type: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeDecisionRepository = Depends(get_trade_decision_repository),
) -> TradeDecisionListResponse:
    return TradeDecisionListResponse(items=[_public_decision(item, include_details=False) for item in repository.list_recent_decisions(limit, decision_type)])


@router.get("/quality/summary")
def get_trade_decision_quality_summary(
    limit: int = Query(default=200, ge=1, le=1000),
    days: int | None = Query(default=None, ge=1, le=365),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeDecisionRepository = Depends(get_trade_decision_repository),
) -> dict:
    documents = repository.list_recent_decisions_for_quality(limit=limit, days=days)
    return TradeDecisionQualityAnalyticsService().summarize(documents)


def _parse_horizons(value: str | None) -> list[int] | None:
    if not value:
        return None
    horizons: list[int] = []
    for item in value.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            horizon = int(text)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="horizons must be comma-separated integers") from exc
        if horizon <= 0 or horizon > 120:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="horizons must be between 1 and 120")
        horizons.append(horizon)
    return horizons or None


@router.get("/outcome/summary", response_model=TradeDecisionOutcomeSummary)
def get_trade_decision_outcome_summary(
    days: int = Query(default=90, ge=1, le=3650),
    limit: int = Query(default=500, ge=1, le=2000),
    symbol: str | None = Query(default=None),
    decision_type: str | None = Query(default=None),
    horizons: str | None = Query(default=None),
    action_group: str | None = Query(default=None),
    outcome_label: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: TradeDecisionOutcomeReplayService = Depends(get_trade_decision_outcome_replay_service),
) -> TradeDecisionOutcomeSummary:
    return service.build_outcomes(
        days=days,
        limit=limit,
        symbol=symbol,
        decision_type=decision_type,
        horizons=_parse_horizons(horizons),
        action_group=action_group,
        outcome_label=outcome_label,
    ).summary


@router.get("/outcome/list", response_model=TradeDecisionOutcomeListResponse)
def list_trade_decision_outcomes(
    days: int = Query(default=90, ge=1, le=3650),
    limit: int = Query(default=500, ge=1, le=2000),
    symbol: str | None = Query(default=None),
    decision_type: str | None = Query(default=None),
    horizons: str | None = Query(default=None),
    action_group: str | None = Query(default=None),
    outcome_label: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: TradeDecisionOutcomeReplayService = Depends(get_trade_decision_outcome_replay_service),
) -> TradeDecisionOutcomeListResponse:
    return service.build_outcomes(
        days=days,
        limit=limit,
        symbol=symbol,
        decision_type=decision_type,
        horizons=_parse_horizons(horizons),
        action_group=action_group,
        outcome_label=outcome_label,
    )


@router.get("/outcome/{decision_id}", response_model=TradeDecisionOutcomeItem)
def get_trade_decision_outcome(
    decision_id: str,
    horizons: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: TradeDecisionOutcomeReplayService = Depends(get_trade_decision_outcome_replay_service),
) -> TradeDecisionOutcomeItem:
    outcome = service.get_outcome(decision_id, horizons=_parse_horizons(horizons))
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade decision not found")
    return outcome


@router.get("/symbol/{symbol}", response_model=TradeDecisionListResponse)
def list_symbol_decisions(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeDecisionRepository = Depends(get_trade_decision_repository),
) -> TradeDecisionListResponse:
    normalized = normalize_longbridge_symbol(symbol)
    return TradeDecisionListResponse(items=[_public_decision(item, include_details=False) for item in repository.list_symbol_decisions(normalized, limit)])


@router.get("/{decision_id}", response_model=TradeDecisionResult)
def get_decision_detail(
    decision_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeDecisionRepository = Depends(get_trade_decision_repository),
) -> TradeDecisionResult:
    document = repository.get_decision(decision_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade decision not found")
    return _public_decision(document)
