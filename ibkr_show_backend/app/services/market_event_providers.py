"""Market Event Provider abstraction and empty implementations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.schemas.market_event import (
    MarketEventProviderCapability,
    MarketEventSourceCode,
    MarketEventSyncStatus,
    MarketEventTestStatus,
    ProviderCalendarQuery,
    ProviderCorporateQuery,
    ProviderFetchResult,
    ProviderHealthCheckResult,
    ProviderMarketHolidayQuery,
    ProviderMarketStatusQuery,
    ProviderNewsQuery,
    ProviderTradingSessionQuery,
    ProviderValueQuery,
)
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_repository import MarketEventRepository

logger = logging.getLogger(__name__)


class MarketEventProviderError(RuntimeError):
    """Base provider error."""


class MarketEventProviderNotFoundError(MarketEventProviderError):
    """Provider not found in registry."""


class MarketEventProviderDisabledError(MarketEventProviderError):
    """Source is disabled."""


class MarketEventCredentialMissingError(MarketEventProviderError):
    """Required credential is missing."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class MarketEventProvider(ABC):
    """Base class for all market event providers."""

    source_code: MarketEventSourceCode
    provider_name: str
    capabilities: set[MarketEventProviderCapability]

    def __init__(
        self,
        repo: MarketEventRepository,
        cred_store: MarketEventCredentialStore,
    ) -> None:
        self._repo = repo
        self._cred_store = cred_store

    def _get_source_config(self) -> dict | None:
        return self._repo.get_source(self.source_code)

    def _is_enabled(self) -> bool:
        src = self._get_source_config()
        return bool(src and src.get("enabled", True))

    def _get_api_key(self) -> str | None:
        src = self._get_source_config()
        if not src or not src.get("requires_api_key"):
            return None
        cred_key = src.get("credential_key_name", "api_key")
        return self._cred_store.get_decrypted_value(self.source_code, cred_key)

    def _check_ready(self) -> tuple[bool, str]:
        """Check if provider is ready. Returns (ok, message)."""
        if not self._is_enabled():
            return False, "Source is disabled"
        src = self._get_source_config()
        if src and src.get("requires_api_key"):
            key = self._get_api_key()
            if not key:
                return False, f"Credential {src.get('credential_key_name')} not configured"
        return True, "Ready"

    @abstractmethod
    async def health_check(self) -> ProviderHealthCheckResult:
        ...

    @abstractmethod
    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        ...

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_event_values not implemented")

    async def fetch_news_events(self, query: ProviderNewsQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_news_events not implemented")

    async def fetch_corporate_events(self, query: ProviderCorporateQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_corporate_events not implemented")

    async def fetch_market_holidays(self, query: ProviderMarketHolidayQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_market_holidays not implemented")

    async def fetch_market_status(self, query: ProviderMarketStatusQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_market_status not implemented")

    async def fetch_trading_sessions(self, query: ProviderTradingSessionQuery) -> ProviderFetchResult:
        return self._skipped_result("fetch_trading_sessions not implemented")

    def _health_result(self, status: MarketEventTestStatus, message: str) -> ProviderHealthCheckResult:
        return ProviderHealthCheckResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status=status,
            message=message,
            checked_at=datetime.now(timezone.utc),
        )

    def _skipped_result(self, message: str = "Skipped") -> ProviderFetchResult:
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SKIPPED",
            error_message=message,
        )

    def _empty_success(self) -> ProviderFetchResult:
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            total_count=0,
        )


# ---------------------------------------------------------------------------
# Empty implementations
# ---------------------------------------------------------------------------


class BlsProvider(MarketEventProvider):
    source_code = "BLS"
    provider_name = "bls"
    capabilities = {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)
        return self._health_result("SUCCESS", "Key configured; real network check in Provider phase")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("BLS calendar fetch not yet implemented")

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        return self._skipped_result("BLS value fetch not yet implemented")


class BeaProvider(MarketEventProvider):
    source_code = "BEA"
    provider_name = "bea"
    capabilities = {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)
        return self._health_result("SUCCESS", "Key configured; real network check in Provider phase")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("BEA calendar fetch not yet implemented")

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        return self._skipped_result("BEA value fetch not yet implemented")


class FredProvider(MarketEventProvider):
    source_code = "FRED"
    provider_name = "fred"
    capabilities = {"EVENT_VALUES", "HEALTH_CHECK"}

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)
        return self._health_result("SUCCESS", "Key configured; real network check in Provider phase")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("FRED does not provide calendar events")

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        return self._skipped_result("FRED value fetch not yet implemented")


