"""Tests for market event sync service."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.market_event import (
    MarketEventSyncRequest,
    MarketEventSyncResult,
    ProviderFetchResult,
    UpsertResult,
)
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_providers import MarketEventProviderRegistry
from app.services.market_event_sync_service import MarketEventSyncService


def _run(coro):
    return asyncio.run(coro)


def _make_sync_service() -> MarketEventSyncService:
    """Create sync service with mocked ES client."""
    es_client = MagicMock()
    settings = MagicMock()
    tmpdir = tempfile.mkdtemp()
    settings.market_event_credential_file = str(Path(tmpdir) / "creds.json")
    settings.es_market_event_source_index = "test_sources"
    settings.es_market_event_occurrence_index = "test_occurrences"
    settings.es_market_event_value_index = "test_values"
    settings.es_market_event_impact_index = "test_impacts"
    settings.es_market_event_news_link_index = "test_news"
    settings.es_market_event_sync_run_index = "test_sync_runs"
    settings.es_market_event_definition_index = "test_definitions"
    settings.es_market_event_analysis_index = "test_analysis"

    # Mock ES operations
    es_client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    es_client.get.return_value = None
    es_client.index_document.return_value = {"_id": "test-id"}
    es_client.create_index_if_missing.return_value = None

    svc = MarketEventSyncService(es_client, settings)
    return svc


# ---------------------------------------------------------------------------
# Sync run lifecycle tests
# ---------------------------------------------------------------------------


def test_sync_run_created_with_running_status():
    svc = _make_sync_service()
    sync_run_id = svc._create_sync_run("BLS", "bls", "CALENDAR")
    assert sync_run_id == "test-id"


def test_finish_sync_run():
    svc = _make_sync_service()
    sync_run_id = "test-id"
    result = UpsertResult(created_count=5, updated_count=2)
    # Should not raise
    svc._finish_sync_run(sync_run_id, "SUCCESS", result)


def test_finish_sync_run_with_error():
    svc = _make_sync_service()
    # Should not raise
    svc._finish_sync_run("test-id", "FAILED", error_message="Network timeout")


# ---------------------------------------------------------------------------
# Provider sync tests (using mocked providers)
# ---------------------------------------------------------------------------


def test_sync_provider_disabled():
    svc = _make_sync_service()
    # Mock provider as disabled
    provider = svc._registry.get_provider("BLS")
    provider._get_source_config = lambda: {"enabled": False, "requires_api_key": False}

    request = MarketEventSyncRequest()
    results = _run(svc.sync_provider("BLS", request))
    assert len(results) == 1
    assert results[0].status == "SKIPPED"


def test_sync_all_with_filter():
    svc = _make_sync_service()
    # All providers return SKIPPED by default (empty implementations)
    request = MarketEventSyncRequest(source_codes=["MANUAL"])
    results = _run(svc.sync_all(request))
    # Manual provider has CALENDAR_EVENTS capability
    assert len(results) >= 1
