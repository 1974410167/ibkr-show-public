"""Market Event schemas -- enums (Literal types), DTOs, and ES document models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enum-like Literal types
# ---------------------------------------------------------------------------

MarketEventSourceCode = Literal[
    "BLS",
    "BEA",
    "FRED",
    "FED",
    "ISM",
    "LONGBRIDGE",
    "MANUAL",
    "SYSTEM",
]

MarketEventCategory = Literal[
    "MACRO",
    "FED",
    "COMPANY",
    "MARKET",
    "NEWS",
    "CRYPTO",
    "POLICY",
    "MANUAL",
]

MarketEventType = Literal[
    # Macro
    "CPI",
    "PPI",
    "NONFARM_PAYROLLS",
    "UNEMPLOYMENT_RATE",
    "JOLTS",
    "PCE",
    "GDP",
    "ISM_MANUFACTURING_PMI",
    "ISM_SERVICES_PMI",
    # Fed
    "FOMC_RATE_DECISION",
    "FOMC_MINUTES",
    "FOMC_SEP",
    "FED_SPEECH",
    # Company
    "EARNINGS",
    "DIVIDEND",
    "SPLIT",
    "IPO",
    "INVESTOR_DAY",
    "SHAREHOLDER_MEETING",
    # Market
    "MARKET_CLOSED",
    "HALF_TRADING_DAY",
    "TRADING_SESSION_CHANGE",
    # News / Policy
    "NEWS",
    "POLICY",
    "TARIFF",
    "EXPORT_CONTROL",
    "CRYPTO_EVENT",
    "BTC_EVENT",
    "MSTR_BTC_EVENT",
    # Other
    "MANUAL_EVENT",
    "UNKNOWN",
]

MarketEventStatus = Literal[
    "SCHEDULED",
    "WATCHING",
    "RELEASED",
    "VALUE_UPDATED",
    "INTERPRETED",
    "REVIEWED",
    "REVISED",
    "CANCELLED",
    "FAILED",
]

MarketEventImportance = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]

MarketEventValueType = Literal[
    "PREVIOUS",
    "FORECAST",
    "ACTUAL",
    "REVISED",
    "CONSENSUS",
    "LOW_ESTIMATE",
    "HIGH_ESTIMATE",
]

MarketEventImpactDirection = Literal[
    "POSITIVE",
    "NEGATIVE",
    "NEUTRAL",
    "UNCERTAIN",
    "MIXED",
]

MarketEventImpactLevel = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
]

MarketEventAnalysisType = Literal[
    "PRE_EVENT",
    "POST_EVENT",
    "DAILY_REVIEW",
    "MANUAL_NOTE",
]

MarketEventSyncStatus = Literal[
    "RUNNING",
    "SUCCESS",
    "PARTIAL_SUCCESS",
    "FAILED",
    "SKIPPED",
]

MarketEventSyncType = Literal[
    "CALENDAR",
    "VALUE",
    "NEWS",
    "CORPORATE",
    "MARKET_HOLIDAY",
    "MARKET_STATUS",
    "TRADING_SESSION",
    "FULL",
    "BACKFILL",
    "MANUAL",
]

MarketEventProviderCapability = Literal[
    "CALENDAR_EVENTS",
    "EVENT_VALUES",
    "NEWS_EVENTS",
    "CORPORATE_EVENTS",
    "MARKET_HOLIDAYS",
    "MARKET_STATUS",
    "TRADING_SESSIONS",
    "HEALTH_CHECK",
]

MarketEventTestStatus = Literal[
    "SUCCESS",
    "FAILED",
    "SKIPPED",
]


# ---------------------------------------------------------------------------
# ES document models (stored in ES indices)
# ---------------------------------------------------------------------------


class MarketEventSource(BaseModel):
    """Document stored in market_event_sources index."""

    source_code: MarketEventSourceCode
    source_name: str
    description: str = ""
    enabled: bool = True
    priority: int = 100
    base_url: str | None = None
    apply_url: str | None = None
    doc_url: str | None = None
    health_check_url: str | None = None
    requires_api_key: bool = False
    credential_key_name: str | None = None
    last_check_at: datetime | None = None
    last_check_status: MarketEventTestStatus | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventDefinition(BaseModel):
    """Document stored in market_event_definitions index."""

    event_code: str
    event_name: str
    category: MarketEventCategory
    event_type: MarketEventType
    default_importance: MarketEventImportance = "MEDIUM"
    country: str | None = None
    region: str | None = None
    market: str | None = None
    currency: str | None = None
    source_code: MarketEventSourceCode | None = None
    description: str = ""
    typical_release_rule: str | None = None
    default_watch_window_hours: int = 24
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventOccurrence(BaseModel):
    """Document stored in market_event_occurrences index."""

    definition_id: str | None = None
    source_code: MarketEventSourceCode
    source_event_id: str | None = None
    dedupe_key: str
    title: str
    summary: str = ""
    category: MarketEventCategory
    event_type: MarketEventType
    status: MarketEventStatus = "SCHEDULED"
    importance: MarketEventImportance = "MEDIUM"
    country: str | None = None
    region: str | None = None
    market: str | None = None
    symbols: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    scheduled_at: datetime
    scheduled_timezone: str = "UTC"
    period: str | None = None
    is_all_day: bool = False
    is_confirmed_time: bool = True
    source_url: str | None = None
    raw_payload_hash: str | None = None
    raw_payload: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventValue(BaseModel):
    """Document stored in market_event_values index."""

    occurrence_id: str
    value_type: MarketEventValueType
    label: str = ""
    value_text: str | None = None
    value_numeric: float | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    published_at: datetime | None = None
    source_code: MarketEventSourceCode | None = None
    raw_payload: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventImpact(BaseModel):
    """Document stored in market_event_impacts index."""

    occurrence_id: str
    symbol: str | None = None
    asset_class: str | None = None
    market: str | None = None
    sector: str | None = None
    industry: str | None = None
    impact_direction: MarketEventImpactDirection = "NEUTRAL"
    impact_level: MarketEventImpactLevel = "LOW"
    reason: str = ""
    confidence: float = 0.5
    source: str = "rule"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventNewsLink(BaseModel):
    """Document stored in market_event_news_links index."""

    occurrence_id: str
    source_code: MarketEventSourceCode | None = None
    news_id: str | None = None
    title: str = ""
    url: str = ""
    publisher: str = ""
    published_at: datetime | None = None
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventAnalysis(BaseModel):
    """Document stored in market_event_analysis index."""

    occurrence_id: str
    analysis_type: MarketEventAnalysisType
    title: str = ""
    content: str = ""
    model_name: str | None = None
    provider_name: str | None = None
    prompt_version: str | None = None
    confidence: float | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventSyncRun(BaseModel):
    """Document stored in market_event_sync_runs index."""

    source_code: MarketEventSourceCode
    provider_name: str
    sync_type: MarketEventSyncType
    status: MarketEventSyncStatus = "RUNNING"
    started_at: datetime
    finished_at: datetime | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    total_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    error_detail: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Input / Query DTOs
# ---------------------------------------------------------------------------


class MarketEventUpsertInput(BaseModel):
    """Input for upserting an event occurrence."""

    source_code: MarketEventSourceCode
    source_event_id: str | None = None
    title: str
    summary: str = ""
    category: MarketEventCategory
    event_type: MarketEventType
    status: MarketEventStatus = "SCHEDULED"
    importance: MarketEventImportance = "MEDIUM"
    country: str | None = None
    region: str | None = None
    market: str | None = None
    symbols: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    scheduled_at: datetime
    scheduled_timezone: str = "UTC"
    period: str | None = None
    is_all_day: bool = False
    is_confirmed_time: bool = True
    source_url: str | None = None
    raw_payload: dict[str, Any] | None = None
    definition_id: str | None = None


class MarketEventValueInput(BaseModel):
    """Input for upserting an event value."""

    occurrence_id: str
    value_type: MarketEventValueType
    label: str = ""
    value_text: str | None = None
    value_numeric: float | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    published_at: datetime | None = None
    source_code: MarketEventSourceCode | None = None
    raw_payload: dict[str, Any] | None = None


class MarketEventImpactInput(BaseModel):
    """Input for upserting an event impact."""

    occurrence_id: str
    symbol: str | None = None
    asset_class: str | None = None
    market: str | None = None
    sector: str | None = None
    industry: str | None = None
    impact_direction: MarketEventImpactDirection = "NEUTRAL"
    impact_level: MarketEventImpactLevel = "LOW"
    reason: str = ""
    confidence: float = 0.5
    source: str = "rule"


class MarketEventNewsLinkInput(BaseModel):
    """Input for upserting a news link."""

    occurrence_id: str
    source_code: MarketEventSourceCode | None = None
    news_id: str | None = None
    title: str = ""
    url: str = ""
    publisher: str = ""
    published_at: datetime | None = None
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None


class MarketEventQuery(BaseModel):
    """Query parameters for listing events."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    category: MarketEventCategory | None = None
    event_type: MarketEventType | None = None
    status: MarketEventStatus | None = None
    importance: MarketEventImportance | None = None
    source_code: MarketEventSourceCode | None = None
    symbol: str | None = None
    market: str | None = None
    country: str | None = None
    keyword: str | None = None
    has_actual_value: bool | None = None
    has_forecast_value: bool | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort_by: str = "scheduled_at"
    sort_order: Literal["asc", "desc"] = "asc"
    display_timezone: str = "Asia/Shanghai"
    include_values: bool = True
    include_impacts: bool = True
    include_news: bool = False
    include_analysis: bool = False


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class MarketEventValueResponse(BaseModel):
    """Value in API response."""

    value_type: MarketEventValueType
    label: str = ""
    value_text: str | None = None
    value_numeric: float | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    published_at: datetime | None = None


