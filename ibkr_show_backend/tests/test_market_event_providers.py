"""Tests for market event provider registry and empty implementations."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.schemas.market_event import ProviderCalendarQuery
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_providers import (
    MarketEventProviderNotFoundError,
    MarketEventProviderRegistry,
    BlsProvider,
    BeaProvider,
    FredProvider,
    FedProvider,
    IsmProvider,
    LongbridgeProvider,
    ManualProvider,
)


def _make_registry() -> MarketEventProviderRegistry:
    """Create a registry with mocked repo."""
    tmpdir = tempfile.mkdtemp()
    cred_file = Path(tmpdir) / "creds.json"
    cred_store = MarketEventCredentialStore(str(cred_file))
    repo = MagicMock()
    # Default: all sources enabled, no API keys required
    repo.get_source.return_value = {
        "source_code": "BLS",
        "enabled": True,
        "requires_api_key": False,
    }
    repo.list_sources.return_value = []
    return MarketEventProviderRegistry(repo, cred_store)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_list_providers():
    registry = _make_registry()
    providers = registry.list_providers()
    codes = [p.source_code for p in providers]
    assert "BLS" in codes
    assert "BEA" in codes
    assert "FRED" in codes
    assert "FED" in codes
    assert "ISM" in codes
    assert "LONGBRIDGE" in codes
    assert "MANUAL" in codes


def test_registry_get_provider():
    registry = _make_registry()
    provider = registry.get_provider("BLS")
    assert provider.source_code == "BLS"
    assert provider.provider_name == "bls"


def test_registry_get_provider_not_found():
    registry = _make_registry()
    with pytest.raises(MarketEventProviderNotFoundError):
        registry.get_provider("NONEXISTENT")


def test_registry_get_providers_by_capability_calendar():
    registry = _make_registry()
    providers = registry.get_providers_by_capability("CALENDAR_EVENTS")
    codes = [p.source_code for p in providers]
    assert "BLS" in codes
    assert "BEA" in codes
    assert "FED" in codes
    assert "ISM" in codes
    assert "LONGBRIDGE" in codes
    assert "MANUAL" in codes
    assert "FRED" not in codes  # FRED doesn't have CALENDAR_EVENTS


def test_registry_get_providers_by_capability_value():
    registry = _make_registry()
    providers = registry.get_providers_by_capability("EVENT_VALUES")
    codes = [p.source_code for p in providers]
    assert "BLS" in codes
    assert "BEA" in codes
    assert "FRED" in codes
    assert "FED" not in codes


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


def test_health_check_disabled_source():
    registry = _make_registry()
    provider = registry.get_provider("BLS")
    # Mock source as disabled
    provider._get_source_config = lambda: {"enabled": False, "requires_api_key": False}
    result = _run(provider.health_check())
    assert result.status == "SKIPPED"
    assert "disabled" in result.message.lower()


def test_health_check_no_key_required():
    registry = _make_registry()
    provider = registry.get_provider("FED")
    result = _run(provider.health_check())
    assert result.status == "SUCCESS"


def test_health_check_manual_provider():
    registry = _make_registry()
    provider = registry.get_provider("MANUAL")
    result = _run(provider.health_check())
    assert result.status == "SUCCESS"


def test_fetch_calendar_returns_skipped():
    registry = _make_registry()
    provider = registry.get_provider("BLS")
    provider._get_source_config = lambda: {
        "enabled": True,
        "requires_api_key": True,
        "credential_key_name": "api_key",
    }
    query = ProviderCalendarQuery()
    result = _run(provider.fetch_calendar_events(query))
    assert result.status == "SKIPPED"
    assert result.source_code == "BLS"


def test_fetch_news_returns_skipped_for_bls():
    """BLS doesn't have NEWS_EVENTS capability."""
    registry = _make_registry()
    provider = registry.get_provider("BLS")
    from app.schemas.market_event import ProviderNewsQuery
    result = _run(provider.fetch_news_events(ProviderNewsQuery()))
    assert result.status == "SKIPPED"


# ---------------------------------------------------------------------------
# Provider capability declarations
# ---------------------------------------------------------------------------


def test_bls_capabilities():
    assert BlsProvider.capabilities == {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}


def test_bea_capabilities():
    assert BeaProvider.capabilities == {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}


def test_fred_capabilities():
    assert FredProvider.capabilities == {"EVENT_VALUES", "HEALTH_CHECK"}


def test_fed_capabilities():
    assert FedProvider.capabilities == {"CALENDAR_EVENTS", "HEALTH_CHECK"}


def test_ism_capabilities():
    assert IsmProvider.capabilities == {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}


def test_longbridge_capabilities():
    expected = {
        "CALENDAR_EVENTS", "NEWS_EVENTS", "CORPORATE_EVENTS",
        "MARKET_HOLIDAYS", "MARKET_STATUS", "TRADING_SESSIONS", "HEALTH_CHECK",
    }
    assert LongbridgeProvider.capabilities == expected


def test_manual_capabilities():
    assert ManualProvider.capabilities == {"CALENDAR_EVENTS"}
