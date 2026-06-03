from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.account_copilot import AccountCopilotRuntime
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.api.deps import (
    get_account_copilot_approval_service,
    get_account_copilot_demo_service,
    get_account_copilot_event_bus,
    get_account_copilot_memory_service,
    get_account_copilot_message_service,
    get_account_copilot_monitoring_service,
    get_account_copilot_run_service,
    get_account_copilot_session_service,
    get_account_copilot_skill_registry,
    get_account_copilot_subagent_registry,
    get_account_copilot_subagent_service,
    get_account_copilot_tool_registry,
    get_account_copilot_tool_reliability_repository,
    get_account_copilot_tool_reliability_service,
    get_admin_prompt_service,
    get_llm_service,
    require_authenticated_session,
)
from app.core.auth import AuthSession
from app.core.config import get_settings
from app.schemas.account_copilot import (
    CopilotApprovalRequest,
    CopilotApprovalResponse,
    CopilotCancelRunRequest,
    CopilotEventListResponse,
    CopilotMemoryListResponse,
    CopilotMessageListResponse,
    CopilotRunResponse,
    CopilotRunTraceResponse,
    CopilotSendMessageRequest,
    CopilotSendMessageResponse,
    CopilotSendMessageStreamResponse,
    CopilotSessionCreateRequest,
    CopilotSessionListResponse,
    CopilotSessionResponse,
    CopilotSessionUpdateRequest,
    CopilotTraceTimelineNode,
)
from app.services.account_copilot import (
    AccountCopilotDemoService,
    AccountCopilotMemoryService,
    AccountCopilotMessageService,
    AccountCopilotRunService,
    AccountCopilotSessionService,
    AccountCopilotSubAgentService,
)
from app.services.account_copilot.approval_service import AccountCopilotApprovalError, AccountCopilotApprovalService
from app.services.account_copilot.event_bus import AccountCopilotEventBus, format_sse
from app.services.account_copilot.monitoring_service import AccountCopilotMonitoringService
from app.services.account_copilot.tool_reliability_repository import AccountCopilotToolReliabilityRepository
from app.services.account_copilot.tool_reliability_service import AccountCopilotToolReliabilityService, percentile
from app.services.admin_prompt_service import AdminPromptService
from app.services.llm_service import LLMService

router = APIRouter(prefix="/agent/account-copilot", tags=["account-copilot"])
logger = logging.getLogger(__name__)


class CopilotToolInvokeRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


class CopilotToolReliabilityProbeRequest(BaseModel):
    include_live: bool = False
    include_longbridge: bool = False
    include_ibkr: bool = False
    include_agent_eval: bool = False
    symbol: str = "AMD.US"
    keyword: str = "AMD"
    max_tools: int = Field(default=200, ge=1, le=500)