class MarketEventImpactResponse(BaseModel):
    """Impact in API response."""

    symbol: str | None = None
    asset_class: str | None = None
    market: str | None = None
    sector: str | None = None
    industry: str | None = None
    impact_direction: MarketEventImpactDirection
    impact_level: MarketEventImpactLevel
    reason: str = ""
    confidence: float = 0.5
    source: str = "rule"


class MarketEventNewsLinkResponse(BaseModel):
    """News link in API response."""

    title: str
    url: str
    publisher: str = ""
    published_at: datetime | None = None
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)


class MarketEventListItem(BaseModel):
    """Event item in list response."""

    id: str
    title: str
    summary: str = ""
    category: MarketEventCategory
    event_type: MarketEventType
    status: MarketEventStatus
    importance: MarketEventImportance
    source_code: MarketEventSourceCode
    country: str | None = None
    market: str | None = None
    symbols: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    scheduled_at: datetime
    scheduled_timezone: str = "UTC"
    display_time: str | None = None
    period: str | None = None
    is_all_day: bool = False
    is_confirmed_time: bool = True
    has_actual_value: bool = False
    has_forecast_value: bool = False
    source_url: str | None = None
    values: list[MarketEventValueResponse] = Field(default_factory=list)
    impacts: list[MarketEventImpactResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventDetail(BaseModel):
    """Event detail response."""

    id: str
    definition_id: str | None = None
    title: str
    summary: str = ""
    category: MarketEventCategory
    event_type: MarketEventType
    status: MarketEventStatus
    importance: MarketEventImportance
    source_code: MarketEventSourceCode
    country: str | None = None
    region: str | None = None
    market: str | None = None
    symbols: list[str] = Field(default_factory=list)
    asset_classes: list[str] = Field(default_factory=list)
    scheduled_at: datetime
    scheduled_timezone: str = "UTC"
    display_time: str | None = None
    period: str | None = None
    is_all_day: bool = False
    is_confirmed_time: bool = True
    source_url: str | None = None
    values: list[MarketEventValueResponse] = Field(default_factory=list)
    impacts: list[MarketEventImpactResponse] = Field(default_factory=list)
    news_links: list[MarketEventNewsLinkResponse] = Field(default_factory=list)
    analysis: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketEventRiskSummary(BaseModel):
    """Risk summary for a time window."""

    risk_level: MarketEventImportance
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    top_events: list[MarketEventListItem] = Field(default_factory=list)


class MarketEventRiskSummaryResponse(BaseModel):
    """Risk summary response with three windows."""

    today: MarketEventRiskSummary
    next_7_days: MarketEventRiskSummary
    next_30_days: MarketEventRiskSummary


class MarketEventCalendarDay(BaseModel):
    """A single day in the calendar view."""

    date: str
    risk_level: MarketEventImportance
    events: list[MarketEventListItem]


class MarketEventCalendarResponse(BaseModel):
    """Calendar view response."""

    days: list[MarketEventCalendarDay]


class MarketEventSourceStatusResponse(BaseModel):
    """Public source status (no secrets)."""

    source_code: MarketEventSourceCode
    source_name: str
    enabled: bool
    description: str = ""
    doc_url: str | None = None
    last_check_status: MarketEventTestStatus | None = None
    last_check_at: datetime | None = None
    last_sync_at: datetime | None = None


class MarketEventPaginatedResponse(BaseModel):
    """Paginated event list response."""

    items: list[MarketEventListItem]
    total: int
    limit: int
    offset: int


class MarketEventSyncRunResponse(BaseModel):
    """Sync run response."""

    id: str
    source_code: MarketEventSourceCode
    provider_name: str
    sync_type: MarketEventSyncType
    status: MarketEventSyncStatus
    started_at: datetime
    finished_at: datetime | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    total_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Admin DTOs
# ---------------------------------------------------------------------------


class MarketEventSourceConfigResponse(BaseModel):
    """Admin source config response."""

    source_code: MarketEventSourceCode
    source_name: str
    description: str = ""
    enabled: bool = True
    priority: int = 100
    apply_url: str | None = None
    doc_url: str | None = None
    requires_api_key: bool = False
    credential_key_name: str | None = None
    credential_configured: bool = False
    masked_value: str | None = None
    last_check_at: datetime | None = None
    last_check_status: MarketEventTestStatus | None = None
    last_error: str | None = None
    updated_at: datetime | None = None


class MarketEventSourceUpdateRequest(BaseModel):
    """Admin source update request."""

    enabled: bool | None = None
    priority: int | None = None
    description: str | None = None
    apply_url: str | None = None
    doc_url: str | None = None


class MarketEventCredentialUpdateRequest(BaseModel):
    """Admin credential update request."""

    credential_key: str = "api_key"
    value: str = Field(min_length=1)


class MarketEventSourceTestResponse(BaseModel):
    """Admin source test response."""

    source_code: MarketEventSourceCode
    status: MarketEventTestStatus
    message: str = ""


class MarketEventSyncRequest(BaseModel):
    """Sync request DTO."""

    source_codes: list[MarketEventSourceCode] | None = None
    capabilities: list[MarketEventProviderCapability] | None = None
    sync_types: list[MarketEventSyncType] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    markets: list[str] | None = None
    countries: list[str] | None = None
    symbols: list[str] | None = None
    keywords: list[str] | None = None
    force: bool = False
    dry_run: bool = False
    triggered_by: str | None = None


class MarketEventSyncResult(BaseModel):
    """Sync result DTO."""

    sync_run_id: str
    source_code: MarketEventSourceCode
    provider_name: str
    sync_type: MarketEventSyncType
    status: MarketEventSyncStatus
    total_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class UpsertResult(BaseModel):
    """Result of an upsert operation."""

    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    occurrence_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider DTOs
# ---------------------------------------------------------------------------


class ProviderHealthCheckResult(BaseModel):
    """Provider health check result."""

    source_code: MarketEventSourceCode
    provider_name: str
    status: MarketEventTestStatus
    message: str = ""
    checked_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class ProviderFetchResult(BaseModel):
    """Provider fetch result."""

    source_code: MarketEventSourceCode
    provider_name: str
    status: MarketEventSyncStatus
    events: list[MarketEventUpsertInput] = Field(default_factory=list)
    values: list[MarketEventValueInput] = Field(default_factory=list)
    impacts: list[MarketEventImpactInput] = Field(default_factory=list)
    news_links: list[MarketEventNewsLinkInput] = Field(default_factory=list)
    total_count: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


class ProviderCalendarQuery(BaseModel):
    """Query for fetching calendar events."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    market: str | None = None
    country: str | None = None
    categories: list[MarketEventCategory] | None = None
    event_types: list[MarketEventType] | None = None
    symbols: list[str] | None = None
    include_raw: bool = False


class ProviderValueQuery(BaseModel):
    """Query for fetching event values."""

    event_type: MarketEventType | None = None
    series_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    period: str | None = None
    country: str | None = None
    market: str | None = None
    include_raw: bool = False


class ProviderNewsQuery(BaseModel):
    """Query for fetching news events."""

    keyword: str | None = None
    symbols: list[str] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = 50
    language: str | None = None
    include_raw: bool = False


class ProviderCorporateQuery(BaseModel):
    """Query for fetching corporate events."""

    symbols: list[str] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_types: list[MarketEventType] | None = None
    market: str | None = None
    include_raw: bool = False


class ProviderMarketHolidayQuery(BaseModel):
    """Query for fetching market holidays."""

    market: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    include_raw: bool = False


class ProviderMarketStatusQuery(BaseModel):
    """Query for fetching market status."""

    markets: list[str] | None = None
    include_raw: bool = False


class ProviderTradingSessionQuery(BaseModel):
    """Query for fetching trading sessions."""

    markets: list[str] | None = None
    include_raw: bool = False
