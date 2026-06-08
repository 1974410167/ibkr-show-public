"""Tests for real market event providers with mocked HTTP."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.longbridge import LongbridgeNewsItem, LongbridgeNewsResponse
from app.schemas.market_event import (
    ProviderCalendarQuery,
    ProviderCorporateQuery,
    ProviderMarketHolidayQuery,
    ProviderNewsQuery,
    ProviderValueQuery,
)
from app.services.longbridge_service import LongbridgeUnavailableError
from app.services.market_event_credential import MarketEventCredentialStore
from app.services.market_event_providers import MarketEventProviderRegistry
from app.services.market_event_real_providers import (
    RealBlsProvider,
    RealBeaProvider,
    RealFedProvider,
    RealFredProvider,
    RealLongbridgeProvider,
)

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260610T083000
SUMMARY:Consumer Price Index
DESCRIPTION:CPI Release
URL:https://www.bls.gov/cpi/
END:VEVENT
BEGIN:VEVENT
DTSTART:20260612T083000
SUMMARY:Producer Price Index
DESCRIPTION:PPI Release
URL:https://www.bls.gov/ppi/
END:VEVENT
BEGIN:VEVENT
DTSTART:20260615T083000
SUMMARY:Employment Situation
DESCRIPTION:Jobs Report
URL:https://www.bls.gov/ces/
END:VEVENT
END:VCALENDAR
"""

SAMPLE_FOMC_HTML = """
<h3>2026</h3>
<p>January 27-28</p>
<p>March 17-18 (with SEP)</p>
<p>June 9-10</p>
"""

SAMPLE_BEA_SCHEDULE_HTML = """
<html><body>
<div>June 26, 2026 8:30 A.M. Gross Domestic Product, 1st Quarter 2026 (Third Estimate)</div>
<div>July 31, 2026 8:30 A.M. Personal Income and Outlays, June 2026</div>
<div>August 5, 2026 10:00 A.M. International Trade in Goods and Services</div>
</body></html>
"""

SAMPLE_BEA_CURRENT_SCHEDULE_HTML = """
<html><body>
<h1>Release Schedule</h1>
Year 2026 Release
June 25
8:30 AM
N ews
GDP (Third Estimate), Industries, Corporate Profits, State GDP, and State Personal Income, 1st Quarter 2026
June 25
8:30 AM
N ews
Personal Income and Outlays, May 2026
July 7
8:30 AM
N ews
U.S. International Trade in Goods and Services, May 2026
Additional Formats
</body></html>
"""

SAMPLE_FOMC_CURRENT_HTML = """
<html><body>
<h3>2026 FOMC Meetings</h3>
January 27-28 Statement: PDF | HTML Implementation Note
March 17-18* Statement: PDF | HTML
June 16-17
July 28-29
September 15-16*
* Meeting associated with a Summary of Economic Projections.
<h3>2027 FOMC Meetings</h3>
</body></html>
"""

SAMPLE_FRED_OBSERVATIONS = {
    "observations": [
        {"date": "2026-05-01", "value": "321.465"}
    ]
}


def _make_registry():
    tmpdir = tempfile.mkdtemp()
    cred_file = Path(tmpdir) / "creds.json"
    cred_store = MarketEventCredentialStore(str(cred_file))
    repo = MagicMock()
    repo.get_source.return_value = {
        "source_code": "BLS",
        "enabled": True,
        "requires_api_key": False,
    }
    return repo, cred_store


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# BLS ICS parsing tests
# ---------------------------------------------------------------------------


def test_bls_parse_ics():
    repo, cred_store = _make_registry()
    provider = RealBlsProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_ics(SAMPLE_ICS, query)
    assert len(events) == 3

    types = {e.event_type for e in events}
    assert "CPI" in types
    assert "PPI" in types
    assert "NONFARM_PAYROLLS" in types


def test_bls_parse_ics_filtered():
    repo, cred_store = _make_registry()
    provider = RealBlsProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        event_types=["CPI"],
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_ics(SAMPLE_ICS, query)
    assert len(events) == 1
    assert events[0].event_type == "CPI"


def test_bls_parse_ics_date_filter():
    repo, cred_store = _make_registry()
    provider = RealBlsProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    events = provider._parse_ics(SAMPLE_ICS, query)
    assert len(events) == 1
    assert events[0].event_type == "PPI"


def test_bls_ics_fields():
    repo, cred_store = _make_registry()
    provider = RealBlsProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_ics(SAMPLE_ICS, query)
    cpi = next(e for e in events if e.event_type == "CPI")
    assert cpi.source_code == "BLS"
    assert cpi.category == "MACRO"
    assert cpi.importance == "CRITICAL"
    assert cpi.country == "US"
    assert cpi.scheduled_timezone == "America/New_York"


# ---------------------------------------------------------------------------
# Fed FOMC parsing tests
# ---------------------------------------------------------------------------


def test_fed_parse_fomc_html():
    repo, cred_store = _make_registry()
    provider = RealFedProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_fomc_html(SAMPLE_FOMC_HTML, query)
    assert len(events) >= 3

    # Check that SEP event exists
    sep_events = [e for e in events if e.event_type == "FOMC_SEP"]
    assert len(sep_events) == 1

    # Check that rate decision events exist
    rate_events = [e for e in events if e.event_type == "FOMC_RATE_DECISION"]
    assert len(rate_events) >= 2