class FedProvider(MarketEventProvider):
    source_code = "FED"
    provider_name = "fed"
    capabilities = {"CALENDAR_EVENTS", "HEALTH_CHECK"}

    async def health_check(self) -> ProviderHealthCheckResult:
        if not self._is_enabled():
            return self._health_result("SKIPPED", "Source is disabled")
        return self._health_result("SUCCESS", "No API key required")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("Fed calendar fetch not yet implemented")


class IsmProvider(MarketEventProvider):
    source_code = "ISM"
    provider_name = "ism"
    capabilities = {"CALENDAR_EVENTS", "EVENT_VALUES", "HEALTH_CHECK"}

    async def health_check(self) -> ProviderHealthCheckResult:
        if not self._is_enabled():
            return self._health_result("SKIPPED", "Source is disabled")
        return self._health_result("SUCCESS", "No API key required")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("ISM calendar fetch not yet implemented")

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        return self._skipped_result("ISM value fetch not yet implemented")


class LongbridgeProvider(MarketEventProvider):
    source_code = "LONGBRIDGE"
    provider_name = "longbridge"
    capabilities = {
        "CALENDAR_EVENTS", "NEWS_EVENTS", "CORPORATE_EVENTS",
        "MARKET_HOLIDAYS", "MARKET_STATUS", "TRADING_SESSIONS", "HEALTH_CHECK",
    }

    async def health_check(self) -> ProviderHealthCheckResult:
        if not self._is_enabled():
            return self._health_result("SKIPPED", "Source is disabled")
        return self._health_result("SUCCESS", "Longbridge config check deferred")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge calendar fetch not yet implemented")

    async def fetch_news_events(self, query: ProviderNewsQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge news fetch not yet implemented")

    async def fetch_corporate_events(self, query: ProviderCorporateQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge corporate fetch not yet implemented")

    async def fetch_market_holidays(self, query: ProviderMarketHolidayQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge market holidays fetch not yet implemented")

    async def fetch_market_status(self, query: ProviderMarketStatusQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge market status fetch not yet implemented")

    async def fetch_trading_sessions(self, query: ProviderTradingSessionQuery) -> ProviderFetchResult:
        return self._skipped_result("Longbridge trading sessions fetch not yet implemented")


class ManualProvider(MarketEventProvider):
    source_code = "MANUAL"
    provider_name = "manual"
    capabilities = {"CALENDAR_EVENTS"}

    async def health_check(self) -> ProviderHealthCheckResult:
        return self._health_result("SUCCESS", "Manual provider always available")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        return self._empty_success()


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------


class MarketEventProviderRegistry:
    """Registry for all market event providers."""

    def __init__(
        self,
        repo: MarketEventRepository,
        cred_store: MarketEventCredentialStore,
    ) -> None:
        self._providers: dict[str, MarketEventProvider] = {}
        from app.services.market_event_real_providers import (
            RealBeaProvider,
            RealBlsProvider,
            RealFedProvider,
            RealFredProvider,
            RealLongbridgeProvider,
        )

        for cls in [RealBlsProvider, RealBeaProvider, RealFredProvider, RealFedProvider,
                     IsmProvider, RealLongbridgeProvider, ManualProvider]:
            provider = cls(repo, cred_store)
            self._providers[provider.source_code] = provider

    def list_providers(self) -> list[MarketEventProvider]:
        return list(self._providers.values())

    def get_provider(self, source_code: str) -> MarketEventProvider:
        provider = self._providers.get(source_code)
        if not provider:
            raise MarketEventProviderNotFoundError(f"Provider {source_code} not found")
        return provider

    def get_enabled_providers(self) -> list[MarketEventProvider]:
        return [p for p in self._providers.values() if p._is_enabled()]

    def get_providers_by_capability(self, capability: str) -> list[MarketEventProvider]:
        return [p for p in self._providers.values() if capability in p.capabilities]

    async def run_health_checks(self) -> list[ProviderHealthCheckResult]:
        results = []
        for provider in self._providers.values():
            try:
                result = await provider.health_check()
                results.append(result)
            except Exception as exc:
                results.append(ProviderHealthCheckResult(
                    source_code=provider.source_code,
                    provider_name=provider.provider_name,
                    status="FAILED",
                    message=str(exc),
                    checked_at=datetime.now(timezone.utc),
                ))
        return results
