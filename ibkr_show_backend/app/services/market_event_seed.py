"""Default seed data for market event sources."""

from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_SOURCES: list[dict] = [
    {
        "source_code": "BLS",
        "source_name": "Bureau of Labor Statistics",
        "description": "CPI, PPI, nonfarm payrolls, unemployment rate, JOLTS -- US labor and inflation data.",
        "enabled": True,
        "priority": 10,
        "requires_api_key": True,
        "credential_key_name": "BLS_API_KEY",
        "apply_url": "https://data.bls.gov/registrationEngine/",
        "doc_url": "https://www.bls.gov/developers/api_faqs.htm",
        "base_url": "https://api.bls.gov/publicAPI/v2",
        "health_check_url": "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0?latest=true",
    },
    {
        "source_code": "BEA",
        "source_name": "Bureau of Economic Analysis",
        "description": "GDP, PCE, Personal Income and Outlays -- US economic data.",
        "enabled": True,
        "priority": 20,
        "requires_api_key": True,
        "credential_key_name": "BEA_API_KEY",
        "apply_url": "https://apps.bea.gov/API/signup/",
        "doc_url": "https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf",
        "base_url": "https://apps.bea.gov/api/data",
    },
    {
        "source_code": "FRED",
        "source_name": "Federal Reserve Economic Data",
        "description": "Macroeconomic time-series backup and verification data source.",
        "enabled": True,
        "priority": 30,
        "requires_api_key": True,
        "credential_key_name": "FRED_API_KEY",
        "apply_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
        "doc_url": "https://fred.stlouisfed.org/docs/api/fred/",
        "base_url": "https://api.stlouisfed.org/fred",
    },
    {
        "source_code": "FED",
        "source_name": "Federal Reserve",
        "description": "FOMC, SEP, meeting minutes, rate decisions, Fed public materials.",
        "enabled": True,
        "priority": 40,
        "requires_api_key": False,
        "credential_key_name": None,
        "apply_url": None,
        "doc_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "base_url": "https://www.federalreserve.gov",
    },
    {
        "source_code": "ISM",
        "source_name": "Institute for Supply Management",
        "description": "ISM Manufacturing PMI, ISM Services PMI release schedule and data.",
        "enabled": True,
        "priority": 50,
        "requires_api_key": False,
        "credential_key_name": None,
        "apply_url": None,
        "doc_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/",
        "base_url": "https://www.ismworld.org",
    },
    {
        "source_code": "LONGBRIDGE",
        "source_name": "Longbridge",
        "description": "Earnings, dividends, splits, IPOs, market holidays, trading sessions, position-related news.",
        "enabled": True,
        "priority": 60,
        "requires_api_key": False,
        "credential_key_name": None,
        "apply_url": None,
        "doc_url": "https://open.longportapp.com/",
        "base_url": "https://openapi.longportapp.com",
    },
    {
        "source_code": "MANUAL",
        "source_name": "Manual",
        "description": "Manually maintained event source from the admin console.",
        "enabled": True,
        "priority": 100,
        "requires_api_key": False,
        "credential_key_name": None,
        "apply_url": None,
        "doc_url": None,
        "base_url": None,
    },
]


def get_seed_sources() -> list[dict]:
    """Return seed source documents with timestamps."""
    now = datetime.now(timezone.utc).isoformat()
    result = []
    for src in DEFAULT_SOURCES:
        doc = dict(src)
        doc["created_at"] = now
        doc["updated_at"] = now
        result.append(doc)
    return result
