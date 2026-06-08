"""Public API routes for market event queries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.schemas.market_event import (
    MarketEventCalendarResponse,
    MarketEventDetail,
    MarketEventPaginatedResponse,
    MarketEventQuery,
    MarketEventRiskSummaryResponse,
    MarketEventSourceStatusResponse,
)
from app.clients.es_client import ElasticsearchClient
from app.services.market_event_query_service import MarketEventQueryService

router = APIRouter(prefix="/market-events", tags=["market-events"])


def _get_query_service(settings: Settings = Depends(get_settings)) -> MarketEventQueryService:
    es_client = ElasticsearchClient(settings)
    return MarketEventQueryService(es_client, settings)


@router.get("", response_model=MarketEventPaginatedResponse)
def list_events(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    category: str | None = None,
    event_type: str | None = None,
    status: str | None = None,
    importance: str | None = None,
    source_code: str | None = None,
    symbol: str | None = None,
    market: str | None = None,
    country: str | None = None,
    keyword: str | None = None,
    has_actual_value: bool | None = None,
    has_forecast_value: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: str = "scheduled_at",
    sort_order: Literal["asc", "desc"] = "asc",
    display_timezone: str = "Asia/Shanghai",
    include_values: bool = True,
    include_impacts: bool = True,
    include_news: bool = False,
    include_analysis: bool = False,
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    query = MarketEventQuery(
        start_at=start_at,
        end_at=end_at,
        category=category,
        event_type=event_type,
        status=status,
        importance=importance,
        source_code=source_code,
        symbol=symbol,
        market=market,
        country=country,
        keyword=keyword,
        has_actual_value=has_actual_value,
        has_forecast_value=has_forecast_value,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        display_timezone=display_timezone,
        include_values=include_values,
        include_impacts=include_impacts,
        include_news=include_news,
        include_analysis=include_analysis,
    )
    return svc.list_events(query)


@router.get("/today", response_model=MarketEventPaginatedResponse)
def today_events(
    display_timezone: str = "Asia/Shanghai",
    market: str | None = None,
    symbol: str | None = None,
    importance: str | None = None,
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.get_today_events(
        display_timezone=display_timezone,
        market=market,
        symbol=symbol,
        importance=importance,
    )


@router.get("/upcoming", response_model=MarketEventPaginatedResponse)
def upcoming_events(
    days: int = Query(default=7, ge=1, le=90),
    importance: str | None = None,
    symbol: str | None = None,
    market: str | None = None,
    category: str | None = None,
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.get_upcoming_events(
        days=days,
        importance=importance,
        symbol=symbol,
        market=market,
        category=category,
    )


@router.get("/risk-summary", response_model=MarketEventRiskSummaryResponse)
def risk_summary(
    display_timezone: str = "Asia/Shanghai",
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.get_risk_summary(display_timezone=display_timezone)


@router.get("/calendar", response_model=MarketEventCalendarResponse)
def calendar_events(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    category: str | None = None,
    market: str | None = None,
    symbol: str | None = None,
    display_timezone: str = "Asia/Shanghai",
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.get_calendar_events(
        start_at=start_at,
        end_at=end_at,
        display_timezone=display_timezone,
        category=category,
        market=market,
        symbol=symbol,
    )


@router.get("/sources", response_model=list[MarketEventSourceStatusResponse])
def list_sources(
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.list_sources()


@router.get("/symbol/{symbol}", response_model=MarketEventPaginatedResponse)
def symbol_events(
    symbol: str,
    days: int = Query(default=30, ge=1, le=90),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    category: str | None = None,
    importance: str | None = None,
    include_macro: bool = True,
    include_news: bool = True,
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    return svc.get_symbol_events(
        symbol=symbol,
        days=days,
        include_macro=include_macro,
    )


@router.get("/{event_id}", response_model=MarketEventDetail)
def event_detail(
    event_id: str,
    include_raw: bool = False,
    svc: MarketEventQueryService = Depends(_get_query_service),
):
    detail = svc.get_event_detail(event_id, include_raw=include_raw)
    if not detail:
        raise HTTPException(status_code=404, detail="Event not found")
    return detail
