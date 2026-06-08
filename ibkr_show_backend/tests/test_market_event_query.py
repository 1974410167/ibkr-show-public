"""Tests for market event query service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.schemas.market_event import (
    MarketEventDetail,
    MarketEventListItem,
    MarketEventPaginatedResponse,
    MarketEventQuery,
    MarketEventRiskSummaryResponse,
)
from app.services.market_event_query_service import MarketEventQueryService


def _make_service() -> MarketEventQueryService:
    es_client = MagicMock()
    settings = MagicMock()
    settings.es_market_event_source_index = "test_sources"
    settings.es_market_event_occurrence_index = "test_occurrences"
    settings.es_market_event_value_index = "test_values"
    settings.es_market_event_impact_index = "test_impacts"
    settings.es_market_event_news_link_index = "test_news"
    settings.es_market_event_sync_run_index = "test_sync_runs"
    settings.es_market_event_definition_index = "test_definitions"
    settings.es_market_event_analysis_index = "test_analysis"

    es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    es_client.get.return_value = None
    es_client.create_index_if_missing.return_value = None

    return MarketEventQueryService(es_client, settings)


# ---------------------------------------------------------------------------
# Query building tests
# ---------------------------------------------------------------------------


def test_build_query_empty():
    svc = _make_service()
    query = MarketEventQuery()
    es_query = svc._build_occurrence_query(query)
    assert es_query == {"match_all": {}}


def test_build_query_with_category():
    svc = _make_service()
    query = MarketEventQuery(category="MACRO")
    es_query = svc._build_occurrence_query(query)
    assert "bool" in es_query
    assert {"term": {"category": "MACRO"}} in es_query["bool"]["filter"]


def test_build_query_with_date_range():
    svc = _make_service()
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    query = MarketEventQuery(start_at=start, end_at=end)
    es_query = svc._build_occurrence_query(query)
    assert "bool" in es_query


def test_build_query_with_keyword():
    svc = _make_service()
    query = MarketEventQuery(keyword="CPI")
    es_query = svc._build_occurrence_query(query)
    assert "bool" in es_query
    assert es_query["bool"]["must"][0]["multi_match"]["query"] == "CPI"


def test_build_query_with_symbol():
    svc = _make_service()
    query = MarketEventQuery(symbol="AMD.US")
    es_query = svc._build_occurrence_query(query)
    assert {"term": {"symbols": "AMD.US"}} in es_query["bool"]["filter"]


# ---------------------------------------------------------------------------
# List events tests
# ---------------------------------------------------------------------------


def test_list_events_returns_paginated():
    svc = _make_service()
    query = MarketEventQuery(limit=10, offset=0)
    result = svc.list_events(query)
    assert isinstance(result, MarketEventPaginatedResponse)
    assert result.total == 0
    assert result.items == []
    assert result.limit == 10
    assert result.offset == 0


# ---------------------------------------------------------------------------
# Event detail tests
# ---------------------------------------------------------------------------


def test_get_event_detail_not_found():
    svc = _make_service()
    result = svc.get_event_detail("nonexistent-id")
    assert result is None


# ---------------------------------------------------------------------------
# Risk summary tests
# ---------------------------------------------------------------------------


def test_get_risk_summary():
    svc = _make_service()
    result = svc.get_risk_summary()
    assert isinstance(result, MarketEventRiskSummaryResponse)
    assert result.today.risk_level == "LOW"
    assert result.next_7_days.risk_level == "LOW"
    assert result.next_30_days.risk_level == "LOW"


# ---------------------------------------------------------------------------
# Calendar tests
# ---------------------------------------------------------------------------


def test_get_calendar_events():
    svc = _make_service()
    result = svc.get_calendar_events()
    assert result.days == []


# ---------------------------------------------------------------------------
# Source list tests
# ---------------------------------------------------------------------------


def test_list_sources():
    svc = _make_service()
    result = svc.list_sources()
    assert result == []
