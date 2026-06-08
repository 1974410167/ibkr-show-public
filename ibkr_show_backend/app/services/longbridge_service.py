from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
import json
import subprocess
import threading
from typing import Any
from urllib.parse import urlencode

from app.core.config import Settings
from app.schemas.longbridge import LongbridgeCandleItem, LongbridgeCandlesResponse, LongbridgeMacroNewsResponse, LongbridgeNewsItem, LongbridgeNewsResponse
from app.services.longbridge_openapi_oauth import LongbridgeOpenAPIOAuthService

SUPPORTED_LONGBRIDGE_PERIODS = {"day", "week", "month"}
SUPPORTED_LONGBRIDGE_ADJUST_TYPES = {"forward", "backward", "none"}


class LongbridgeUnavailableError(RuntimeError):
    """Raised when the Longbridge external data source is disabled or not configured."""


class LongbridgeExternalDataError(RuntimeError):
    """Raised when Longbridge returns an API or SDK error."""


@dataclass(frozen=True)
class LongbridgeSdkBindings:
    Config: type
    HttpClient: type
    OAuthBuilder: type
    QuoteContext: type
    ContentContext: type
    CalendarContext: type | None
    MarketContext: type | None
    module: Any


def normalize_longbridge_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol is required")
    if "." in normalized:
        return normalized
    return f"{normalized}.US"


def _load_longbridge_sdk() -> LongbridgeSdkBindings | None:
    try:
        from longbridge.openapi import Config, ContentContext, HttpClient, OAuthBuilder, QuoteContext
        import longbridge.openapi as openapi

        CalendarContext = getattr(openapi, "CalendarContext", None)
        MarketContext = getattr(openapi, "MarketContext", None)

        return LongbridgeSdkBindings(
            Config=Config,
            HttpClient=HttpClient,
            OAuthBuilder=OAuthBuilder,
            QuoteContext=QuoteContext,
            ContentContext=ContentContext,
            CalendarContext=CalendarContext,
            MarketContext=MarketContext,
            module=import_module("longbridge.openapi"),
        )
    except ImportError:
        return None


