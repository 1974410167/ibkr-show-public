"""Real Market Event Provider implementations -- BLS, BEA, Fed, Longbridge."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.schemas.market_event import (
    MarketEventCategory,
    MarketEventImportance,
    MarketEventNewsLinkInput,
    MarketEventType,
    MarketEventUpsertInput,
    MarketEventValueInput,
    ProviderCalendarQuery,
    ProviderCorporateQuery,
    ProviderFetchResult,
    ProviderHealthCheckResult,
    ProviderMarketHolidayQuery,
    ProviderMarketStatusQuery,
    ProviderNewsQuery,
    ProviderValueQuery,
)
from app.core.config import get_settings
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_providers import (
    BeaProvider,
    BlsProvider,
    FedProvider,
    FredProvider,
    LongbridgeProvider,
)
from app.services.market_event_repository import MarketEventRepository
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthService
from app.services.longbridge_service import (
    LongbridgeExternalDataClient,
    LongbridgeExternalDataError,
    LongbridgeUnavailableError,
    normalize_longbridge_symbol,
)
from app.utils.market_event import utc_now

logger = logging.getLogger(__name__)

# BLS series IDs
BLS_SERIES: dict[str, tuple[str, MarketEventType, MarketEventImportance]] = {
    "CUUR0000SA0": ("CPI", "CPI", "CRITICAL"),
    "WPUFD4": ("PPI", "PPI", "HIGH"),
    "CES0000000001": ("Nonfarm Payrolls", "NONFARM_PAYROLLS", "CRITICAL"),
    "LNS14000000": ("Unemployment Rate", "UNEMPLOYMENT_RATE", "CRITICAL"),
    "JTSJOL": ("JOLTS", "JOLTS", "HIGH"),
}

# BLS ICS title -> event type mapping
BLS_ICS_TITLE_MAP: dict[str, tuple[MarketEventType, MarketEventImportance]] = {
    "consumer price index": ("CPI", "CRITICAL"),
    "producer price index": ("PPI", "HIGH"),
    "employment situation": ("NONFARM_PAYROLLS", "CRITICAL"),
    "job openings and labor turnover": ("JOLTS", "HIGH"),
}

# BEA release -> event type mapping
BEA_RELEASE_MAP: dict[str, tuple[MarketEventType, MarketEventImportance]] = {
    "gdp": ("GDP", "HIGH"),
    "gross domestic product": ("GDP", "HIGH"),
    "personal income": ("PCE", "CRITICAL"),
}

HTTP_TIMEOUT = 15.0
HTTP_HEADERS = {
    "User-Agent": "ibkr-show/1.0 (+https://gehaoyuan.top; market-event-calendar)",
    "Accept": "application/json,text/calendar,text/html;q=0.9,*/*;q=0.8",
}


def _safe_http_get(url: str, params: dict | None = None, timeout: float = HTTP_TIMEOUT) -> httpx.Response | None:
    """Make an HTTP GET request, returning None on failure."""
    try:
        resp = httpx.get(url, params=params, headers=HTTP_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception as exc:
        logger.warning("HTTP GET failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Enhanced BLS Provider
# ---------------------------------------------------------------------------


class RealBlsProvider(BlsProvider):
    """BLS provider with real ICS calendar and API value fetching."""

    BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
    BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)

        key = self._get_api_key()
        if key:
            # Try a minimal API call
            resp = _safe_http_get(
                self.BLS_API_URL + "CUUR0000SA0",
                params={"latest": "true", "registrationkey": key},
            )
            if resp and resp.status_code == 200:
                return self._health_result("SUCCESS", "BLS API reachable")
            return self._health_result("FAILED", "BLS API request failed")
        return self._health_result("SUCCESS", "Key configured; real check in sync phase")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._skipped_result(msg)

        resp = _safe_http_get(self.BLS_CALENDAR_URL)
        if not resp:
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="FAILED",
                error_message="Failed to fetch BLS calendar",
            )

        events = self._parse_ics(resp.text, query)
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            events=events,
            total_count=len(events),
        )

    def _parse_ics(self, ics_text: str, query: ProviderCalendarQuery) -> list[MarketEventUpsertInput]:
        """Parse BLS ICS feed into event inputs."""
        events: list[MarketEventUpsertInput] = []
        current: dict[str, str] = {}

        for line in ics_text.splitlines():
            line = line.strip()
            if line == "BEGIN:VEVENT":
                current = {}
            elif line == "END:VEVENT":
                if current.get("summary"):
                    event = self._map_ics_event(current, query)
                    if event:
                        events.append(event)
                current = {}
            elif ":" in line:
                key, _, value = line.partition(":")
                current[key.lower()] = value

        return events

    def _map_ics_event(
        self, ics: dict[str, str], query: ProviderCalendarQuery
    ) -> MarketEventUpsertInput | None:
        summary = ics.get("summary", "").lower()
        # Handle DTSTART with or without TZID prefix
        dtstart = ics.get("dtstart", "")
        if not dtstart:
            for k, v in ics.items():
                if k.startswith("dtstart"):
                    dtstart = v
                    break

        event_type = None
        importance: MarketEventImportance = "MEDIUM"
        for pattern, (et, imp) in BLS_ICS_TITLE_MAP.items():
            if pattern in summary:
                event_type = et
                importance = imp
                break

        if not event_type:
            return None

        # Filter by requested event types
        if query.event_types and event_type not in query.event_types:
            return None

        # Parse date
        scheduled_at = self._parse_ics_date(dtstart)
        if not scheduled_at:
            return None

        # Filter by date range
        if query.start_at and scheduled_at < query.start_at:
            return None
        if query.end_at and scheduled_at > query.end_at:
            return None

        return MarketEventUpsertInput(
            source_code="BLS",
            title=ics.get("summary", ""),
            summary=ics.get("description", ""),
            category="MACRO",
            event_type=event_type,
            importance=importance,
            country="US",
            market="US",
            scheduled_at=scheduled_at,
            scheduled_timezone="America/New_York",
            is_confirmed_time=True,
            source_url=ics.get("url", "https://www.bls.gov/schedule/"),
            raw_payload=ics,
        )

    def _parse_ics_date(self, dtstart: str) -> datetime | None:
        """Parse ICS date like 20260610T083000."""
        if not dtstart:
            return None
        try:
            # Remove TZID prefix if present
            if "T" in dtstart:
                clean = dtstart.split(":")[-1] if ":" in dtstart else dtstart
                dt = datetime.strptime(clean[:15], "%Y%m%dT%H%M%S")
            else:
                dt = datetime.strptime(dtstart[:8], "%Y%m%d")
            return dt.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        except (ValueError, IndexError):
            return None

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._skipped_result(msg)

        key = self._get_api_key()
        if not key:
            return self._skipped_result("BLS API key not configured")

        values: list[MarketEventValueInput] = []
        for series_id, (name, event_type, _) in BLS_SERIES.items():
            if query.event_type and event_type != query.event_type:
                continue
            resp = _safe_http_get(
                self.BLS_API_URL + series_id,
                params={"latest": "true", "registrationkey": key},
            )
            if not resp:
                continue
            try:
                data = resp.json()
                series_list = data.get("Results", {}).get("series", [])
                for series in series_list:
                    for item in series.get("data", [])[:1]:  # Latest value
                        values.append(MarketEventValueInput(
                            occurrence_id="",  # Will be matched later
                            value_type="ACTUAL",
                            label=f"{name} Latest",
                            value_text=f"{item.get('value', '')} {item.get('periodName', '')}",
                            value_numeric=float(item.get("value", 0)) if item.get("value") else None,
                            unit=item.get("periodName", ""),
                            period=item.get("year", ""),
                            source_code="BLS",
                        ))
            except Exception as exc:
                logger.warning("Failed to parse BLS response for %s: %s", series_id, exc)

        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            values=values,
            total_count=len(values),
        )


# ---------------------------------------------------------------------------
# Enhanced BEA Provider
# ---------------------------------------------------------------------------


class RealBeaProvider(BeaProvider):
    """BEA provider with release schedule and value fetching."""

    BEA_API_URL = "https://apps.bea.gov/api/data"
    BEA_RELEASE_SCHEDULE_URL = "https://www.bea.gov/news/schedule"

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)

        key = self._get_api_key()
        if key:
            resp = _safe_http_get(
                self.BEA_API_URL,
                params={"UserID": key, "method": "GETDATASETLIST", "ResultFormat": "JSON"},
            )
            if resp and resp.status_code == 200:
                return self._health_result("SUCCESS", "BEA API reachable")
            return self._health_result("FAILED", "BEA API request failed")
        return self._health_result("SUCCESS", "Key configured")

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._skipped_result(msg)

        resp = _safe_http_get(self.BEA_RELEASE_SCHEDULE_URL)
        if not resp:
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="FAILED",
                error_message="Failed to fetch BEA release schedule",
            )

        events = self._parse_release_schedule(resp.text, query)
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            events=events,
            total_count=len(events),
        )

    def _parse_release_schedule(self, html: str, query: ProviderCalendarQuery) -> list[MarketEventUpsertInput]:
        """Parse BEA Release Schedule HTML into event inputs."""
        events: list[MarketEventUpsertInput] = []
        text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)

        year_match = re.search(r"\bYear\s+(?P<year>\d{4})\s+Release\b", text, flags=re.IGNORECASE)
        if year_match:
            start = year_match.end()
            end_match = re.search(r"\b(?:Additional Formats|Additional Archives)\b", text[start:], flags=re.IGNORECASE)
            section = text[start:start + end_match.start()] if end_match else text[start:]
            events = self._parse_release_schedule_year_section(section, year_match.group("year"), query)
            if events:
                return events

        pattern = re.compile(
            r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})"
            r"(?:\s+(?P<time>\d{1,2}:\d{2}\s*(?:A\.M\.|P\.M\.|AM|PM)))?"
            r"\s+(?P<title>[^.]{3,180}?)"
            r"(?=(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}|$)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            title = match.group("title").strip(" -:\u2013")
            mapped = self._map_release_title(title)
            if not mapped:
                continue
            event_type, importance = mapped
            if query.event_types and event_type not in query.event_types:
                continue

            scheduled_at = self._parse_release_datetime(
                match.group("year"),
                match.group("month"),
                match.group("day"),
                match.group("time"),
            )
            if not scheduled_at:
                continue
            if query.start_at and scheduled_at < query.start_at:
                continue
            if query.end_at and scheduled_at > query.end_at:
                continue

            events.append(MarketEventUpsertInput(
                source_code="BEA",
                title=title,
                summary="BEA Release Schedule",
                category="MACRO",
                event_type=event_type,
                importance=importance,
                country="US",
                market="US",
                scheduled_at=scheduled_at,
                scheduled_timezone="America/New_York",
                is_confirmed_time=bool(match.group("time")),
                source_url=self.BEA_RELEASE_SCHEDULE_URL,
                raw_payload={
                    "title": title,
                    "date": f"{match.group('month')} {match.group('day')}, {match.group('year')}",
                    "time": match.group("time") or "",
                },
            ))
        return events

    def _parse_release_schedule_year_section(
        self,
        text: str,
        year: str,
        query: ProviderCalendarQuery,
    ) -> list[MarketEventUpsertInput]:
        """Parse BEA schedule entries where the year appears once in the section heading."""
        events: list[MarketEventUpsertInput] = []
        item_pattern = re.compile(
            r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(?P<day>\d{1,2})\s+"
            r"(?P<time>\d{1,2}:\d{2}\s*(?:A\.M\.|P\.M\.|AM|PM))\s+"
            r"(?:N\s*ews|D\s*ata|V\s*isual\s+Data|A\s*rticle)\s+"
            r"(?P<title>.*?)(?="
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2}\s+\d{1,2}:\d{2}\s*(?:A\.M\.|P\.M\.|AM|PM)\s+"
            r"(?:N\s*ews|D\s*ata|V\s*isual\s+Data|A\s*rticle)"
            r"|To Be Announced|$)",
            re.IGNORECASE,
        )
        for match in item_pattern.finditer(text):
            title = match.group("title").strip(" -:\u2013")
            mapped = self._map_release_title(title)
            if not mapped:
                continue
            event_type, importance = mapped
            if query.event_types and event_type not in query.event_types:
                continue

            scheduled_at = self._parse_release_datetime(
                year,
                match.group("month"),
                match.group("day"),
                match.group("time"),
            )
            if not scheduled_at:
                continue
            if query.start_at and scheduled_at < query.start_at:
                continue
            if query.end_at and scheduled_at > query.end_at:
                continue

            events.append(MarketEventUpsertInput(
                source_code="BEA",
                title=title,
                summary="BEA Release Schedule",
                category="MACRO",
                event_type=event_type,
                importance=importance,
                country="US",
                market="US",
                scheduled_at=scheduled_at,
                scheduled_timezone="America/New_York",
                is_confirmed_time=True,
                source_url=self.BEA_RELEASE_SCHEDULE_URL,
                raw_payload={
                    "title": title,
                    "date": f"{match.group('month')} {match.group('day')}, {year}",
                    "time": match.group("time"),
                },
            ))
        return events

    def _map_release_title(self, title: str) -> tuple[MarketEventType, MarketEventImportance] | None:
        normalized = title.lower()
        for pattern, mapped in BEA_RELEASE_MAP.items():
            if pattern in normalized:
                return mapped
        return None

    def _parse_release_datetime(
        self,
        year: str,
        month: str,
        day: str,
        time_text: str | None,
    ) -> datetime | None:
        try:
            month_num = datetime.strptime(month, "%B").month
            hour = 8
            minute = 30
            if time_text:
                normalized = time_text.upper().replace(".", "").replace(" ", "")
                time_match = re.match(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<ampm>AM|PM)", normalized)
                if time_match:
                    hour = int(time_match.group("hour"))
                    minute = int(time_match.group("minute"))
                    if time_match.group("ampm") == "PM" and hour != 12:
                        hour += 12
                    if time_match.group("ampm") == "AM" and hour == 12:
                        hour = 0
            local = datetime(int(year), month_num, int(day), hour, minute, tzinfo=ZoneInfo("America/New_York"))
            return local.astimezone(timezone.utc)
        except ValueError:
            return None

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._skipped_result(msg)

        key = self._get_api_key()
        if not key:
            return self._skipped_result("BEA API key not configured")

        # Try to get GDP data
        values: list[MarketEventValueInput] = []
        resp = _safe_http_get(
            self.BEA_API_URL,
            params={
                "UserID": key,
                "method": "GetData",
                "datasetname": "NIPA",
                "TableName": "T10101",
                "Frequency": "Q",
                "Year": "latest",
                "ResultFormat": "JSON",
            },
        )
        if resp:
            try:
                data = resp.json()
                # Parse BEA NIPA response
                results = data.get("BEAAPI", {}).get("Results", {})
                data_list = results.get("Data", [])
                for item in data_list[:5]:  # Take first few
                    values.append(MarketEventValueInput(
                        occurrence_id="",
                        value_type="ACTUAL",
                        label=item.get("LineNumber", ""),
                        value_text=item.get("DataValue", ""),
                        value_numeric=float(item.get("DataValue", "0").replace(",", "")) if item.get("DataValue") else None,
                        unit=item.get("CL_UNIT", ""),
                        period=f"{item.get('Year', '')}Q{item.get('Quarter', '')}",
                        source_code="BEA",
                    ))
            except Exception as exc:
                logger.warning("Failed to parse BEA response: %s", exc)

        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            values=values,
            total_count=len(values),
        )


# ---------------------------------------------------------------------------
# Enhanced FRED Provider
# ---------------------------------------------------------------------------


FRED_SERIES: dict[str, tuple[str, MarketEventType, str]] = {
    "CPIAUCSL": ("CPI", "CPI", "Index 1982-1984=100"),
    "PPIACO": ("PPI", "PPI", "Index 1982=100"),
    "UNRATE": ("Unemployment Rate", "UNEMPLOYMENT_RATE", "Percent"),
    "PAYEMS": ("Nonfarm Payrolls", "NONFARM_PAYROLLS", "Thousands of Persons"),
}


class RealFredProvider(FredProvider):
    """FRED provider with real readonly API health and latest value fetching."""

    FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

    async def health_check(self) -> ProviderHealthCheckResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._health_result("SKIPPED", msg)

        key = self._get_api_key()
        if not key:
            return self._health_result("SKIPPED", "FRED API key not configured")
        resp = _safe_http_get(
            self.FRED_OBSERVATIONS_URL,
            params={
                "series_id": "CPIAUCSL",
                "api_key": key,
                "file_type": "json",
                "limit": 1,
                "sort_order": "desc",
            },
        )
        if not resp:
            return self._health_result("FAILED", "FRED API request failed")
        try:
            data = resp.json()
        except ValueError:
            return self._health_result("FAILED", "FRED API returned non-JSON response")
        if data.get("observations"):
            return self._health_result("SUCCESS", "FRED API reachable")
        return self._health_result("FAILED", "FRED API returned no observations")

    async def fetch_event_values(self, query: ProviderValueQuery) -> ProviderFetchResult:
        ok, msg = self._check_ready()
        if not ok:
            return self._skipped_result(msg)

        key = self._get_api_key()
        if not key:
            return self._skipped_result("FRED API key not configured")

        values: list[MarketEventValueInput] = []
        series_items = FRED_SERIES.items()
        if query.series_id:
            series_items = [(k, v) for k, v in FRED_SERIES.items() if k == query.series_id]

        for series_id, (label, event_type, unit) in series_items:
            if query.event_type and event_type != query.event_type:
                continue
            resp = _safe_http_get(
                self.FRED_OBSERVATIONS_URL,
                params={
                    "series_id": series_id,
                    "api_key": key,
                    "file_type": "json",
                    "limit": 1,
                    "sort_order": "desc",
                },
            )
            if not resp:
                continue
            try:
                data = resp.json()
                observations = data.get("observations", [])
                if not observations:
                    continue
                item = observations[0]
                raw_value = item.get("value")
                value_numeric = None
                if raw_value not in {None, "."}:
                    value_numeric = float(raw_value)
                values.append(MarketEventValueInput(
                    occurrence_id="",
                    value_type="ACTUAL",
                    label=f"{label} Latest",
                    value_text=None if raw_value in {None, "."} else str(raw_value),
                    value_numeric=value_numeric,
                    unit=unit,
                    period=item.get("date"),
                    source_code="FRED",
                    raw_payload={"series_id": series_id, "date": item.get("date")},
                ))
            except Exception as exc:
                logger.warning("Failed to parse FRED response for %s: %s", series_id, exc)

        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            values=values,
            total_count=len(values),
        )


# ---------------------------------------------------------------------------
# Enhanced Fed Provider
# ---------------------------------------------------------------------------


class RealFedProvider(FedProvider):
    """Fed provider with FOMC calendar parsing."""

    FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        if not self._is_enabled():
            return self._skipped_result("Source is disabled")

        resp = _safe_http_get(self.FOMC_CALENDAR_URL)
        if not resp:
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="FAILED",
                error_message="Failed to fetch Fed FOMC calendar",
            )

        events = self._parse_fomc_html(resp.text, query)
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="SUCCESS",
            events=events,
            total_count=len(events),
        )

    def _parse_fomc_html(self, html: str, query: ProviderCalendarQuery) -> list[MarketEventUpsertInput]:
        """Simple FOMC date extraction from HTML."""
        events: list[MarketEventUpsertInput] = []
        text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)

        for year_match in re.finditer(r"\b(?P<year>20\d{2})\s+FOMC\s+Meetings\b", text, re.IGNORECASE):
            current_year = int(year_match.group("year"))
            section_start = year_match.end()
            next_year = re.search(r"\b20\d{2}\s+FOMC\s+Meetings\b", text[section_start:], re.IGNORECASE)
            section = text[section_start:section_start + next_year.start()] if next_year else text[section_start:]
            events.extend(self._parse_fomc_year_section(section, current_year, query))

        if events:
            return events

        # Look for year headers and meeting dates
        # Pattern: "2026" followed by date ranges like "January 27-28" or "March 17-18"
        year_pattern = re.compile(r"<h[23][^>]*>\s*(\d{4})\s*</h[23]>")
        date_pattern = re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?",
            re.IGNORECASE,
        )

        current_year = None
        for line in html.splitlines():
            year_match = year_pattern.search(line)
            if year_match:
                current_year = int(year_match.group(1))
                continue

            if current_year:
                date_match = date_pattern.search(line)
                if date_match:
                    month_name = date_match.group(1)
                    day_start = int(date_match.group(2))
                    month_num = datetime.strptime(month_name, "%B").month
                    # Use the last day of the meeting (end date if range, else start)
                    day_end = int(date_match.group(3)) if date_match.group(3) else day_start

                    # FOMC announcements typically at 2:00 PM ET (18:00 UTC)
                    scheduled = datetime(current_year, month_num, day_end, 18, 0, 0, tzinfo=timezone.utc)

                    # Filter
                    if query.start_at and scheduled < query.start_at:
                        continue
                    if query.end_at and scheduled > query.end_at:
                        continue

                    has_sep = "SEP" in line.upper() or "summary of economic projections" in line.lower()

                    events.append(MarketEventUpsertInput(
                        source_code="FED",
                        title=f"FOMC Meeting {month_name} {current_year}",
                        summary="FOMC Rate Decision" + (" with SEP" if has_sep else ""),
                        category="FED",
                        event_type="FOMC_RATE_DECISION",
                        importance="CRITICAL",
                        country="US",
                        market="US",
                        scheduled_at=scheduled,
                        scheduled_timezone="America/New_York",
                        is_confirmed_time=False,
                        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    ))

                    if has_sep:
                        events.append(MarketEventUpsertInput(
                            source_code="FED",
                            title=f"FOMC SEP {month_name} {current_year}",
                            summary="Summary of Economic Projections",
                            category="FED",
                            event_type="FOMC_SEP",
                            importance="HIGH",
                            country="US",
                            market="US",
                            scheduled_at=scheduled,
                            scheduled_timezone="America/New_York",
                            is_confirmed_time=False,
                        ))

        return events

    def _parse_fomc_year_section(
        self,
        section: str,
        current_year: int,
        query: ProviderCalendarQuery,
    ) -> list[MarketEventUpsertInput]:
        events: list[MarketEventUpsertInput] = []
        date_pattern = re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?P<sep>\*)?",
            re.IGNORECASE,
        )
        for match in date_pattern.finditer(section):
            if section[match.end():match.end() + 2].startswith(","):
                continue
            month_name = match.group(1)
            month_num = datetime.strptime(month_name, "%B").month
            day_end = int(match.group(3)) if match.group(3) else int(match.group(2))
            scheduled = datetime(current_year, month_num, day_end, 18, 0, 0, tzinfo=timezone.utc)
            if query.start_at and scheduled < query.start_at:
                continue
            if query.end_at and scheduled > query.end_at:
                continue

            following = section[match.end():match.end() + 120].lower()
            has_sep = bool(match.group("sep")) or "summary of economic projections" in following
            events.append(MarketEventUpsertInput(
                source_code="FED",
                title=f"FOMC Meeting {month_name} {current_year}",
                summary="FOMC Rate Decision" + (" with SEP" if has_sep else ""),
                category="FED",
                event_type="FOMC_RATE_DECISION",
                importance="CRITICAL",
                country="US",
                market="US",
                scheduled_at=scheduled,
                scheduled_timezone="America/New_York",
                is_confirmed_time=False,
                source_url=self.FOMC_CALENDAR_URL,
            ))
            if has_sep:
                events.append(MarketEventUpsertInput(
                    source_code="FED",
                    title=f"FOMC SEP {month_name} {current_year}",
                    summary="Summary of Economic Projections",
                    category="FED",
                    event_type="FOMC_SEP",
                    importance="HIGH",
                    country="US",
                    market="US",
                    scheduled_at=scheduled,
                    scheduled_timezone="America/New_York",
                    is_confirmed_time=False,
                    source_url=self.FOMC_CALENDAR_URL,
                ))
        return events


# ---------------------------------------------------------------------------
# Enhanced Longbridge Provider
# ---------------------------------------------------------------------------


class RealLongbridgeProvider(LongbridgeProvider):
    """Longbridge provider using Longbridge OpenAPI / SDK only."""

    def __init__(
        self,
        repo: MarketEventRepository,
        cred_store: MarketEventCredentialStore,
        client: LongbridgeExternalDataClient | None = None,
    ) -> None:
        super().__init__(repo, cred_store)
        settings = get_settings()
        self._client = client or LongbridgeExternalDataClient(settings, LongbridgeOpenAPIOAuthService(settings))

    async def health_check(self) -> ProviderHealthCheckResult:
        if not self._is_enabled():
            return self._health_result("SKIPPED", "Source is disabled")
        health = self._client.health()
        if health.get("enabled"):
            return self._health_result("SUCCESS", "Longbridge OpenAPI / SDK is connected")
        return self._health_result("SKIPPED", str(health.get("message") or "Longbridge OpenAPI / SDK is not available"))

    async def fetch_calendar_events(self, query: ProviderCalendarQuery) -> ProviderFetchResult:
        corporate = await self.fetch_corporate_events(ProviderCorporateQuery(
            symbols=query.symbols,
            start_at=query.start_at,
            end_at=query.end_at,
            market=query.market,
            include_raw=query.include_raw,
        ))
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status=corporate.status,
            events=corporate.events,
            values=corporate.values,
            news_links=corporate.news_links,
            total_count=corporate.total_count,
            error_message=corporate.error_message,
            metadata=corporate.metadata,
        )

    async def fetch_news_events(self, query: ProviderNewsQuery) -> ProviderFetchResult:
        try:
            self._client._ensure_available()
            events: list[MarketEventUpsertInput] = []
            links: list[MarketEventNewsLinkInput] = []
            seen: set[str] = set()

            for symbol in query.symbols or []:
                response = self._client.get_news(symbol, min(max(query.limit, 1), 50))
                for item in response.items:
                    event, link = self._map_news_item(item.model_dump(), symbols=[response.symbol], query=query)
                    if event and (event.source_event_id or event.title) not in seen:
                        seen.add(event.source_event_id or event.title)
                        events.append(event)
                        links.append(link)

            if not events and (query.keyword or not query.symbols):
                return self._skipped_result("Longbridge OpenAPI SDK supports news(symbol) only; keyword news is unsupported")

            events = events[:query.limit]
            links = links[:len(events)]
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="SUCCESS",
                events=events,
                news_links=links,
                total_count=len(events),
            )
        except LongbridgeUnavailableError as exc:
            return self._skipped_result(self._safe_error(exc))
        except (LongbridgeExternalDataError, ValueError) as exc:
            return self._failed_result(self._safe_error(exc))

    async def fetch_corporate_events(self, query: ProviderCorporateQuery) -> ProviderFetchResult:
        try:
            start, end = self._range_dates(query.start_at, query.end_at, days=90)
            payload = self._client.get_finance_calendar(
                start=start,
                end=end,
                market=query.market,
                symbols=query.symbols,
            )
            events: list[MarketEventUpsertInput] = []
            values: list[MarketEventValueInput] = []

            for item in self._items(payload, "earnings", "reports", "financial_reports", "calendar"):
                event, event_values = self._map_earnings(item, query)
                if event:
                    events.append(event)
                    values.extend(event_values)
            for item in self._items(payload, "dividends", "dividend"):
                event = self._map_dividend(item, query)
                if event:
                    events.append(event)
            for item in self._items(payload, "splits", "split", "corporate_actions"):
                event = self._map_split(item, query)
                if event:
                    events.append(event)
            for item in self._items(payload, "ipos", "ipo"):
                event = self._map_ipo(item, query)
                if event:
                    events.append(event)

            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="SUCCESS",
                events=events,
                values=values,
                total_count=len(events),
            )
        except LongbridgeUnavailableError as exc:
            return self._skipped_result(self._safe_error(exc))
        except (LongbridgeExternalDataError, ValueError) as exc:
            return self._failed_result(self._safe_error(exc))

    async def fetch_market_holidays(self, query: ProviderMarketHolidayQuery) -> ProviderFetchResult:
        try:
            start, end = self._range_dates(query.start_at, query.end_at, days=365)
            markets = [query.market] if query.market else ["US", "HK", "CN"]
            events: list[MarketEventUpsertInput] = []
            for market in markets:
                payload = self._client.get_trading_days(market=market, start=start, end=end)
                for item in self._items(payload, "closed_days", "holidays", "market_closed"):
                    event = self._map_market_holiday(item, market, "MARKET_CLOSED", "HIGH", query)
                    if event:
                        events.append(event)
                for item in self._items(payload, "half_days", "half_trading_days"):
                    event = self._map_market_holiday(item, market, "HALF_TRADING_DAY", "MEDIUM", query)
                    if event:
                        events.append(event)
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="SUCCESS",
                events=events,
                total_count=len(events),
            )
        except LongbridgeUnavailableError as exc:
            return self._skipped_result(self._safe_error(exc))
        except (LongbridgeExternalDataError, ValueError) as exc:
            return self._failed_result(self._safe_error(exc))

    async def fetch_market_status(self, query: ProviderMarketStatusQuery) -> ProviderFetchResult:
        try:
            payload = self._client.get_market_status(query.markets)
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="SUCCESS",
                total_count=0,
                metadata={"market_status": self._redact_payload(payload)},
            )
        except LongbridgeUnavailableError as exc:
            return self._skipped_result(self._safe_error(exc))
        except (LongbridgeExternalDataError, ValueError) as exc:
            return self._failed_result(self._safe_error(exc))

    async def fetch_trading_sessions(self, query: Any) -> ProviderFetchResult:
        try:
            markets = getattr(query, "markets", None)
            payload = self._client.get_trading_sessions(markets)
            return ProviderFetchResult(
                source_code=self.source_code,
                provider_name=self.provider_name,
                status="SUCCESS",
                total_count=0,
                metadata={"trading_sessions": self._redact_payload(payload)},
            )
        except LongbridgeUnavailableError as exc:
            return self._skipped_result(self._safe_error(exc))
        except (LongbridgeExternalDataError, ValueError) as exc:
            return self._failed_result(self._safe_error(exc))

    def _failed_result(self, message: str) -> ProviderFetchResult:
        return ProviderFetchResult(
            source_code=self.source_code,
            provider_name=self.provider_name,
            status="FAILED",
            error_message=message,
        )

    def _range_dates(self, start_at: datetime | None, end_at: datetime | None, *, days: int) -> tuple[str, str]:
        start = start_at or utc_now()
        end = end_at or (start + timedelta(days=days))
        return start.date().isoformat(), end.date().isoformat()

    def _items(self, payload: Any, *keys: str) -> list[dict[str, Any]]:
        data = self._jsonish(payload)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        candidates: list[Any] = []
        for key in keys:
            value = data.get(key)
            if value is not None:
                candidates.append(value)
        nested = data.get("data") or data.get("result") or data.get("results")
        if isinstance(nested, dict):
            for key in keys:
                value = nested.get(key)
                if value is not None:
                    candidates.append(value)
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("items") or candidate.get("list") or candidate.get("data") or [candidate]
            if isinstance(candidate, list):
                items.extend(item for item in candidate if isinstance(item, dict))
        return items

    def _map_earnings(
        self,
        item: dict[str, Any],
        query: ProviderCorporateQuery,
    ) -> tuple[MarketEventUpsertInput | None, list[MarketEventValueInput]]:
        scheduled_at = self._first_datetime(item, "scheduled_at", "report_date", "date", "earnings_date", "release_date")
        if not scheduled_at or not self._in_range(scheduled_at, query.start_at, query.end_at):
            return None, []
        symbol = self._symbol(item)
        market = self._market(item, symbol, query.market)
        if not self._corporate_allowed("EARNINGS", symbol, market, query):
            return None, []
        title = str(item.get("title") or item.get("name") or item.get("company_name") or f"{symbol or market or 'Longbridge'} Earnings")
        event = MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, "earnings", symbol, scheduled_at),
            title=title,
            summary=str(item.get("summary") or item.get("description") or ""),
            category="COMPANY",
            event_type="EARNINGS",
            importance="HIGH",
            country=self._country(market),
            market=market,
            symbols=[symbol] if symbol else [],
            asset_classes=["EQUITY"],
            scheduled_at=scheduled_at,
            scheduled_timezone=str(item.get("scheduled_timezone") or item.get("timezone") or "UTC"),
            period=str(item.get("period") or item.get("fiscal_period") or ""),
            source_url=str(item.get("source_url") or item.get("url") or ""),
            raw_payload=self._redact_payload(item),
        )
        values = []
        for field, label in (("estimate_eps", "estimate_eps"), ("eps_estimate", "estimate_eps"), ("estimate_revenue", "estimate_revenue"), ("revenue_estimate", "estimate_revenue")):
            value = item.get(field)
            if value not in (None, ""):
                values.append(MarketEventValueInput(
                    occurrence_id="",
                    value_type="FORECAST",
                    label=label,
                    value_text=str(value),
                    value_numeric=self._float_or_none(value),
                    currency=str(item.get("currency") or "") or None,
                    period=event.period,
                    source_code="LONGBRIDGE",
                    raw_payload={"field": field},
                ))
        return event, values

    def _map_dividend(self, item: dict[str, Any], query: ProviderCorporateQuery) -> MarketEventUpsertInput | None:
        scheduled_at = self._first_datetime(item, "ex_date", "scheduled_at", "date", "payment_date")
        if not scheduled_at or not self._in_range(scheduled_at, query.start_at, query.end_at):
            return None
        symbol = self._symbol(item)
        market = self._market(item, symbol, query.market)
        if not self._corporate_allowed("DIVIDEND", symbol, market, query):
            return None
        amount = item.get("dividend_amount") or item.get("amount") or item.get("cash_amount")
        currency = item.get("currency") or item.get("currency_code")
        return MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, "dividend", symbol, scheduled_at),
            title=f"{symbol or market or 'Longbridge'} Dividend",
            summary=f"Dividend {amount or ''} {currency or ''}".strip(),
            category="COMPANY",
            event_type="DIVIDEND",
            importance="MEDIUM",
            country=self._country(market),
            market=market,
            symbols=[symbol] if symbol else [],
            asset_classes=["EQUITY"],
            scheduled_at=scheduled_at,
            scheduled_timezone=str(item.get("scheduled_timezone") or item.get("timezone") or "UTC"),
            source_url=str(item.get("source_url") or item.get("url") or ""),
            raw_payload=self._redact_payload(item),
        )

    def _map_split(self, item: dict[str, Any], query: ProviderCorporateQuery) -> MarketEventUpsertInput | None:
        scheduled_at = self._first_datetime(item, "scheduled_at", "date", "split_date", "effective_date")
        if not scheduled_at or not self._in_range(scheduled_at, query.start_at, query.end_at):
            return None
        symbol = self._symbol(item)
        market = self._market(item, symbol, query.market)
        if not self._corporate_allowed("SPLIT", symbol, market, query):
            return None
        ratio = item.get("split_ratio") or item.get("ratio") or item.get("split")
        return MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, "split", symbol, scheduled_at),
            title=f"{symbol or market or 'Longbridge'} Split",
            summary=f"Split ratio {ratio or 'unknown'}",
            category="COMPANY",
            event_type="SPLIT",
            importance="MEDIUM",
            country=self._country(market),
            market=market,
            symbols=[symbol] if symbol else [],
            asset_classes=["EQUITY"],
            scheduled_at=scheduled_at,
            scheduled_timezone=str(item.get("scheduled_timezone") or item.get("timezone") or "UTC"),
            source_url=str(item.get("source_url") or item.get("url") or ""),
            raw_payload=self._redact_payload(item),
        )

    def _map_ipo(self, item: dict[str, Any], query: ProviderCorporateQuery) -> MarketEventUpsertInput | None:
        scheduled_at = self._first_datetime(item, "listing_date", "scheduled_at", "date")
        if not scheduled_at or not self._in_range(scheduled_at, query.start_at, query.end_at):
            return None
        symbol = self._symbol(item)
        market = self._market(item, symbol, query.market)
        if not self._corporate_allowed("IPO", symbol, market, query):
            return None
        company = str(item.get("company_name") or item.get("name") or symbol or "IPO")
        return MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, "ipo", symbol or company, scheduled_at),
            title=f"{company} IPO",
            summary=str(item.get("summary") or item.get("description") or ""),
            category="COMPANY",
            event_type="IPO",
            importance="MEDIUM",
            country=self._country(market),
            market=market,
            symbols=[symbol] if symbol else [],
            asset_classes=["EQUITY"],
            scheduled_at=scheduled_at,
            scheduled_timezone=str(item.get("scheduled_timezone") or item.get("timezone") or "UTC"),
            source_url=str(item.get("source_url") or item.get("url") or ""),
            raw_payload=self._redact_payload(item),
        )

    def _map_market_holiday(
        self,
        item: dict[str, Any],
        market: str,
        event_type: MarketEventType,
        importance: MarketEventImportance,
        query: ProviderMarketHolidayQuery,
    ) -> MarketEventUpsertInput | None:
        scheduled_at = self._first_datetime(item, "date", "scheduled_at")
        if not scheduled_at or not self._in_range(scheduled_at, query.start_at, query.end_at):
            return None
        title = str(item.get("name") or item.get("title") or event_type.replace("_", " ").title())
        return MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, event_type.lower(), market, scheduled_at),
            title=f"{market.upper()} {title}",
            summary=str(item.get("summary") or item.get("description") or ""),
            category="MARKET",
            event_type=event_type,
            importance=importance,
            market=market.upper(),
            scheduled_at=scheduled_at,
            scheduled_timezone=str(item.get("scheduled_timezone") or item.get("timezone") or "UTC"),
            is_all_day=True,
            raw_payload=self._redact_payload(item),
        )

    def _map_news_item(
        self,
        item: dict[str, Any],
        *,
        symbols: list[str],
        query: ProviderNewsQuery,
        keyword: str | None = None,
    ) -> tuple[MarketEventUpsertInput | None, MarketEventNewsLinkInput]:
        published_at = self._first_datetime(item, "published_at", "time", "timestamp", "released_at", "updated_at") or utc_now()
        if not self._in_range(published_at, query.start_at, query.end_at):
            return None, MarketEventNewsLinkInput()
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or item.get("description") or item.get("excerpt") or "")
        event_type, category, importance = self._classify_news(title, summary, keyword)
        url = str(item.get("url") or item.get("link") or "")
        news_symbols = symbols or [normalize_longbridge_symbol(str(symbol)) for symbol in item.get("symbols", []) if str(symbol).strip()]
        event = MarketEventUpsertInput(
            source_code="LONGBRIDGE",
            source_event_id=self._source_id(item, "news", url or title, published_at),
            title=title,
            summary=summary,
            category=category,
            event_type=event_type,
            importance=importance,
            market=None,
            symbols=news_symbols,
            asset_classes=["EQUITY"] if news_symbols else [],
            scheduled_at=published_at,
            scheduled_timezone="UTC",
            is_confirmed_time=True,
            source_url=url,
            raw_payload=self._redact_payload(item),
        )
        link = MarketEventNewsLinkInput(
            occurrence_id="",
            source_code="LONGBRIDGE",
            news_id=str(item.get("id") or item.get("news_id") or ""),
            title=title,
            url=url,
            publisher=str(item.get("publisher") or item.get("source") or "Longbridge"),
            published_at=published_at,
            summary=summary,
            symbols=news_symbols,
            raw_payload=self._redact_payload(item),
        )
        return event, link

    def _classify_news(
        self,
        title: str,
        summary: str,
        keyword: str | None,
    ) -> tuple[MarketEventType, MarketEventCategory, MarketEventImportance]:
        text = f"{title} {summary} {keyword or ''}".lower()
        if "export control" in text:
            return "EXPORT_CONTROL", "POLICY", "HIGH"
        if "tariff" in text:
            return "TARIFF", "POLICY", "HIGH"
        if "mstr" in text or "microstrategy" in text:
            return "MSTR_BTC_EVENT", "CRYPTO", "HIGH"
        if "bitcoin" in text or "btc" in text:
            return "BTC_EVENT", "CRYPTO", "MEDIUM"
        if any(token in text for token in ("fomc", "cpi", "ppi", "fed rate")):
            return "NEWS", "NEWS", "MEDIUM"
        return "NEWS", "NEWS", "LOW"

    def _source_id(self, item: dict[str, Any], prefix: str, entity: str | None, scheduled_at: datetime) -> str:
        raw = item.get("id") or item.get("event_id") or item.get("news_id")
        if raw:
            return f"{prefix}:{raw}"
        return f"{prefix}:{entity or 'unknown'}:{scheduled_at.isoformat()}"

    def _corporate_allowed(
        self,
        event_type: MarketEventType,
        symbol: str | None,
        market: str | None,
        query: ProviderCorporateQuery,
    ) -> bool:
        if query.event_types and event_type not in query.event_types:
            return False
        if query.market and market and market.upper() != query.market.upper():
            return False
        if query.symbols and symbol:
            wanted = {normalize_longbridge_symbol(item) for item in query.symbols}
            if symbol not in wanted:
                return False
        return True

    def _symbol(self, item: dict[str, Any]) -> str | None:
        raw = item.get("symbol") or item.get("ticker") or item.get("stock_code") or item.get("security_code")
        if not raw:
            return None
        try:
            return normalize_longbridge_symbol(str(raw))
        except ValueError:
            return str(raw).upper()

    def _market(self, item: dict[str, Any], symbol: str | None, fallback: str | None = None) -> str | None:
        raw = item.get("market") or item.get("exchange") or fallback
        if raw:
            return str(raw).upper()
        if symbol and "." in symbol:
            return symbol.rsplit(".", 1)[1].upper()
        return None

    def _country(self, market: str | None) -> str | None:
        return {"US": "US", "HK": "HK", "CN": "CN", "SH": "CN", "SZ": "CN"}.get((market or "").upper())

    def _first_datetime(self, item: dict[str, Any], *fields: str) -> datetime | None:
        for field in fields:
            raw = item.get(field)
            parsed = self._parse_datetime(raw)
            if parsed:
                return parsed
        return None

    def _parse_datetime(self, raw: Any) -> datetime | None:
        if raw in (None, ""):
            return None
        if isinstance(raw, datetime):
            return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        text = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _in_range(self, value: datetime, start_at: datetime | None, end_at: datetime | None) -> bool:
        if start_at and value < (start_at.astimezone(timezone.utc) if start_at.tzinfo else start_at.replace(tzinfo=timezone.utc)):
            return False
        if end_at and value > (end_at.astimezone(timezone.utc) if end_at.tzinfo else end_at.replace(tzinfo=timezone.utc)):
            return False
        return True

    def _float_or_none(self, value: Any) -> float | None:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    def _jsonish(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): self._jsonish(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._jsonish(item) for item in value]
        try:
            return {str(k): self._jsonish(v) for k, v in vars(value).items() if not str(k).startswith("_")}
        except TypeError:
            return str(value)

    def _redact_payload(self, payload: Any) -> dict[str, Any]:
        data = self._jsonish(payload)
        if not isinstance(data, dict):
            return {"value": data}
        sensitive = ("token", "secret", "authorization", "cookie", "app_key", "app_secret", "access_token", "refresh_token")
        return self._redact_dict(data, sensitive)

    def _redact_dict(self, data: dict[str, Any], sensitive: tuple[str, ...]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            if any(term in key.lower() for term in sensitive):
                redacted[key] = "[REDACTED]"
            elif isinstance(value, dict):
                redacted[key] = self._redact_dict(value, sensitive)
            elif isinstance(value, list):
                redacted[key] = [
                    self._redact_dict(item, sensitive) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                redacted[key] = value
        return redacted

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc)
        text = re.sub(r"(?i)(access_token|refresh_token|authorization|app_key|app_secret|token|secret)=([^\s&]+)", r"\1=[REDACTED]", text)
        text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer [REDACTED]", text)
        return text[:240]