def test_fed_fomc_fields():
    repo, cred_store = _make_registry()
    provider = RealFedProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_fomc_html(SAMPLE_FOMC_HTML, query)
    first = events[0]
    assert first.source_code == "FED"
    assert first.category == "FED"
    assert first.importance == "CRITICAL"
    assert first.is_confirmed_time is False


# ---------------------------------------------------------------------------
# BEA release schedule parsing tests
# ---------------------------------------------------------------------------


def test_bea_parse_release_schedule():
    repo, cred_store = _make_registry()
    provider = RealBeaProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_release_schedule(SAMPLE_BEA_SCHEDULE_HTML, query)
    assert len(events) == 2
    types = {event.event_type for event in events}
    assert "GDP" in types
    assert "PCE" in types


def test_bea_parse_current_release_schedule_format():
    repo, cred_store = _make_registry()
    provider = RealBeaProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    events = provider._parse_release_schedule(SAMPLE_BEA_CURRENT_SCHEDULE_HTML, query)
    assert len(events) == 2
    assert {event.event_type for event in events} == {"GDP", "PCE"}
    assert all(event.scheduled_at.year == 2026 for event in events)


def test_bea_release_schedule_fields():
    repo, cred_store = _make_registry()
    provider = RealBeaProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    events = provider._parse_release_schedule(SAMPLE_BEA_SCHEDULE_HTML, query)
    assert len(events) == 1
    event = events[0]
    assert event.source_code == "BEA"
    assert event.category == "MACRO"
    assert event.event_type == "GDP"
    assert event.scheduled_timezone == "America/New_York"
    assert event.is_confirmed_time is True