def _parse_api_date(raw_value: str, field_name: str) -> date:
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _to_iso_datetime(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if int(value.timestamp()) == 0:
            return ""
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        iso = value.isoformat()
        return "" if iso == "1970-01-01" else iso
    if isinstance(value, (int, float)):
        if value <= 0:
            return ""
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    raw_value = str(value).strip()
    if raw_value in {"", "0", "1970-01-01", "1970-01-01T00:00:00", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00+00:00"}:
        return ""
    if raw_value.isdigit():
        if int(raw_value) <= 0:
            return ""
        return datetime.fromtimestamp(int(raw_value), tz=timezone.utc).isoformat()
    if raw_value.startswith("1970-01-01"):
        return ""
    return raw_value


def _to_candle_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    raw_value = str(value)
    if raw_value.isdigit():
        if len(raw_value) == 8:
            return datetime.strptime(raw_value, "%Y%m%d").date().isoformat()
        return datetime.fromtimestamp(int(raw_value), tz=timezone.utc).date().isoformat()
    return raw_value[:10]


def _get_attr(item: Any, *names: str) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
        return None
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _to_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_json_value(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_value(item, depth=depth + 1) for item in value]
    try:
        raw_vars = vars(value)
    except Exception:
        raw_vars = None
    if isinstance(raw_vars, dict) and raw_vars:
        return {
            str(key): _to_json_value(item, depth=depth + 1)
            for key, item in raw_vars.items()
            if not str(key).startswith("_")
        }
    if value.__class__.__module__ == "builtins":
        text_value = str(value)
        if text_value.startswith(f"{value.__class__.__name__}."):
            return text_value

    data: dict[str, Any] = {}
    try:
        attribute_names = dir(value)
    except Exception:
        attribute_names = []
    for name in attribute_names:
        if name.startswith("_"):
            continue
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if callable(item):
            continue
        if isinstance(item, type):
            continue
        data[name] = _to_json_value(item, depth=depth + 1)
    return data or str(value)


def _format_longbridge_error(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    code = getattr(exc, "code", None)
    if code is not None:
        return f"Longbridge error {code}: {message}"
    return f"Longbridge error: {message}"


class LongbridgeExternalDataClient:
    def __init__(self, settings: Settings, oauth_service: LongbridgeOpenAPIOAuthService | None = None) -> None:
        self.settings = settings
        self.oauth_service = oauth_service or LongbridgeOpenAPIOAuthService(settings)
        self._sdk = _load_longbridge_sdk()
        self._oauth: Any | None = None
        self._config: Any | None = None
        self._http_client: Any | None = None
        self._quote_context: Any | None = None
        self._content_context: Any | None = None
        self._calendar_context: Any | None = None
        self._market_context: Any | None = None
        self._fetch_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.longbridge_enable

    @property
    def configured(self) -> bool:
        return bool(self._oauth_client_id())

    @property
    def oauth_connected(self) -> bool:
        return bool(self.oauth_service.status().get("oauth_connected"))

    @property
    def sdk_loaded(self) -> bool:
        return self._sdk is not None

    def health(self) -> dict:
        oauth_status = self.oauth_service.status()
        if not self.sdk_loaded:
            return {
                "enabled": False,
                "configured": self.configured,
                "sdk_loaded": False,
                "oauth_connected": bool(oauth_status.get("oauth_connected")),
                "message": "Longbridge SDK is not installed",
            }
        if not self.enabled:
            return {
                "enabled": False,
                "configured": self.configured,
                "sdk_loaded": True,
                "oauth_connected": bool(oauth_status.get("oauth_connected")),
                "message": "Longbridge client is disabled",
            }
        if not self.configured:
            return {
                "enabled": False,
                "configured": False,
                "sdk_loaded": True,
                "oauth_connected": False,
                "message": "Longbridge OpenAPI OAuth client_id is not configured",
            }
        if not oauth_status.get("oauth_connected"):
            return {
                "enabled": False,
                "configured": True,
                "sdk_loaded": True,
                "oauth_connected": False,
                "message": "Longbridge OpenAPI OAuth is not connected",
            }
        return {
            "enabled": True,
            "configured": True,
            "sdk_loaded": True,
            "oauth_connected": True,
            "message": "Longbridge OpenAPI OAuth is connected",
        }

    def get_candles(self, symbol: str, start: str, end: str, period: str, adjust_type: str) -> LongbridgeCandlesResponse:
        normalized_symbol = normalize_longbridge_symbol(symbol)
        start_date, end_date = self._validate_date_range(start, end)
        normalized_period = period.strip().lower()
        if normalized_period not in SUPPORTED_LONGBRIDGE_PERIODS:
            raise ValueError("period must be one of: day, week, month")

        candles = self._fetch_candles(
            symbol=normalized_symbol,
            start=start_date,
            end=end_date,
            period=normalized_period,
            adjust_type=adjust_type.strip().lower(),
        )
        return LongbridgeCandlesResponse(
            symbol=normalized_symbol,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            period=normalized_period,
            items=candles,
        )

    def get_benchmark_candles(self, symbols: str, start: str, end: str, period: str) -> dict[str, list[LongbridgeCandleItem]]:
        symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]
        if not symbol_list:
            raise ValueError("symbols must contain at least one symbol")

        results: dict[str, list[LongbridgeCandleItem]] = {}
        with ThreadPoolExecutor(max_workers=len(symbol_list)) as executor:
            futures = {
                executor.submit(self.get_candles, symbol=symbol, start=start, end=end, period=period, adjust_type="forward"): symbol
                for symbol in symbol_list
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    response = future.result()
                    results[response.symbol] = response.items
                except Exception:
                    results[symbol] = []
        return results

    def get_news(self, symbol: str, limit: int) -> LongbridgeNewsResponse:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            raw_items = self._get_content_context().news(normalized_symbol)
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge news: {_format_longbridge_error(exc)}") from exc

        items = [self._normalize_news_item(item) for item in list(raw_items)[:limit]]
        return LongbridgeNewsResponse(symbol=normalized_symbol, items=items)

    def search_macro_news(self, keyword: str = "macro economy", limit: int = 20) -> LongbridgeMacroNewsResponse:
        normalized_keyword = keyword.strip() or "macro economy"
        normalized_limit = max(1, min(int(limit), 50))
        if not self.enabled:
            raise LongbridgeUnavailableError("Longbridge external data source is disabled")
        try:
            completed = subprocess.run(
                [
                    "longbridge",
                    "news",
                    "search",
                    normalized_keyword,
                    "--count",
                    str(normalized_limit),
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError as exc:
            raise LongbridgeUnavailableError("Longbridge CLI is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise LongbridgeExternalDataError("Longbridge macro news search timed out") from exc
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "").strip()
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge macro news: {message or exc}") from exc

        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise LongbridgeExternalDataError("Longbridge macro news response is not valid JSON") from exc
        raw_items = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        items = [self._normalize_news_item(item) for item in raw_items[:normalized_limit]]
        return LongbridgeMacroNewsResponse(keyword=normalized_keyword, items=items)

    def get_quote_snapshot(self, symbol: str) -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            items = self._get_quote_context().quote([normalized_symbol])
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge quote: {_format_longbridge_error(exc)}") from exc
        return self._first_serialized_item(items, normalized_symbol)

    def get_static_info(self, symbol: str) -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            items = self._get_quote_context().static_info([normalized_symbol])
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge static info: {_format_longbridge_error(exc)}") from exc
        return self._first_serialized_item(items, normalized_symbol)

    def get_calc_indexes(self, symbol: str) -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            items = self._get_quote_context().calc_indexes([normalized_symbol], self._resolve_calc_indexes())
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge calc indexes: {_format_longbridge_error(exc)}") from exc
        return self._first_serialized_item(items, normalized_symbol)

    def get_filings(self, symbol: str, limit: int = 10) -> list[dict]:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            items = self._get_quote_context().filings(normalized_symbol)
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge filings: {_format_longbridge_error(exc)}") from exc
        return [_to_json_value(item) for item in list(items)[:limit]]

    def get_topics(self, symbol: str, limit: int = 10) -> list[dict]:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        try:
            items = self._get_content_context().topics(normalized_symbol)
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge topics: {_format_longbridge_error(exc)}") from exc
        return [_to_json_value(item) for item in list(items)[:limit]]

    def get_financial_statement(self, symbol: str, kind: str, report: str = "qf") -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        kind_upper = kind.strip().upper()
        report_lower = report.strip().lower()
        if kind_upper not in {"IS", "BS", "CF", "ALL"}:
            raise ValueError("kind must be one of: IS, BS, CF, ALL")
        if report_lower not in {"af", "saf", "qf", "cumul"}:
            raise ValueError("report must be one of: af, saf, qf, cumul")

        query = urlencode(
            {
                "counter_id": self._symbol_to_counter_id(normalized_symbol),
                "kind": kind_upper,
                "report": report_lower,
            }
        )
        try:
            payload = self._get_http_client().request("get", f"/v1/quote/financials/statements?{query}")
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge financial statement: {_format_longbridge_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise LongbridgeExternalDataError("Longbridge financial statement response is not an object")
        return payload

    def get_financial_report(self, symbol: str, kind: str = "ALL", report: str = "qf") -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        kind_upper = kind.strip().upper()
        report_lower = report.strip().lower()
        if kind_upper not in {"IS", "BS", "CF", "ALL"}:
            raise ValueError("kind must be one of: IS, BS, CF, ALL")
        if report_lower not in {"af", "saf", "q1", "3q", "qf", "q2", "q3", "q4"}:
            raise ValueError("report must be one of: af, saf, q1, 3q, qf, q2, q3, q4")

        query = urlencode(
            {
                "counter_id": self._symbol_to_counter_id(normalized_symbol),
                "kind": kind_upper,
                "report": report_lower,
            }
        )
        try:
            payload = self._get_http_client().request("get", f"/v1/quote/financial-reports?{query}")
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge financial report: {_format_longbridge_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise LongbridgeExternalDataError("Longbridge financial report response is not an object")
        return payload

    def get_valuation_detail(self, symbol: str) -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        query = urlencode({"counter_id": self._symbol_to_counter_id(normalized_symbol)})
        try:
            payload = self._get_http_client().request("get", f"/v1/quote/valuation/detail?{query}")
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge valuation detail: {_format_longbridge_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise LongbridgeExternalDataError("Longbridge valuation detail response is not an object")
        return payload

    def get_forecast_eps(self, symbol: str) -> dict:
        self._ensure_available()
        normalized_symbol = normalize_longbridge_symbol(symbol)
        query = urlencode({"counter_id": self._symbol_to_counter_id(normalized_symbol)})
        try:
            payload = self._get_http_client().request("get", f"/v1/quote/forecast-eps?{query}")
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge forecast EPS: {_format_longbridge_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise LongbridgeExternalDataError("Longbridge forecast EPS response is not an object")
        return payload

    def get_finance_calendar(
        self,
        *,
        start: str,
        end: str,
        market: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict:
        """Fetch read-only Longbridge finance calendar data."""
        self._ensure_available()
        if self._sdk.CalendarContext is None or not hasattr(self._sdk.module, "CalendarCategory"):
            raise LongbridgeUnavailableError("Installed Longbridge SDK does not expose finance calendar APIs")
        start_date, end_date = self._validate_date_range(start, end)
        categories = {
            "earnings": self._sdk.module.CalendarCategory.Report,
            "dividends": self._sdk.module.CalendarCategory.Dividend,
            "splits": self._sdk.module.CalendarCategory.Split,
            "ipos": self._sdk.module.CalendarCategory.Ipo,
        }
        market_arg = self._resolve_market(market) if market else None
        payload: dict[str, Any] = {}
        try:
            for key, category in categories.items():
                payload[key] = _to_json_value(
                    self._get_calendar_context().finance_calendar(category, start_date.isoformat(), end_date.isoformat(), market_arg)
                )
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge finance calendar: {_format_longbridge_error(exc)}") from exc
        return payload

    def get_market_status(self, markets: list[str] | None = None) -> dict:
        """Fetch read-only Longbridge market status data."""
        self._ensure_available()
        if self._sdk.MarketContext is None:
            raise LongbridgeUnavailableError("Installed Longbridge SDK does not expose market status APIs")
        try:
            payload = _to_json_value(self._get_market_context().market_status())
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge market status: {_format_longbridge_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise LongbridgeExternalDataError("Longbridge market status response is not an object")
        return payload

    def get_trading_days(self, *, market: str, start: str, end: str) -> dict:
        """Fetch read-only Longbridge trading-day calendar data."""
        self._ensure_available()
        start_date, end_date = self._validate_date_range(start, end)
        try:
            payload = _to_json_value(self._get_quote_context().trading_days(self._resolve_market(market), start_date, end_date))
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge trading days: {_format_longbridge_error(exc)}") from exc
        return {"closed_days": payload}

    def get_trading_sessions(self, markets: list[str] | None = None) -> dict:
        """Fetch read-only Longbridge trading-session data."""
        self._ensure_available()
        try:
            payload = _to_json_value(self._get_quote_context().trading_session())
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge trading sessions: {_format_longbridge_error(exc)}") from exc
        return payload if isinstance(payload, dict) else {"sessions": payload}

    def _validate_date_range(self, start: str, end: str) -> tuple[date, date]:
        start_date = _parse_api_date(start, "start")
        end_date = _parse_api_date(end, "end")
        if start_date > end_date:
            raise ValueError("start must be earlier than or equal to end")
        return start_date, end_date

    def _ensure_available(self) -> None:
        if not self.sdk_loaded:
            raise LongbridgeUnavailableError("Longbridge SDK is not installed")
        if not self.enabled:
            raise LongbridgeUnavailableError("Longbridge external data source is disabled")
        if not self.configured:
            raise LongbridgeUnavailableError("Longbridge OpenAPI OAuth client_id is not configured")
        if not self.oauth_service.get_access_token():
            raise LongbridgeUnavailableError("Longbridge OpenAPI OAuth authorization is required. Complete LongBridge OpenAPI OAuth in the admin console.")

    def _get_oauth(self) -> Any:
        self._ensure_available()
        if self._oauth is None:
            self.oauth_service.sync_sdk_token_cache()
            try:
                client_id = self._oauth_client_id()
                if not client_id:
                    raise LongbridgeUnavailableError("Longbridge OpenAPI OAuth client_id is not configured")
                self._oauth = self._sdk.OAuthBuilder(client_id).build(
                    lambda _url: (_ for _ in ()).throw(LongbridgeUnavailableError("Longbridge OpenAPI OAuth is not connected"))
                )
            except LongbridgeUnavailableError:
                raise
            except Exception as exc:
                raise LongbridgeUnavailableError(f"Failed to initialize Longbridge OpenAPI OAuth: {str(exc)[:200]}") from exc
        return self._oauth

    def _oauth_client_id(self) -> str:
        configured = self.settings.longbridge_openapi_oauth_client_id.strip()
        if configured:
            return configured
        return str(self.oauth_service.status().get("client_id") or "").strip()

    def _get_config(self) -> Any:
        if self._config is None:
            self._config = self._sdk.Config.from_oauth(self._get_oauth())
        return self._config

    def _get_http_client(self) -> Any:
        if self._http_client is None:
            self._http_client = self._sdk.HttpClient.from_oauth(self._get_oauth())
        return self._http_client

    def _get_quote_context(self) -> Any:
        if self._quote_context is None:
            self._quote_context = self._sdk.QuoteContext(self._get_config())
        return self._quote_context

    def _get_content_context(self) -> Any:
        if self._content_context is None:
            self._content_context = self._sdk.ContentContext(self._get_config())
        return self._content_context

    def _get_calendar_context(self) -> Any:
        if self._sdk.CalendarContext is None:
            raise LongbridgeUnavailableError("Installed Longbridge SDK does not expose finance calendar APIs")
        if self._calendar_context is None:
            self._calendar_context = self._sdk.CalendarContext(self._get_config())
        return self._calendar_context

    def _get_market_context(self) -> Any:
        if self._sdk.MarketContext is None:
            raise LongbridgeUnavailableError("Installed Longbridge SDK does not expose market status APIs")
        if self._market_context is None:
            self._market_context = self._sdk.MarketContext(self._get_config())
        return self._market_context

    def _resolve_market(self, market: str | None) -> Any:
        normalized = (market or "").upper()
        if not normalized:
            return None
        if normalized in {"SH", "SZ"}:
            normalized = "CN"
        if hasattr(self._sdk.module.Market, normalized):
            return normalized
        raise ValueError("market must be one of: US, HK, CN, SG")

    def _fetch_candles(self, symbol: str, start: date, end: date, period: str, adjust_type: str) -> list[LongbridgeCandleItem]:
        self._ensure_available()
        try:
            raw_items = self._get_quote_context().history_candlesticks_by_date(
                symbol,
                self._resolve_period(period),
                self._resolve_adjust_type(adjust_type),
                start,
                end,
                self._resolve_trade_sessions(),
            )
        except ValueError:
            raise
        except Exception as exc:
            raise LongbridgeExternalDataError(f"Failed to fetch Longbridge historical candles: {_format_longbridge_error(exc)}") from exc

        return [self._normalize_candle_item(item) for item in raw_items]

    def _resolve_period(self, period: str) -> Any:
        mapping = {
            "day": "Day",
            "week": "Week",
            "month": "Month",
        }
        return getattr(self._sdk.module.Period, mapping[period])

    def _resolve_adjust_type(self, adjust_type: str) -> Any:
        if adjust_type not in SUPPORTED_LONGBRIDGE_ADJUST_TYPES:
            raise ValueError("adjust_type must be one of: forward, backward, none")

        candidates = {
            "forward": ("ForwardAdjust",),
            "backward": ("BackwardAdjust", "Backward"),
            "none": ("NoAdjust",),
        }[adjust_type]
        for candidate in candidates:
            if hasattr(self._sdk.module.AdjustType, candidate):
                return getattr(self._sdk.module.AdjustType, candidate)
        raise ValueError(f"adjust_type={adjust_type} is not supported by the installed Longbridge SDK")

    def _resolve_trade_sessions(self) -> Any:
        return getattr(self._sdk.module.TradeSessions, "Intraday")

    def _resolve_calc_indexes(self) -> list[Any]:
        calc_index = self._sdk.module.CalcIndex
        names = [
            "LastDone",
            "ChangeRate",
            "FiveDayChangeRate",
            "TenDayChangeRate",
            "HalfYearChangeRate",
            "YtdChangeRate",
            "PeTtmRatio",
            "PbRatio",
            "DividendRatioTtm",
            "TotalMarketValue",
            "TurnoverRate",
            "VolumeRatio",
        ]
        return [getattr(calc_index, name) for name in names if hasattr(calc_index, name)]

    def _symbol_to_counter_id(self, symbol: str) -> str:
        if "." not in symbol:
            return symbol
        code, market = symbol.rsplit(".", 1)
        market = market.upper()
        if code.startswith("."):
            return f"IX/{market}/{code}"
        normalized_code = code.lstrip("0") if code.isdigit() else code
        if not normalized_code:
            normalized_code = code
        prefix = "ETF" if market == "US" and normalized_code.upper() in {"SPY", "QQQ", "SMH"} else "ST"
        return f"{prefix}/{market}/{normalized_code.upper()}"

    def _first_serialized_item(self, items: Any, symbol: str) -> dict:
        serialized = [_to_json_value(item) for item in list(items)]
        for item in serialized:
            if str(item.get("symbol", "")).upper() == symbol.upper():
                return item
        return serialized[0] if serialized else {"symbol": symbol}

    def _normalize_candle_item(self, item: Any) -> LongbridgeCandleItem:
        timestamp = _get_attr(item, "timestamp", "date")
        return LongbridgeCandleItem(
            date=_to_candle_date(timestamp),
            open=_to_float(_get_attr(item, "open")),
            high=_to_float(_get_attr(item, "high")),
            low=_to_float(_get_attr(item, "low")),
            close=_to_float(_get_attr(item, "close")),
            volume=_to_int(_get_attr(item, "volume")),
            turnover=_to_float(_get_attr(item, "turnover")),
        )

    def _normalize_news_item(self, item: Any) -> LongbridgeNewsItem:
        return LongbridgeNewsItem(
            title=str(_get_attr(item, "title") or ""),
            summary=str(_get_attr(item, "description", "summary") or ""),
            url=str(_get_attr(item, "url") or ""),
            published_at=_to_iso_datetime(_get_attr(item, "published_at", "publishedAt", "released_at", "time", "timestamp", "updated_at")),
        )
