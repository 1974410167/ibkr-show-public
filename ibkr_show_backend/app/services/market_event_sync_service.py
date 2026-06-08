"""Market Event Sync Service -- orchestrates sync runs across providers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.market_event import (
    MarketEventProviderCapability,
    MarketEventSourceCode,
    MarketEventSyncRequest,
    MarketEventSyncResult,
    MarketEventSyncRun,
    MarketEventSyncStatus,
    MarketEventSyncType,
    ProviderCalendarQuery,
    ProviderCorporateQuery,
    ProviderMarketHolidayQuery,
    ProviderMarketStatusQuery,
    ProviderNewsQuery,
    ProviderTradingSessionQuery,
    ProviderValueQuery,
    UpsertResult,
)
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_index import ensure_market_event_indices
from app.services.market_event_providers import MarketEventProviderRegistry
from app.services.market_event_repository import MarketEventRepository
from app.utils.market_event import utc_now

logger = logging.getLogger(__name__)


# Default time windows
DEFAULT_CALENDAR_DAYS = 90
DEFAULT_CORPORATE_DAYS = 90
DEFAULT_HOLIDAY_DAYS = 365
DEFAULT_NEWS_HOURS = 24
DEFAULT_VALUE_DAYS = 7


class MarketEventSyncService:
    """Orchestrates market event sync runs."""

    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
    ) -> None:
        self._es = es_client
        self._s = settings
        self._repo = MarketEventRepository(es_client, settings)
        self._cred_store = MarketEventCredentialStore(
            settings.market_event_credential_file,
            settings.config_encryption_key,
        )
        self._registry = MarketEventProviderRegistry(self._repo, self._cred_store)

    @property
    def registry(self) -> MarketEventProviderRegistry:
        return self._registry

    def _create_sync_run(
        self,
        source_code: str,
        provider_name: str,
        sync_type: MarketEventSyncType,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
    ) -> str:
        now = utc_now()
        doc = {
            "source_code": source_code,
            "provider_name": provider_name,
            "sync_type": sync_type,
            "status": "RUNNING",
            "started_at": now.isoformat(),
            "range_start": range_start.isoformat() if range_start else None,
            "range_end": range_end.isoformat() if range_end else None,
            "total_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
        }
        return self._repo.create_sync_run(doc)

    def _finish_sync_run(
        self,
        sync_run_id: str,
        status: MarketEventSyncStatus,
        upsert_result: UpsertResult | None = None,
        error_message: str | None = None,
    ) -> None:
        now = utc_now()
        updates: dict[str, Any] = {
            "status": status,
            "finished_at": now.isoformat(),
        }
        if upsert_result:
            updates["total_count"] = (
                upsert_result.created_count
                + upsert_result.updated_count
                + upsert_result.skipped_count
                + upsert_result.failed_count
            )
            updates["created_count"] = upsert_result.created_count
            updates["updated_count"] = upsert_result.updated_count
            updates["skipped_count"] = upsert_result.skipped_count
            updates["failed_count"] = upsert_result.failed_count
        if error_message:
            updates["error_message"] = error_message
        self._repo.update_sync_run(sync_run_id, updates)

    async def _run_sync_method(
        self,
        source_code: str,
        provider_name: str,
        sync_type: MarketEventSyncType,
        fetch_coro,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        sync_run_id = self._create_sync_run(
            source_code, provider_name, sync_type, range_start, range_end
        )
        try:
            result = await fetch_coro

            if result.status == "SKIPPED":
                self._finish_sync_run(sync_run_id, "SKIPPED", error_message=result.error_message)
                return MarketEventSyncResult(
                    sync_run_id=sync_run_id,
                    source_code=source_code,
                    provider_name=provider_name,
                    sync_type=sync_type,
                    status="SKIPPED",
                    error_message=result.error_message,
                )

            if result.status == "FAILED":
                self._finish_sync_run(sync_run_id, "FAILED", error_message=result.error_message)
                return MarketEventSyncResult(
                    sync_run_id=sync_run_id,
                    source_code=source_code,
                    provider_name=provider_name,
                    sync_type=sync_type,
                    status="FAILED",
                    error_message=result.error_message,
                )

            # Upsert events
            upsert_result = UpsertResult()
            fetched_count = result.total_count or len(result.events) + len(result.values) + len(result.news_links)
            if dry_run:
                upsert_result.skipped_count = fetched_count
            if not dry_run and result.events:
                upsert_result = self._repo.upsert_occurrences(result.events)

            if not dry_run and result.values:
                occurrence_ids = upsert_result.occurrence_ids
                for index, val in enumerate(result.values):
                    if not val.occurrence_id and len(occurrence_ids) == 1:
                        val.occurrence_id = occurrence_ids[0]
                    elif not val.occurrence_id and index < len(occurrence_ids):
                        val.occurrence_id = occurrence_ids[index]
                    if val.occurrence_id:
                        self._repo.upsert_values(val.occurrence_id, [val])

            if not dry_run and result.news_links:
                occurrence_ids = upsert_result.occurrence_ids
                for index, link in enumerate(result.news_links):
                    occurrence_id = link.occurrence_id
                    if not occurrence_id and len(occurrence_ids) == 1:
                        occurrence_id = occurrence_ids[0]
                    elif not occurrence_id and index < len(occurrence_ids):
                        occurrence_id = occurrence_ids[index]
                    if occurrence_id:
                        self._repo.upsert_news_link(occurrence_id, link)

            final_status: MarketEventSyncStatus = "SUCCESS"
            self._finish_sync_run(sync_run_id, final_status, upsert_result)
            return MarketEventSyncResult(
                sync_run_id=sync_run_id,
                source_code=source_code,
                provider_name=provider_name,
                sync_type=sync_type,
                status=final_status,
                total_count=fetched_count if dry_run else upsert_result.created_count + upsert_result.updated_count,
                created_count=upsert_result.created_count,
                updated_count=upsert_result.updated_count,
                skipped_count=upsert_result.skipped_count,
                failed_count=upsert_result.failed_count,
            )

        except Exception as exc:
            logger.error("Sync failed for %s/%s: %s", source_code, sync_type, exc)
            self._finish_sync_run(sync_run_id, "FAILED", error_message=str(exc))
            return MarketEventSyncResult(
                sync_run_id=sync_run_id,
                source_code=source_code,
                provider_name=provider_name,
                sync_type=sync_type,
                status="FAILED",
                error_message=str(exc),
            )

    async def sync_calendar_events(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        start = request.start_at or utc_now()
        end = request.end_at or (start + timedelta(days=DEFAULT_CALENDAR_DAYS))
        query = ProviderCalendarQuery(
            start_at=start,
            end_at=end,
            markets=request.markets,
            countries=request.countries,
            symbols=request.symbols,
        )
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "CALENDAR",
            provider.fetch_calendar_events(query),
            start, end, dry_run,
        )

    async def sync_event_values(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        start = request.start_at or (utc_now() - timedelta(days=DEFAULT_VALUE_DAYS))
        end = request.end_at or utc_now()
        query = ProviderValueQuery(
            start_at=start,
            end_at=end,
            countries=request.countries,
            markets=request.markets,
        )
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "VALUE",
            provider.fetch_event_values(query),
            start, end, dry_run,
        )

    async def sync_corporate_events(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        start = request.start_at or utc_now()
        end = request.end_at or (start + timedelta(days=DEFAULT_CORPORATE_DAYS))
        query = ProviderCorporateQuery(
            start_at=start,
            end_at=end,
            symbols=request.symbols,
            markets=request.markets,
        )
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "CORPORATE",
            provider.fetch_corporate_events(query),
            start, end, dry_run,
        )

    async def sync_news_events(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        start = request.start_at or (utc_now() - timedelta(hours=DEFAULT_NEWS_HOURS))
        end = request.end_at or utc_now()
        query = ProviderNewsQuery(
            start_at=start,
            end_at=end,
            symbols=request.symbols,
        )
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "NEWS",
            provider.fetch_news_events(query),
            start, end, dry_run,
        )

    async def sync_market_holidays(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        start = request.start_at or utc_now()
        end = request.end_at or (start + timedelta(days=DEFAULT_HOLIDAY_DAYS))
        query = ProviderMarketHolidayQuery(
            market=request.markets[0] if request.markets else None,
            start_at=start,
            end_at=end,
        )
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "MARKET_HOLIDAY",
            provider.fetch_market_holidays(query),
            start, end, dry_run,
        )

    async def sync_market_status(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        query = ProviderMarketStatusQuery(markets=request.markets)
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "MARKET_STATUS",
            provider.fetch_market_status(query),
            dry_run=dry_run,
        )

    async def sync_trading_sessions(
        self,
        provider,
        request: MarketEventSyncRequest,
        dry_run: bool = False,
    ) -> MarketEventSyncResult:
        query = ProviderTradingSessionQuery(markets=request.markets)
        return await self._run_sync_method(
            provider.source_code,
            provider.provider_name,
            "TRADING_SESSION",
            provider.fetch_trading_sessions(query),
            dry_run=dry_run,
        )

    async def sync_provider(
        self,
        source_code: str,
        request: MarketEventSyncRequest,
    ) -> list[MarketEventSyncResult]:
        """Sync all capabilities for a single provider."""
        provider = self._registry.get_provider(source_code)
        results = []
        dry_run = request.dry_run

        if not provider._is_enabled():
            return [MarketEventSyncResult(
                sync_run_id="",
                source_code=source_code,
                provider_name=provider.provider_name,
                sync_type="MANUAL",
                status="SKIPPED",
                error_message="Source is disabled",
            )]

        sync_types = request.sync_types or []

        if not sync_types or "CALENDAR" in sync_types:
            if "CALENDAR_EVENTS" in provider.capabilities:
                r = await self.sync_calendar_events(provider, request, dry_run)
                results.append(r)

        if not sync_types or "VALUE" in sync_types:
            if "EVENT_VALUES" in provider.capabilities:
                r = await self.sync_event_values(provider, request, dry_run)
                results.append(r)

        if not sync_types or "CORPORATE" in sync_types:
            if "CORPORATE_EVENTS" in provider.capabilities:
                r = await self.sync_corporate_events(provider, request, dry_run)
                results.append(r)

        if not sync_types or "NEWS" in sync_types:
            if "NEWS_EVENTS" in provider.capabilities:
                r = await self.sync_news_events(provider, request, dry_run)
                results.append(r)

        if not sync_types or "MARKET_HOLIDAY" in sync_types:
            if "MARKET_HOLIDAYS" in provider.capabilities:
                r = await self.sync_market_holidays(provider, request, dry_run)
                results.append(r)

        if not sync_types or "MARKET_STATUS" in sync_types:
            if "MARKET_STATUS" in provider.capabilities:
                r = await self.sync_market_status(provider, request, dry_run)
                results.append(r)

        if not sync_types or "TRADING_SESSION" in sync_types:
            if "TRADING_SESSIONS" in provider.capabilities:
                r = await self.sync_trading_sessions(provider, request, dry_run)
                results.append(r)

        return results

    async def sync_all(
        self,
        request: MarketEventSyncRequest,
    ) -> list[MarketEventSyncResult]:
        """Sync all enabled providers (or filtered by source_codes)."""
        if request.source_codes:
            providers = [self._registry.get_provider(c) for c in request.source_codes]
        else:
            providers = self._registry.get_enabled_providers()

        all_results = []
        for provider in providers:
            try:
                results = await self.sync_provider(provider.source_code, request)
                all_results.extend(results)
            except Exception as exc:
                all_results.append(MarketEventSyncResult(
                    sync_run_id="",
                    source_code=provider.source_code,
                    provider_name=provider.provider_name,
                    sync_type="MANUAL",
                    status="FAILED",
                    error_message=str(exc),
                ))
        return all_results