def test_fed_parse_current_fomc_html():
    repo, cred_store = _make_registry()
    provider = RealFedProvider(repo, cred_store)
    query = ProviderCalendarQuery(
        start_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    events = provider._parse_fomc_html(SAMPLE_FOMC_CURRENT_HTML, query)
    event_types = [event.event_type for event in events]
    assert event_types.count("FOMC_RATE_DECISION") == 3
    assert "FOMC_SEP" in event_types


class _FakeHttpResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fred_health_and_latest_values(monkeypatch):
    repo, cred_store = _make_registry()
    repo.get_source.return_value = {
        "source_code": "FRED",
        "enabled": True,
        "requires_api_key": True,
        "credential_key_name": "FRED_API_KEY",
    }
    monkeypatch.setattr(cred_store, "get_decrypted_value", lambda source_code, credential_key: "test-fred-key")
    provider = RealFredProvider(repo, cred_store)

    from app.services import market_event_real_providers
    monkeypatch.setattr(
        market_event_real_providers,
        "_safe_http_get",
        lambda *args, **kwargs: _FakeHttpResponse(SAMPLE_FRED_OBSERVATIONS),
    )

    health = _run(provider.health_check())
    values = _run(provider.fetch_event_values(ProviderValueQuery(series_id="CPIAUCSL")))

    assert health.status == "SUCCESS"
    assert values.status == "SUCCESS"
    assert values.total_count == 1
    assert values.values[0].source_code == "FRED"
    assert values.values[0].value_numeric == 321.465


# ---------------------------------------------------------------------------
# Longbridge provider tests
# ---------------------------------------------------------------------------


def test_longbridge_health_check():
    repo, cred_store = _make_registry()
    repo.get_source.return_value = {"enabled": True}
    provider = RealLongbridgeProvider(repo, cred_store, _FakeLongbridgeClient())
    result = _run(provider.health_check())
    assert result.status == "SUCCESS"


def test_longbridge_corporate_returns_skipped():
    repo, cred_store = _make_registry()
    provider = RealLongbridgeProvider(repo, cred_store, _MissingLongbridgeClient())
    result = _run(provider.fetch_corporate_events(ProviderCorporateQuery()))
    assert result.status == "SKIPPED"
    assert "authorization" in (result.error_message or "").lower()


class _FakeLongbridgeClient:
    def health(self):
        return {"enabled": True, "message": "ok"}

    def _ensure_available(self):
        return None

    def get_finance_calendar(self, *, start, end, market=None, symbols=None):
        return {
            "earnings": [{
                "id": "earn-1",
                "symbol": "AMD.US",
                "company_name": "AMD",
                "report_date": "2026-07-28",
                "period": "2026Q2",
                "market_time": "after",
                "estimate_eps": "1.20",
                "estimate_revenue": "7000000000",
                "currency": "USD",
                "url": "https://longbridge.example/earnings/amd",
            }],
            "dividends": [{
                "id": "div-1",
                "symbol": "MSFT.US",
                "ex_date": "2026-08-15",
                "record_date": "2026-08-16",
                "payment_date": "2026-09-01",
                "dividend_amount": "0.83",
                "currency": "USD",
            }],
            "splits": [{
                "id": "split-1",
                "symbol": "NVDA.US",
                "split_date": "2026-09-10",
                "split_ratio": "10:1",
            }],
            "ipos": [{
                "id": "ipo-1",
                "symbol": "NEW.US",
                "company_name": "New Co",
                "market": "US",
                "listing_date": "2026-10-02",
            }],
        }

    def get_trading_days(self, *, market, start, end):
        return {
            "closed_days": [{"date": "2026-07-04", "name": "Independence Day"}],
            "half_days": [{"date": "2026-11-27", "name": "Thanksgiving half day"}],
        }

    def get_news(self, symbol, limit):
        return LongbridgeNewsResponse(
            symbol="AMD.US",
            items=[
                LongbridgeNewsItem(
                    title="AMD earnings preview",
                    summary="Analysts discuss upcoming report.",
                    url="https://news.example/amd",
                    published_at="2026-07-20T10:00:00+00:00",
                )
            ],
        )

    def get_market_status(self, markets=None):
        return {"markets": [{"market": "US", "status": "OPEN", "authorization": "Bearer token-secret"}]}

    def get_trading_sessions(self, markets=None):
        return {"sessions": [{"market": "US", "session": "regular"}]}


class _EmptyLongbridgeClient(_FakeLongbridgeClient):
    def get_finance_calendar(self, *, start, end, market=None, symbols=None):
        return {"earnings": [], "dividends": [], "splits": [], "ipos": []}


class _MissingLongbridgeClient(_FakeLongbridgeClient):
    def health(self):
        return {"enabled": False, "message": "Longbridge OpenAPI OAuth authorization is required"}

    def _ensure_available(self):
        raise LongbridgeUnavailableError("Longbridge OpenAPI OAuth authorization is required; access_token=secret-token")

    def get_finance_calendar(self, *, start, end, market=None, symbols=None):
        self._ensure_available()


def _longbridge_provider(client=None):
    repo, cred_store = _make_registry()
    repo.get_source.return_value = {"enabled": True}
    return RealLongbridgeProvider(repo, cred_store, client or _FakeLongbridgeClient())


def test_longbridge_finance_calendar_maps_earnings_and_forecast_values():
    provider = _longbridge_provider()
    result = _run(provider.fetch_corporate_events(ProviderCorporateQuery()))
    earnings = next(event for event in result.events if event.event_type == "EARNINGS")
    assert result.status == "SUCCESS"
    assert earnings.source_code == "LONGBRIDGE"
    assert earnings.category == "COMPANY"
    assert earnings.importance == "HIGH"
    assert earnings.symbols == ["AMD.US"]
    assert {value.label for value in result.values} >= {"estimate_eps", "estimate_revenue"}


def test_longbridge_finance_calendar_maps_dividend_split_ipo():
    provider = _longbridge_provider()
    result = _run(provider.fetch_corporate_events(ProviderCorporateQuery()))
    event_types = {event.event_type for event in result.events}
    assert "DIVIDEND" in event_types
    assert "SPLIT" in event_types
    assert "IPO" in event_types


def test_longbridge_trading_days_map_closed_and_half_day():
    provider = _longbridge_provider()
    result = _run(provider.fetch_market_holidays(ProviderMarketHolidayQuery(market="US")))
    by_type = {event.event_type: event for event in result.events}
    assert by_type["MARKET_CLOSED"].importance == "HIGH"
    assert by_type["MARKET_CLOSED"].is_all_day is True
    assert by_type["HALF_TRADING_DAY"].importance == "MEDIUM"


def test_longbridge_symbol_news_maps_news_and_link():
    provider = _longbridge_provider()
    result = _run(provider.fetch_news_events(ProviderNewsQuery(symbols=["AMD.US"], limit=1)))
    assert result.status == "SUCCESS"
    assert result.events[0].event_type == "NEWS"
    assert result.news_links[0].url == "https://news.example/amd"


def test_longbridge_keyword_only_news_is_skipped():
    provider = _longbridge_provider()
    result = _run(provider.fetch_news_events(ProviderNewsQuery(keyword="tariffs", limit=1)))
    assert result.status == "SKIPPED"
    assert result.total_count == 0
    assert "news(symbol) only" in (result.error_message or "")


def test_longbridge_empty_result_is_success_zero():
    provider = _longbridge_provider(_EmptyLongbridgeClient())
    result = _run(provider.fetch_corporate_events(ProviderCorporateQuery()))
    assert result.status == "SUCCESS"
    assert result.total_count == 0


def test_longbridge_missing_auth_is_skipped_and_redacts_token():
    provider = _longbridge_provider(_MissingLongbridgeClient())
    result = _run(provider.fetch_corporate_events(ProviderCorporateQuery()))
    assert result.status == "SKIPPED"
    assert "secret-token" not in (result.error_message or "")
    assert "access_token=[REDACTED]" in (result.error_message or "")


def test_longbridge_market_status_metadata_redacts_token():
    from app.schemas.market_event import ProviderMarketStatusQuery
    provider = _longbridge_provider()
    result = _run(provider.fetch_market_status(ProviderMarketStatusQuery(markets=["US"])))
    assert result.status == "SUCCESS"
    assert "token-secret" not in str(result.model_dump())
