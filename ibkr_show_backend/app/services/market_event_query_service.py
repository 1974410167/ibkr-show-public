"""Market Event query service -- list, detail, today, upcoming, risk, calendar."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.market_event import (
    MarketEventCalendarDay,
    MarketEventCalendarResponse,
    MarketEventDetail,
    MarketEventImpactResponse,
    MarketEventListItem,
    MarketEventNewsLinkResponse,
    MarketEventPaginatedResponse,
    MarketEventQuery,
    MarketEventRiskSummary,
    MarketEventRiskSummaryResponse,
    MarketEventSourceStatusResponse,
    MarketEventSyncRunResponse,
    MarketEventValueResponse,
)
from app.services.market_event_index import ensure_market_event_indices
from app.services.market_event_repository import MarketEventRepository
from app.utils.market_event import calculate_event_risk_level, utc_now

logger = logging.getLogger(__name__)

IMPORTANCE_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_INIT_LOCK = threading.Lock()
_INDICES_INITIALIZED = False


class MarketEventQueryService:
    """Query market events for API responses."""

    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self._es = es_client
        self._s = settings
        self._repo = MarketEventRepository(es_client, settings)
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        global _INDICES_INITIALIZED
        if _INDICES_INITIALIZED:
            return
        with _INIT_LOCK:
            if _INDICES_INITIALIZED:
                return
            ensure_market_event_indices(self._es)
            self._repo.seed_sources()
            _INDICES_INITIALIZED = True

    def _build_occurrence_query(self, query: MarketEventQuery) -> dict:
        """Build ES query body from MarketEventQuery."""
        must: list[dict] = []
        filter_clauses: list[dict] = []

        if query.start_at:
            filter_clauses.append({"range": {"scheduled_at": {"gte": query.start_at.isoformat()}}})
        if query.end_at:
            filter_clauses.append({"range": {"scheduled_at": {"lte": query.end_at.isoformat()}}})
        if query.category:
            filter_clauses.append({"term": {"category": query.category}})
        if query.event_type:
            filter_clauses.append({"term": {"event_type": query.event_type}})
        if query.status:
            filter_clauses.append({"term": {"status": query.status}})
        if query.importance:
            filter_clauses.append({"term": {"importance": query.importance}})
        if query.source_code:
            filter_clauses.append({"term": {"source_code": query.source_code}})
        if query.symbol:
            filter_clauses.append({"term": {"symbols": query.symbol.upper()}})
        if query.market:
            filter_clauses.append({"term": {"market": query.market.upper()}})
        if query.country:
            filter_clauses.append({"term": {"country": query.country.upper()}})
        if query.keyword:
            must.append({
                "multi_match": {
                    "query": query.keyword,
                    "fields": ["title^2", "summary", "event_name"],
                }
            })

        if not filter_clauses and not must:
            return {"match_all": {}}

        return {"bool": {"must": must or [{"match_all": {}}], "filter": filter_clauses}}

    def _build_sort(self, query: MarketEventQuery) -> list:
        if query.sort_by == "importance":
            # Custom sort by importance level
            return [{"importance": {"order": query.sort_order}}]
        return [{query.sort_by: {"order": query.sort_order}}]

    def _doc_to_list_item(self, doc: dict, values: list[dict] | None = None, impacts: list[dict] | None = None) -> MarketEventListItem:
        """Convert ES document to MarketEventListItem."""
        value_responses = []
        if values:
            for v in values:
                value_responses.append(MarketEventValueResponse(
                    value_type=v.get("value_type", "ACTUAL"),
                    label=v.get("label", ""),
                    value_text=v.get("value_text"),
                    value_numeric=v.get("value_numeric"),
                    unit=v.get("unit"),
                    currency=v.get("currency"),
                    period=v.get("period"),
                    published_at=v.get("published_at"),
                ))

        impact_responses = []
        if impacts:
            for imp in impacts:
                impact_responses.append(MarketEventImpactResponse(
                    symbol=imp.get("symbol"),
                    asset_class=imp.get("asset_class"),
                    market=imp.get("market"),
                    sector=imp.get("sector"),
                    industry=imp.get("industry"),
                    impact_direction=imp.get("impact_direction", "NEUTRAL"),
                    impact_level=imp.get("impact_level", "LOW"),
                    reason=imp.get("reason", ""),
                    confidence=imp.get("confidence", 0.5),
                    source=imp.get("source", "rule"),
                ))

        has_actual = any(v.get("value_type") == "ACTUAL" and v.get("value_numeric") is not None for v in (values or []))
        has_forecast = any(v.get("value_type") == "FORECAST" and v.get("value_numeric") is not None for v in (values or []))

        return MarketEventListItem(
            id=doc.get("_id", doc.get("dedupe_key", "")),
            title=doc.get("title", ""),
            summary=doc.get("summary", ""),
            category=doc.get("category", "MACRO"),
            event_type=doc.get("event_type", "UNKNOWN"),
            status=doc.get("status", "SCHEDULED"),
            importance=doc.get("importance", "MEDIUM"),
            source_code=doc.get("source_code", "UNKNOWN"),
            country=doc.get("country"),
            market=doc.get("market"),
            symbols=doc.get("symbols", []),
            asset_classes=doc.get("asset_classes", []),
            scheduled_at=doc.get("scheduled_at", utc_now()),
            scheduled_timezone=doc.get("scheduled_timezone", "UTC"),
            period=doc.get("period"),
            is_all_day=doc.get("is_all_day", False),
            is_confirmed_time=doc.get("is_confirmed_time", True),
            has_actual_value=has_actual,
            has_forecast_value=has_forecast,
            source_url=doc.get("source_url"),
            values=value_responses,
            impacts=impact_responses,
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    def list_events(self, query: MarketEventQuery) -> MarketEventPaginatedResponse:
        """List events with filtering, sorting, and pagination."""
        es_query = self._build_occurrence_query(query)
        sort = self._build_sort(query)

        docs, total = self._repo.list_occurrences(
            es_query, size=query.limit, from_=query.offset, sort=sort
        )

        items = []
        for doc in docs:
            values = self._repo.get_values_for_occurrence(doc.get("_id", "")) if query.include_values else []
            impacts = self._repo.get_impacts_for_occurrence(doc.get("_id", "")) if query.include_impacts else []
            items.append(self._doc_to_list_item(doc, values, impacts))

        return MarketEventPaginatedResponse(items=items, total=total, limit=query.limit, offset=query.offset)

    def get_event_detail(self, event_id: str, include_raw: bool = False) -> MarketEventDetail | None:
        """Get full event detail."""
        doc = self._repo.get_occurrence(event_id)
        if not doc:
            return None

        values = self._repo.get_values_for_occurrence(event_id)
        impacts = self._repo.get_impacts_for_occurrence(event_id)
        news_links = self._repo.get_news_links_for_occurrence(event_id)
        analysis = self._repo.get_analysis_for_occurrence(event_id)

        value_responses = [MarketEventValueResponse(
            value_type=v.get("value_type", "ACTUAL"),
            label=v.get("label", ""),
            value_text=v.get("value_text"),
            value_numeric=v.get("value_numeric"),
            unit=v.get("unit"),
            currency=v.get("currency"),
            period=v.get("period"),
            published_at=v.get("published_at"),
        ) for v in values]

        impact_responses = [MarketEventImpactResponse(
            symbol=imp.get("symbol"),
            asset_class=imp.get("asset_class"),
            market=imp.get("market"),
            sector=imp.get("sector"),
            industry=imp.get("industry"),
            impact_direction=imp.get("impact_direction", "NEUTRAL"),
            impact_level=imp.get("impact_level", "LOW"),
            reason=imp.get("reason", ""),
            confidence=imp.get("confidence", 0.5),
            source=imp.get("source", "rule"),
        ) for imp in impacts]

        news_responses = [MarketEventNewsLinkResponse(
            title=nl.get("title", ""),
            url=nl.get("url", ""),
            publisher=nl.get("publisher", ""),
            published_at=nl.get("published_at"),
            summary=nl.get("summary", ""),
            symbols=nl.get("symbols", []),
        ) for nl in news_links]

        return MarketEventDetail(
            id=event_id,
            definition_id=doc.get("definition_id"),
            title=doc.get("title", ""),
            summary=doc.get("summary", ""),
            category=doc.get("category", "MACRO"),
            event_type=doc.get("event_type", "UNKNOWN"),
            status=doc.get("status", "SCHEDULED"),
            importance=doc.get("importance", "MEDIUM"),
            source_code=doc.get("source_code", "UNKNOWN"),
            country=doc.get("country"),
            region=doc.get("region"),
            market=doc.get("market"),
            symbols=doc.get("symbols", []),
            asset_classes=doc.get("asset_classes", []),
            scheduled_at=doc.get("scheduled_at", utc_now()),
            scheduled_timezone=doc.get("scheduled_timezone", "UTC"),
            period=doc.get("period"),
            is_all_day=doc.get("is_all_day", False),
            is_confirmed_time=doc.get("is_confirmed_time", True),
            source_url=doc.get("source_url"),
            values=value_responses,
            impacts=impact_responses,
            news_links=news_responses,
            analysis=analysis,
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    def get_today_events(self, display_timezone: str = "Asia/Shanghai", **kwargs) -> MarketEventPaginatedResponse:
        """Get events for today in the specified timezone."""
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(display_timezone)
        except Exception:
            tz = zoneinfo.ZoneInfo("UTC")

        now = datetime.now(tz)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        query = MarketEventQuery(
            start_at=start_of_day.astimezone(timezone.utc),
            end_at=end_of_day.astimezone(timezone.utc),
            importance=kwargs.get("importance"),
            market=kwargs.get("market"),
            symbol=kwargs.get("symbol"),
        )
        return self.list_events(query)

    def get_upcoming_events(self, days: int = 7, **kwargs) -> MarketEventPaginatedResponse:
        """Get upcoming events for the next N days."""
        now = utc_now()
        query = MarketEventQuery(
            start_at=now,
            end_at=now + timedelta(days=days),
            importance=kwargs.get("importance"),
            market=kwargs.get("market"),
            symbol=kwargs.get("symbol"),
            category=kwargs.get("category"),
        )
        return self.list_events(query)

    def get_risk_summary(self, display_timezone: str = "Asia/Shanghai") -> MarketEventRiskSummaryResponse:
        """Get risk summary for today, next 7 days, and next 30 days."""
        now = utc_now()

        def _summary(days: int) -> MarketEventRiskSummary:
            query = MarketEventQuery(start_at=now, end_at=now + timedelta(days=days), limit=200)
            result = self.list_events(query)
            event_dicts = [{"importance": item.importance} for item in result.items]
            level, critical, high, medium, low = calculate_event_risk_level(event_dicts)

            top_items = sorted(
                result.items,
                key=lambda x: IMPORTANCE_ORDER.get(x.importance, 99),
            )[:5]

            return MarketEventRiskSummary(
                risk_level=level,
                critical_count=critical,
                high_count=high,
                medium_count=medium,
                low_count=low,
                top_events=top_items,
            )

        return MarketEventRiskSummaryResponse(
            today=_summary(1),
            next_7_days=_summary(7),
            next_30_days=_summary(30),
        )

    def get_calendar_events(
        self, start_at: datetime | None = None, end_at: datetime | None = None,
        display_timezone: str = "Asia/Shanghai", **kwargs
    ) -> MarketEventCalendarResponse:
        """Get events grouped by date for calendar view."""
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(display_timezone)
        except Exception:
            tz = zoneinfo.ZoneInfo("UTC")

        now = utc_now()
        start = start_at or now
        end = end_at or (now + timedelta(days=30))

        query = MarketEventQuery(
            start_at=start, end_at=end, limit=200,
            category=kwargs.get("category"),
            market=kwargs.get("market"),
            symbol=kwargs.get("symbol"),
        )
        result = self.list_events(query)

        # Group by date in display timezone
        day_map: dict[str, list[MarketEventListItem]] = {}
        for item in result.items:
            dt = item.scheduled_at.astimezone(tz) if item.scheduled_at.tzinfo else item.scheduled_at.replace(tzinfo=timezone.utc).astimezone(tz)
            date_str = dt.strftime("%Y-%m-%d")
            day_map.setdefault(date_str, []).append(item)

        days = []
        for date_str in sorted(day_map.keys()):
            events = day_map[date_str]
            event_dicts = [{"importance": e.importance} for e in events]
            level, _, _, _, _ = calculate_event_risk_level(event_dicts)
            days.append(MarketEventCalendarDay(date=date_str, risk_level=level, events=events))

        return MarketEventCalendarResponse(days=days)

    def get_symbol_events(self, symbol: str, days: int = 30, include_macro: bool = True, **kwargs) -> MarketEventPaginatedResponse:
        """Get events affecting a specific symbol."""
        now = utc_now()
        # Direct symbol match
        query = MarketEventQuery(
            start_at=now, end_at=now + timedelta(days=days),
            symbol=symbol, limit=50,
        )
        result = self.list_events(query)

        if include_macro:
            # Add high-importance macro events
            macro_query = MarketEventQuery(
                start_at=now, end_at=now + timedelta(days=days),
                category="MACRO", importance="HIGH", limit=20,
            )
            macro_result = self.list_events(macro_query)
            existing_ids = {item.id for item in result.items}
            for item in macro_result.items:
                if item.id not in existing_ids:
                    result.items.append(item)

        return result

    def list_sources(self) -> list[MarketEventSourceStatusResponse]:
        """List public source status."""
        sources = self._repo.list_sources()
        return [MarketEventSourceStatusResponse(
            source_code=s.get("source_code", ""),
            source_name=s.get("source_name", ""),
            enabled=s.get("enabled", True),
            description=s.get("description", ""),
            doc_url=s.get("doc_url"),
            last_check_status=s.get("last_check_status"),
            last_check_at=s.get("last_check_at"),
        ) for s in sources]

    def list_sync_runs(self, query_body: dict | None = None, size: int = 50, offset: int = 0) -> tuple[list[MarketEventSyncRunResponse], int]:
        """List sync runs."""
        docs, total = self._repo.list_sync_runs(query_body, size=size, from_=offset)
        items = [MarketEventSyncRunResponse(
            id=d.get("_id", ""),
            source_code=d.get("source_code", ""),
            provider_name=d.get("provider_name", ""),
            sync_type=d.get("sync_type", "MANUAL"),
            status=d.get("status", "RUNNING"),
            started_at=d.get("started_at", utc_now()),
            finished_at=d.get("finished_at"),
            range_start=d.get("range_start"),
            range_end=d.get("range_end"),
            total_count=d.get("total_count", 0),
            created_count=d.get("created_count", 0),
            updated_count=d.get("updated_count", 0),
            skipped_count=d.get("skipped_count", 0),
            failed_count=d.get("failed_count", 0),
            error_message=d.get("error_message"),
        ) for d in docs]
        return items, total