def _build_tool_reliability_response(probe_run_id: str | None, items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    counts = {status: 0 for status in ("pass", "fail", "partial", "skipped")}
    domain_buckets: dict[str, dict[str, Any]] = {}
    latencies: list[int] = []
    created_values: list[str] = []

    for item in items:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1

        latency = item.get("latency_ms")
        numeric_latency = latency if isinstance(latency, (int, float)) and not isinstance(latency, bool) else None
        if numeric_latency is not None:
            latencies.append(int(numeric_latency))

        created_at = item.get("created_at")
        if isinstance(created_at, str) and created_at:
            created_values.append(created_at)

        domain = str(item.get("tool_domain") or "unknown")
        bucket = domain_buckets.setdefault(
            domain,
            {
                "total": 0,
                "pass": 0,
                "fail": 0,
                "partial": 0,
                "skipped": 0,
                "_latencies": [],
            },
        )
        bucket["total"] += 1
        if status in counts:
            bucket[status] += 1
        if numeric_latency is not None:
            bucket["_latencies"].append(int(numeric_latency))

    domain_stats = {}
    for domain, bucket in domain_buckets.items():
        bucket_total = int(bucket["total"])
        bucket_latencies = bucket.pop("_latencies")
        domain_stats[domain] = {
            **bucket,
            "success_rate": (bucket["pass"] / bucket_total) if bucket_total else 0,
            "avg_latency_ms": int(mean(bucket_latencies)) if bucket_latencies else 0,
        }

    return {
        "probe_run_id": probe_run_id,
        "total": total,
        "pass": counts["pass"],
        "fail": counts["fail"],
        "partial": counts["partial"],
        "skipped": counts["skipped"],
        "success_rate": (counts["pass"] / total) if total else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "last_run_at": max(created_values) if created_values else "",
        "domain_stats": domain_stats,
        "results": items,
    }


@router.get("/health")
def get_account_copilot_health(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    memory_service: AccountCopilotMemoryService = Depends(get_account_copilot_memory_service),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
    skill_registry: AccountCopilotSkillRegistry = Depends(get_account_copilot_skill_registry),
    llm_service: LLMService = Depends(get_llm_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> dict:
    settings = get_settings()
    checks = {}
    try:
        llm_health = llm_service.health()
        llm_ok = bool(llm_health.get("enabled") and llm_health.get("has_active_provider", True))
        checks["llm"] = {"ok": llm_ok, "message": "configured" if llm_ok else "LLM is not fully configured"}
    except Exception as exc:
        checks["llm"] = {"ok": False, "message": str(exc)[:200]}

    try:
        session_service.list_sessions(limit=1)
        checks["es"] = {"ok": True, "message": "reachable"}
    except Exception as exc:
        checks["es"] = {"ok": False, "message": str(exc)[:200]}

    exposed_tools = tool_registry.list_exposed_specs()
    ibkr_count = len([tool for tool in exposed_tools if tool.name.startswith("ibkr_")])
    longbridge_count = len([tool for tool in exposed_tools if tool.name.startswith("longbridge_")])
    skill_count = len(skill_registry.list_exposed_specs())
    checks["ibkr_tools"] = {"ok": ibkr_count == 9, "count": ibkr_count}
    checks["longbridge_meta_tools"] = {"ok": longbridge_count >= 6, "count": longbridge_count}
    checks["skills"] = {"ok": skill_count == 5, "count": skill_count}
    checks["event_bus"] = {"ok": event_bus is not None}
    try:
        memory_service.list_memories("__health__", limit=1)
        checks["memory_index"] = {"ok": True}
    except Exception as exc:
        checks["memory_index"] = {"ok": False, "message": str(exc)[:200]}

    return {
        "ok": all(bool(check.get("ok")) for check in checks.values()),
        "checks": checks,
        "settings": {
            "max_react_rounds": settings.account_copilot_max_react_rounds,
            "run_timeout_seconds": settings.account_copilot_run_timeout_seconds,
            "max_event_payload_chars": settings.account_copilot_max_event_payload_chars,
            "demo_mode": settings.account_copilot_demo_mode,
        },
    }


@router.post("/demo/seed")
def seed_account_copilot_demo(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    demo_service: AccountCopilotDemoService = Depends(get_account_copilot_demo_service),
) -> dict:
    if not get_settings().account_copilot_demo_mode:
        raise HTTPException(status_code=403, detail="Account Copilot demo mode is disabled")
    return demo_service.seed()


@router.get("/tool-reliability/latest")
def get_tool_reliability_latest(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: AccountCopilotToolReliabilityRepository = Depends(get_account_copilot_tool_reliability_repository),
) -> dict:
    probe_run_id = repository.latest_probe_run_id()
    items = repository.list_results(probe_run_id, limit=200) if probe_run_id else []
    return _build_tool_reliability_response(probe_run_id, items)


@router.get("/tool-reliability/results")
def list_tool_reliability_results(
    probe_run_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: AccountCopilotToolReliabilityRepository = Depends(get_account_copilot_tool_reliability_repository),
) -> dict:
    return {"items": repository.list_results(probe_run_id=probe_run_id, limit=limit)}


@router.post("/tool-reliability/probe")
def run_tool_reliability_probe(
    request: CopilotToolReliabilityProbeRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: AccountCopilotToolReliabilityService = Depends(get_account_copilot_tool_reliability_service),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    include_ibkr_live = request.include_live and request.include_ibkr
    include_longbridge_live = request.include_live and request.include_longbridge
    probe_result = service.run_probe(
        include_ibkr_live=include_ibkr_live,
        include_longbridge_live=include_longbridge_live,
        include_agent_eval=request.include_agent_eval,
        symbol=request.symbol,
        keyword=request.keyword,
        max_tools=request.max_tools,
        persist=True,
    )
    try:
        monitoring_service.record_probe_results(
            probe_run_id=probe_result.get("probe_run_id"),
            results=probe_result.get("results") or [],
        )
    except Exception as exc:
        logger.warning("Account Copilot probe metric write failed: %s", exc)
    return _build_tool_reliability_response(probe_result.get("probe_run_id"), probe_result.get("results") or [])


@router.get("/monitoring/overview")
def get_copilot_monitoring_overview(
    hours: int = Query(default=24, ge=1, le=168),
    bucket: str = Query(default="1h"),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_monitoring_overview(hours=hours, bucket=bucket)


@router.get("/monitoring/tool-metrics")
def get_copilot_tool_metrics(
    hours: int = Query(default=24, ge=1, le=168),
    bucket: str = Query(default="1h"),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_tool_metrics(hours=hours, bucket=bucket)


@router.get("/monitoring/llm-metrics")
def get_copilot_llm_metrics(
    hours: int = Query(default=24, ge=1, le=168),
    bucket: str = Query(default="1h"),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_llm_metrics(hours=hours, bucket=bucket)


@router.get("/monitoring/failures")
def get_copilot_monitoring_failures(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=50, ge=1, le=200),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_recent_failures(hours=hours, limit=limit)


@router.get("/monitoring/tool-calls/recent")
def get_copilot_recent_tool_calls(
    limit: int = Query(default=100, ge=1, le=500),
    agent_name: str | None = Query(default=None),
    tool_domain: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    include_debug: bool = Query(default=False),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_recent_tool_calls(
        limit=limit,
        agent_name=agent_name,
        tool_domain=tool_domain,
        tool_name=tool_name,
        include_debug=include_debug,
    )


@router.get("/monitoring/llm-calls/recent")
def get_copilot_recent_llm_calls(
    limit: int = Query(default=100, ge=1, le=500),
    agent_name: str | None = Query(default=None),
    model: str | None = Query(default=None),
    include_debug: bool = Query(default=False),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.get_recent_llm_calls(
        limit=limit,
        agent_name=agent_name,
        model=model,
        include_debug=include_debug,
    )


@router.get("/monitoring/structured-output/recent")
def get_structured_output_recent(
    limit: int = Query(default=100, ge=1, le=500),
    agent_name: str | None = Query(default=None),
    contract_name: str | None = Query(default=None),
    node_name: str | None = Query(default=None),
    ok: bool | None = Query(default=None),
    repaired: bool | None = Query(default=None),
    fallback_used: bool | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
) -> dict:
    return monitoring_service.query_recent_structured_output_events(
        limit=limit,
        agent_name=agent_name,
        contract_name=contract_name,
        node_name=node_name,
        ok=ok,
        repaired=repaired,
        fallback_used=fallback_used,
    )


@router.post("/sessions", response_model=CopilotSessionResponse)
def create_session(
    request: CopilotSessionCreateRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
) -> dict:
    return session_service.create_session(title=request.title)


@router.get("/sessions", response_model=CopilotSessionListResponse)
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
) -> dict:
    return {"items": session_service.list_sessions(limit=limit)}


@router.get("/sessions/{session_id}", response_model=CopilotSessionResponse)
def get_session(
    session_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
) -> dict:
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    return session


@router.patch("/sessions/{session_id}", response_model=CopilotSessionResponse)
def update_session(
    session_id: str,
    request: CopilotSessionUpdateRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
) -> dict:
    payload = request.model_dump(exclude_unset=True)
    session = session_service.update_session(session_id, payload)
    if session is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=CopilotMessageListResponse)
def list_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    message_service: AccountCopilotMessageService = Depends(get_account_copilot_message_service),
) -> dict:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    return {"items": message_service.list_messages(session_id=session_id, limit=limit)}


@router.post("/sessions/{session_id}/messages", response_model=CopilotSendMessageResponse)
def send_message(
    session_id: str,
    request: CopilotSendMessageRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    message_service: AccountCopilotMessageService = Depends(get_account_copilot_message_service),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    memory_service: AccountCopilotMemoryService = Depends(get_account_copilot_memory_service),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
    skill_registry: AccountCopilotSkillRegistry = Depends(get_account_copilot_skill_registry),
    subagent_registry: AccountCopilotSubAgentRegistry = Depends(get_account_copilot_subagent_registry),
    subagent_service: AccountCopilotSubAgentService = Depends(get_account_copilot_subagent_service),
    llm_service: LLMService = Depends(get_llm_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
    prompt_service: AdminPromptService = Depends(get_admin_prompt_service),
) -> dict:
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    if run_service.find_active_run_by_session(session_id):
        raise HTTPException(status_code=409, detail="This session already has an active Account Copilot run.")

    user_message = message_service.create_message(session_id=session_id, role="user", content=request.content)
    run = run_service.create_run(
        session_id=session_id,
        user_message_id=user_message["id"],
        user_input=request.content,
    )
    user_message = message_service.update_message_run_id(user_message["id"], run["id"]) or user_message

    memory_context = _safe_load_memory_context(memory_service, session_id, request.content)
    settings = get_settings()
    runtime = AccountCopilotRuntime(
        llm_service=llm_service,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        subagent_registry=subagent_registry,
        subagent_service=subagent_service,
        event_bus=event_bus,
        emit_terminal_events=False,
        cancel_checker=lambda run_id: (run_service.get_run(run_id) or {}).get("status") == "cancelled",
        timeout_seconds=settings.account_copilot_run_timeout_seconds,
        max_rounds=settings.account_copilot_max_react_rounds,
        monitoring_service=monitoring_service,
        prompt_service=prompt_service,
    )
    runtime_state = runtime.run(
        {
            "session_id": session_id,
            "run_id": run["id"],
            "user_message_id": user_message["id"],
            "user_input": request.content,
            "messages": memory_context["recent_messages"],
            "rolling_summary": memory_context["rolling_summary"],
            "pinned_facts": memory_context["pinned_facts"],
            "retrieved_memories": memory_context["retrieved_memories"],
            "non_compressible_constraints": memory_context["non_compressible_constraints"],
            "memory_snapshot": memory_context["memory_snapshot"],
        }
    )
    final_answer = runtime_state.get("final_answer") or ""
    if (run_service.get_run(run["id"]) or {}).get("status") == "cancelled":
        event_bus.publish(run["id"], session_id, "run_cancelled", {"reason": "cancelled before persistence"})
        raise HTTPException(status_code=409, detail="Run was cancelled")
    assistant_message = message_service.create_message(
        session_id=session_id,
        role="assistant",
        content=final_answer,
        run_id=run["id"],
    )
    trace_payload = _runtime_trace_payload(runtime_state)
    pending_approval = runtime_state.get("pending_approval")
    if (runtime_state.get("metadata") or {}).get("cancelled"):
        run = run_service.mark_run_cancelled(run["id"], "Runtime cancelled") or run
    elif pending_approval and (runtime_state.get("metadata") or {}).get("requires_approval"):
        run = run_service.mark_run_awaiting_approval(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=final_answer,
            pending_approval=pending_approval,
            payload=trace_payload,
        )
    else:
        run = run_service.mark_run_completed(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=final_answer,
            payload={**trace_payload, "pending_approval": pending_approval},
        )
    if (runtime_state.get("metadata") or {}).get("timeout"):
        run = run_service.update_run_fields(
            run["id"],
            {
                "error_code": "RUN_TIMEOUT",
                "error_message": "Run timed out",
                "metadata": {**(run.get("metadata") or {}), "timeout": True, "fallback_used": True},
            },
        ) or run
    session_service.touch_after_messages(
        session_id,
        message_count=2,
        last_message_at=assistant_message["created_at"],
    )
    event_bus.publish(run["id"], session_id, "memory_update_started", {})
    memory_update = _safe_memory_update(memory_service, session_id, run["id"])
    if not memory_update.get("ok"):
        event_bus.publish(run["id"], session_id, "memory_update_failed", {"error": memory_update.get("error")})
        metadata = {**(run.get("metadata") or {}), "memory_update_error": memory_update.get("error")}
        run = run_service.update_run_fields(run["id"], {"metadata": metadata}) or run
    else:
        event_bus.publish(run["id"], session_id, "memory_update_finished", memory_update)
    if run.get("status") == "completed":
        event_bus.publish(run["id"], session_id, "run_completed", {"fallback_used": (run.get("metadata") or {}).get("fallback_used", False)})
    return {"user_message": user_message, "assistant_message": assistant_message, "run": run}


@router.post("/sessions/{session_id}/messages/stream", response_model=CopilotSendMessageStreamResponse)
def send_message_stream(
    session_id: str,
    request: CopilotSendMessageRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    message_service: AccountCopilotMessageService = Depends(get_account_copilot_message_service),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    memory_service: AccountCopilotMemoryService = Depends(get_account_copilot_memory_service),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
    skill_registry: AccountCopilotSkillRegistry = Depends(get_account_copilot_skill_registry),
    subagent_registry: AccountCopilotSubAgentRegistry = Depends(get_account_copilot_subagent_registry),
    subagent_service: AccountCopilotSubAgentService = Depends(get_account_copilot_subagent_service),
    llm_service: LLMService = Depends(get_llm_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
    monitoring_service: AccountCopilotMonitoringService = Depends(get_account_copilot_monitoring_service),
    prompt_service: AdminPromptService = Depends(get_admin_prompt_service),
) -> dict:
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    if run_service.find_active_run_by_session(session_id):
        raise HTTPException(status_code=409, detail="This session already has an active Account Copilot run.")
    user_message = message_service.create_message(session_id=session_id, role="user", content=request.content)
    run = run_service.create_run(session_id=session_id, user_message_id=user_message["id"], user_input=request.content)
    user_message = message_service.update_message_run_id(user_message["id"], run["id"]) or user_message
    background_tasks.add_task(
        _execute_stream_run,
        session,
        user_message,
        run,
        request.content,
        session_service,
        message_service,
        run_service,
        memory_service,
        tool_registry,
        skill_registry,
        llm_service,
        event_bus,
        monitoring_service,
        prompt_service,
        subagent_registry,
        subagent_service,
    )
    return {
        "user_message": user_message,
        "run": run,
        "events_url": f"/api/agent/account-copilot/runs/{run['id']}/events",
    }


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> StreamingResponse:
    if run_service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Account Copilot run not found")

    async def event_generator():
        async for event in event_bus.subscribe(run_id, after_seq=after_seq):
            yield format_sse(event)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}/events/list", response_model=CopilotEventListResponse)
def list_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> dict:
    if run_service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Account Copilot run not found")
    return {"items": event_bus.repository.list_events(run_id, after_seq=after_seq, limit=limit)}


@router.post("/runs/{run_id}/cancel", response_model=CopilotRunResponse)
def cancel_run(
    run_id: str,
    request: CopilotCancelRunRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> dict:
    run = run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Account Copilot run not found")
    if run.get("status") not in {"queued", "running", "awaiting_approval"}:
        raise HTTPException(status_code=400, detail="Run is not cancellable")
    cancelled = run_service.mark_run_cancelled(run_id, request.reason)
    event_bus.publish(run_id, run["session_id"], "run_cancelled", {"reason": request.reason or "User cancelled the run"})
    return cancelled


@router.get("/sessions/{session_id}/memories", response_model=CopilotMemoryListResponse)
def list_session_memories(
    session_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    memory_type: str | None = None,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    memory_service: AccountCopilotMemoryService = Depends(get_account_copilot_memory_service),
) -> dict:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    return {"items": memory_service.list_memories(session_id=session_id, limit=limit, memory_type=memory_type)}


@router.post("/sessions/{session_id}/memories/rebuild")
def rebuild_session_memories(
    session_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    session_service: AccountCopilotSessionService = Depends(get_account_copilot_session_service),
    memory_service: AccountCopilotMemoryService = Depends(get_account_copilot_memory_service),
) -> dict:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Account Copilot session not found")
    return memory_service.rebuild_session_memory(session_id)


@router.get("/tools")
def list_tools(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
) -> dict:
    return {"items": [_serialize_tool_spec(spec) for spec in tool_registry.list_exposed_specs()]}


@router.get("/tools/{tool_name}/schema")
def get_tool_schema(
    tool_name: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
) -> dict:
    spec = tool_registry.get(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail="Account Copilot tool not found")
    return spec.schema


@router.post("/tools/{tool_name}/invoke")
def invoke_tool(
    tool_name: str,
    request: CopilotToolInvokeRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    tool_registry: AccountCopilotToolRegistry = Depends(get_account_copilot_tool_registry),
) -> dict:
    spec = tool_registry.get(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail="Account Copilot tool not found")
    if not spec.read_only or spec.handler is None:
        raise HTTPException(status_code=403, detail="Account Copilot tool is not invokable")
    try:
        return spec.handler(**request.arguments)
    except TypeError as exc:
        return {
            "ok": False,
            "tool": tool_name,
            "arguments": request.arguments,
            "data": {},
            "data_source": "IBKR_ES",
            "data_limitations": ["Tool arguments did not match the schema."],
            "metadata": {"read_only": True, "error_code": "INVALID_ARGUMENT", "message": str(exc)},
        }


@router.post("/runs/{run_id}/approval", response_model=CopilotApprovalResponse)
def approve_run_skill_request(
    run_id: str,
    request: CopilotApprovalRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    approval_service: AccountCopilotApprovalService = Depends(get_account_copilot_approval_service),
) -> dict:
    try:
        result = approval_service.handle_approval(
            run_id=run_id,
            approval_id=request.approval_id,
            approved=request.approved,
            plan_hash=request.plan_hash,
            comment=request.comment,
        )
        if request.approved:
            background_tasks.add_task(
                approval_service.execute_approved_skill,
                run_id,
                request.approval_id,
            )
        return result
    except AccountCopilotApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/runs/{run_id}", response_model=CopilotRunResponse)
def get_run(
    run_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
) -> dict:
    run = run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Account Copilot run not found")
    return run


@router.get("/runs/{run_id}/trace", response_model=CopilotRunTraceResponse)
def get_run_trace(
    run_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    run_service: AccountCopilotRunService = Depends(get_account_copilot_run_service),
    event_bus: AccountCopilotEventBus = Depends(get_account_copilot_event_bus),
) -> dict:
    run = run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Account Copilot run not found")

    events = event_bus.repository.list_events(run_id, limit=1000)
    timeline = _build_trace_timeline(run, events)

    safe_events = []
    for event in events:
        safe_event = dict(event)
        safe_event["payload"] = _redact_sensitive(safe_event.get("payload") or {})
        safe_events.append(safe_event)

    return {"run_id": run_id, "status": run.get("status", ""), "timeline": timeline, "events": safe_events}


_SUBAGENT_EVENT_TYPES = {"subagent_started", "subagent_finished", "subagent_failed"}

_SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "authorization",
    "api_key", "secret", "password", "cookie", "set_cookie",
    "reasoning", "thinking", "chain_of_thought",
}


def _redact_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _redact_sensitive(v) for k, v in obj.items() if str(k).lower().replace("-", "_") not in _SENSITIVE_KEYS}
    if isinstance(obj, list):
        return [_redact_sensitive(item) for item in obj[:50]]
    return obj


def _build_trace_timeline(run: dict, events: list[dict]) -> list[dict]:
    nodes: list[dict] = []
    ts_map: dict[str, str] = {}
    for event in events:
        et = event.get("event_type", "")
        if et in {"planner_started", "planner_finished", "tool_started", "tool_finished", "tool_failed",
                   "skill_started", "skill_finished", "skill_failed", "final_answer",
                   "run_completed", "run_failed", "run_cancelled"} | _SUBAGENT_EVENT_TYPES:
            ts_map.setdefault(et, event.get("created_at", ""))

    planner = run.get("planner_output") or {}
    if planner:
        nodes.append({
            "node_type": "planner",
            "round": planner.get("round"),
            "status": "repaired" if planner.get("repaired") else "ok",
            "label": f"Planner{'(repaired)' if planner.get('repaired') else ''}",
            "created_at": ts_map.get("planner_finished", run.get("created_at", "")),
            "payload": _redact_sensitive({k: v for k, v in planner.items() if k not in {"raw_action", "repair_raw_action"}}),
        })

    for action in run.get("actions") or []:
        action_type = action.get("action_type", "")
        label = action_type
        if action_type == "call_tool":
            label = f"Tool: {action.get('tool_name', '--')}"
        elif action_type == "delegate_to_subagent":
            label = f"SubAgent: {action.get('subagent_name', '--')}"
        elif action_type == "request_skill_approval":
            label = f"Skill: {action.get('skill_name', '--')}"
        elif action_type == "final_answer":
            label = "Final Answer"
        nodes.append({
            "node_type": "action",
            "round": action.get("round"),
            "status": "ok",
            "label": label,
            "created_at": ts_map.get("planner_finished", run.get("created_at", "")),
            "payload": _redact_sensitive({k: v for k, v in action.items() if k not in {"thought_summary", "raw_action"}}),
        })

    for event in events:
        et = event.get("event_type", "")
        if et in _SUBAGENT_EVENT_TYPES:
            ep = event.get("payload") or {}
            nodes.append({
                "node_type": "subagent",
                "round": ep.get("round"),
                "status": "started" if et == "subagent_started" else ("ok" if et == "subagent_finished" else "failed"),
                "label": f"SubAgent {ep.get('subagent_name', '--')} {'started' if et == 'subagent_started' else ('done' if et == 'subagent_finished' else 'failed')}",
                "created_at": event.get("created_at", ""),
                "payload": _redact_sensitive(ep),
            })

    for tc in run.get("tool_calls") or []:
        nodes.append({
            "node_type": "tool",
            "round": tc.get("round"),
            "status": "ok" if tc.get("ok") else "failed",
            "label": f"Tool: {tc.get('tool_name', '--')}",
            "created_at": tc.get("created_at", run.get("created_at", "")),
            "payload": _redact_sensitive({k: v for k, v in tc.items() if k not in {"raw_data", "data"}}),
        })

    for obs in run.get("observations") or []:
        obs_type = obs.get("observation_type", "")
        label = f"Observation: {obs_type}"
        if obs_type == "subagent_result":
            label = f"SubAgent Result: {obs.get('subagent_name', '--')}"
        nodes.append({
            "node_type": "observation",
            "round": obs.get("round"),
            "status": "ok" if obs.get("ok") else "failed",
            "label": label,
            "created_at": obs.get("created_at", run.get("created_at", "")),
            "payload": _redact_sensitive({
                "observation_type": obs_type,
                "ok": obs.get("ok"),
                "data_summary": str(obs.get("data_summary") or "")[:500],
                "data_limitations": obs.get("data_limitations") or [],
                "subagent_name": obs.get("subagent_name"),
            }),
        })

    if run.get("final_answer"):
        nodes.append({
            "node_type": "final_answer",
            "status": "ok",
            "label": "Final Answer",
            "created_at": ts_map.get("final_answer", run.get("completed_at", "")),
            "payload": {"content": str(run["final_answer"])[:500]},
        })

    if run.get("status") == "failed":
        nodes.append({
            "node_type": "error",
            "status": "failed",
            "label": f"Error: {run.get('error_code', 'UNKNOWN')}",
            "created_at": run.get("completed_at", ""),
            "payload": {"error_code": run.get("error_code"), "error_message": str(run.get("error_message") or "")[:500]},
        })

    return nodes


def _runtime_trace_payload(runtime_state: dict) -> dict:
    return {
        "planner_output": runtime_state.get("planner_output") or {},
        "actions": runtime_state.get("actions") or [],
        "observations": runtime_state.get("observations") or [],
        "tool_calls": runtime_state.get("tool_calls") or [],
        "skill_requests": runtime_state.get("skill_requests") or [],
        "memory_snapshot": runtime_state.get("memory_snapshot") or {},
        "metadata": runtime_state.get("metadata") or {},
    }


def _empty_memory_context(session_id: str) -> dict:
    return {
        "rolling_summary": "",
        "pinned_facts": {},
        "non_compressible_constraints": [],
        "retrieved_memories": [],
        "recent_messages": [],
        "memory_snapshot": {
            "session_id": session_id,
            "retrieved_memory_count": 0,
            "recent_message_count": 0,
            "memory_fallback_used": True,
            "context_layers": ["L1_recent"],
        },
    }


def _safe_load_memory_context(memory_service: AccountCopilotMemoryService, session_id: str, user_input: str) -> dict:
    try:
        return memory_service.load_context_for_run(session_id, user_input)
    except Exception as exc:
        context = _empty_memory_context(session_id)
        context["memory_snapshot"]["memory_load_error"] = str(exc)[:300]
        return context


def _safe_memory_update(memory_service: AccountCopilotMemoryService, session_id: str, run_id: str) -> dict:
    try:
        return memory_service.maybe_update_after_run(session_id, run_id)
    except Exception as exc:
        return {"ok": False, "run_id": run_id, "error": str(exc)[:500]}


def _execute_stream_run(
    session: dict,
    user_message: dict,
    run: dict,
    content: str,
    session_service: AccountCopilotSessionService,
    message_service: AccountCopilotMessageService,
    run_service: AccountCopilotRunService,
    memory_service: AccountCopilotMemoryService,
    tool_registry: AccountCopilotToolRegistry,
    skill_registry: AccountCopilotSkillRegistry,
    llm_service: LLMService,
    event_bus: AccountCopilotEventBus,
    monitoring_service: AccountCopilotMonitoringService | None = None,
    prompt_service: AdminPromptService | None = None,
    subagent_registry: AccountCopilotSubAgentRegistry | None = None,
    subagent_service: AccountCopilotSubAgentService | None = None,
) -> None:
    session_id = session["id"]
    try:
        memory_context = _safe_load_memory_context(memory_service, session_id, content)
        runtime = AccountCopilotRuntime(
            llm_service=llm_service,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            subagent_registry=subagent_registry,
            subagent_service=subagent_service,
            event_bus=event_bus,
            emit_terminal_events=False,
            cancel_checker=lambda run_id: (run_service.get_run(run_id) or {}).get("status") == "cancelled",
            timeout_seconds=get_settings().account_copilot_run_timeout_seconds,
            max_rounds=get_settings().account_copilot_max_react_rounds,
            monitoring_service=monitoring_service,
            prompt_service=prompt_service,
        )
        runtime_state = runtime.run(
            {
                "session_id": session_id,
                "run_id": run["id"],
                "user_message_id": user_message["id"],
                "user_input": content,
                "messages": memory_context["recent_messages"],
                "rolling_summary": memory_context["rolling_summary"],
                "pinned_facts": memory_context["pinned_facts"],
                "retrieved_memories": memory_context["retrieved_memories"],
                "non_compressible_constraints": memory_context["non_compressible_constraints"],
                "memory_snapshot": memory_context["memory_snapshot"],
            }
        )
        final_answer = runtime_state.get("final_answer") or ""
        if (run_service.get_run(run["id"]) or {}).get("status") == "cancelled":
            event_bus.publish(run["id"], session_id, "run_cancelled", {"reason": "cancelled before persistence"})
            return
        assistant_message = message_service.create_message(session_id=session_id, role="assistant", content=final_answer, run_id=run["id"])
        trace_payload = _runtime_trace_payload(runtime_state)
        pending_approval = runtime_state.get("pending_approval")
        if (runtime_state.get("metadata") or {}).get("cancelled"):
            saved_run = run_service.mark_run_cancelled(run["id"], "Runtime cancelled")
        elif pending_approval and (runtime_state.get("metadata") or {}).get("requires_approval"):
            saved_run = run_service.mark_run_awaiting_approval(
                run_id=run["id"],
                assistant_message_id=assistant_message["id"],
                final_answer=final_answer,
                pending_approval=pending_approval,
                payload=trace_payload,
            )
        else:
            saved_run = run_service.mark_run_completed(
                run_id=run["id"],
                assistant_message_id=assistant_message["id"],
                final_answer=final_answer,
                payload={**trace_payload, "pending_approval": pending_approval},
            )
        if saved_run and (runtime_state.get("metadata") or {}).get("timeout"):
            saved_run = run_service.update_run_fields(
                run["id"],
                {
                    "error_code": "RUN_TIMEOUT",
                    "error_message": "Run timed out",
                    "metadata": {**(saved_run.get("metadata") or {}), "timeout": True, "fallback_used": True},
                },
            ) or saved_run
        session_service.touch_after_messages(session_id, message_count=2, last_message_at=assistant_message["created_at"])
        event_bus.publish(run["id"], session_id, "memory_update_started", {})
        memory_update = _safe_memory_update(memory_service, session_id, run["id"])
        if not memory_update.get("ok"):
            event_bus.publish(run["id"], session_id, "memory_update_failed", {"error": memory_update.get("error")})
            metadata = {**((saved_run or {}).get("metadata") or {}), "memory_update_error": memory_update.get("error")}
            saved_run = run_service.update_run_fields(run["id"], {"metadata": metadata}) or saved_run
        else:
            event_bus.publish(run["id"], session_id, "memory_update_finished", memory_update)
        if saved_run and saved_run.get("status") == "completed":
            event_bus.publish(run["id"], session_id, "run_completed", {"fallback_used": (saved_run.get("metadata") or {}).get("fallback_used", False)})
    except Exception as exc:
        run_service.mark_run_failed(run["id"], "STREAM_RUN_FAILED", str(exc)[:500])
        event_bus.publish(run["id"], session_id, "run_failed", {"error_code": "STREAM_RUN_FAILED", "message": str(exc)[:500]})


def _serialize_tool_spec(spec) -> dict:
    return {
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "data_sensitivity": spec.data_sensitivity,
        "read_only": spec.read_only,
        "approval_required": spec.approval_required,
        "output_budget_chars": spec.output_budget_chars,
        "schema": spec.schema,
    }
