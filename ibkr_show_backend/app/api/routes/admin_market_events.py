"""Admin API routes for market event data source configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require_admin_session
from app.core.auth import AuthSession
from app.schemas.market_event import (
    MarketEventCredentialUpdateRequest,
    MarketEventSourceConfigResponse,
    MarketEventSourceTestResponse,
    MarketEventSourceUpdateRequest,
    MarketEventSyncRunResponse,
)
from app.services.market_event_admin_service import MarketEventAdminError, MarketEventAdminService
from app.services.market_event_query_service import MarketEventQueryService

router = APIRouter(prefix="/admin/market-events", tags=["admin-market-events"])


def _get_admin_service() -> MarketEventAdminService:
    from app.api.deps import get_es_client, get_settings
    settings = get_settings()
    es_client = get_es_client()
    return MarketEventAdminService(es_client, settings)


def _get_query_service() -> MarketEventQueryService:
    from app.api.deps import get_es_client, get_settings
    settings = get_settings()
    es_client = get_es_client()
    return MarketEventQueryService(es_client, settings)


@router.get("/sources", response_model=list[MarketEventSourceConfigResponse])
def list_sources(
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    return svc.list_sources()


@router.get("/sources/{source_code}", response_model=MarketEventSourceConfigResponse)
def get_source(
    source_code: str,
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    try:
        return svc.get_source(source_code)
    except MarketEventAdminError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/sources/{source_code}", response_model=MarketEventSourceConfigResponse)
def update_source(
    source_code: str,
    body: MarketEventSourceUpdateRequest,
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    try:
        return svc.update_source(source_code, body.model_dump(exclude_none=True))
    except MarketEventAdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/sources/{source_code}/credential", response_model=MarketEventSourceConfigResponse)
def save_credential(
    source_code: str,
    body: MarketEventCredentialUpdateRequest,
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    try:
        return svc.save_credential(source_code, body.credential_key, body.value)
    except MarketEventAdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/sources/{source_code}/credential", response_model=MarketEventSourceConfigResponse)
def delete_credential(
    source_code: str,
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    try:
        return svc.delete_credential(source_code)
    except MarketEventAdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sources/{source_code}/test", response_model=MarketEventSourceTestResponse)
def test_source(
    source_code: str,
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventAdminService = Depends(_get_admin_service),
):
    try:
        return svc.test_source(source_code)
    except MarketEventAdminError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/sync-runs", response_model=list[MarketEventSyncRunResponse])
def list_sync_runs(
    source_code: str | None = None,
    sync_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _auth: AuthSession = Depends(require_admin_session),
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    filters = []
    if source_code:
        filters.append({"term": {"source_code": source_code}})
    if sync_type:
        filters.append({"term": {"sync_type": sync_type}})
    if status:
        filters.append({"term": {"status": status}})
    query_body = {"bool": {"filter": filters}} if filters else None
    items, _total = svc.list_sync_runs(query_body, size=limit, offset=offset)
    return items


@router.post("/sync")
async def trigger_sync(
    body: dict,
    _auth: AuthSession = Depends(require_admin_session),
):
    """Trigger a market event sync."""
    from app.services.market_event_sync_service import MarketEventSyncService
    from app.schemas.market_event import MarketEventSyncRequest

    settings = _get_admin_service()._s
    es_client = _get_admin_service()._es
    sync_svc = MarketEventSyncService(es_client, settings)

    request = MarketEventSyncRequest(
        source_codes=body.get("source_codes"),
        sync_types=body.get("sync_types"),
        start_at=body.get("start_at"),
        end_at=body.get("end_at"),
        dry_run=body.get("dry_run", False),
    )
    results = await sync_svc.sync_all(request)
    return {"results": [r.model_dump() for r in results]}
