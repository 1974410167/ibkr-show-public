"""
Longbridge MCP Tool Adapter - whitelist enforcement, output compaction, structured returns.

Sub-agents MUST go through this adapter. Direct calls to LongbridgeMCPClient are forbidden.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any

from app.services.mcp.longbridge_mcp_client import LongbridgeMCPClient

logger = logging.getLogger(__name__)


# === Tool Allowlist ===
ALLOWED_LONGBRIDGE_MCP_TOOLS: frozenset[str] = frozenset({
    "quote",
    "candlesticks",
    "history_candlesticks",
    "news_search",
    "company",
    "financial_report",
    "valuation",
    "industry_peers",
    "institution_rating",
    "institution_rating_detail",
    "institution_rating_history",
    "consensus",
    "analyst_estimates",
    "finance_calendar",
    "business_segments",
    "business_segments_history",
    "static_info",
    "financial_report_latest",
    "financial_report_snapshot",
    "financial_statement",
    "forecast_eps",
    "market_status",
})

# === Forbidden Tool List ===
FORBIDDEN_LONGBRIDGE_MCP_TOOLS: frozenset[str] = frozenset({
    "submit_order",
    "replace_order",
    "cancel_order",
    "dca_create",
    "withdrawal",
    "withdrawals",
    "account_statement",
    "account_balance",
    "stock_positions",
    "orders",
    "today_orders",
    "history_orders",
    "order_detail",
    "executions",
    "today_executions",
    "history_executions",
    "trade_context",
    "positions",
    "deposits",
    "bank_cards",
    "ipo_orders",
    "ipo_order_detail",
    "withdrawal",
    "withdrawals",
})

PUBLIC_READONLY_TOOL_HINTS: frozenset[str] = frozenset({
    "analyst",
    "business",
    "calendar",
    "quote",
    "candle",
    "candlestick",
    "company",
    "consensus",
    "finance",
    "financial",
    "forecast",
    "fundamental",
    "history",
    "industry",
    "institution",
    "market",
    "news",
    "peer",
    "rating",
    "segment",
    "segments",
    "security",
    "static",
    "stock_detail",
    "valuation",
})

ACCOUNT_PRIVATE_TOOL_HINTS: frozenset[str] = frozenset({
    "account",
    "balance",
    "statement",
    "position",
    "positions",
    "portfolio",
    "asset",
    "cash",
    "margin",
    "execution",
    "executions",
    "order",
    "orders",
    "trade_context",
})

TRADING_WRITE_TOOL_HINTS: frozenset[str] = frozenset({
    "submit",
    "replace",
    "cancel",
    "withdraw",
    "deposit",
    "transfer",
    "dca_create",
    "order",
    "trade",
})

EXPECTED_FIELDS_BY_TOOL: dict[str, list[str]] = {
    "quote": ["price", "prev_close", "change_pct", "volume", "market_time"],
    "candlesticks": ["sample_points", "return_pct", "latest_close"],
    "history_candlesticks": ["sample_points", "return_pct", "latest_close"],
    "company": ["name", "description"],
    "financial_report": ["revenue", "net_income", "eps", "latest_period"],
    "valuation": ["pe_ttm", "pe_range"],
    "industry_peers": ["peers"],
    "institution_rating": ["consensus", "target_price", "industry"],
    "consensus": ["eps_forward", "revenue_estimate"],
    "forecast_eps": ["eps_forward"],
    "finance_calendar": ["next_earnings_date"],
    "business_segments": ["segments"],
    "business_segments_history": ["segments"],
    "static_info": ["name", "total_shares", "eps_forward"],
    "news_search": ["items", "published_at", "source"],
    "market_status": ["status"],
}

UNKNOWN_TIME_VALUES = {"", "0", "1970-01-01", "1970-01-01T00:00:00", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00+00:00"}

LOCAL_TO_MCP_TOOL_ALIASES: dict[str, str] = {
    "history_candlesticks": "history_candlesticks_by_date",
    "industry_peers": "industry_valuation",
}


def classify_mcp_tool(tool: str | dict[str, Any]) -> str:
    """Classify an MCP tool into public/private/write/unknown buckets."""
    if isinstance(tool, dict):
        name = str(tool.get("name") or tool.get("tool") or "")
        schema = tool.get("inputSchema") or tool.get("input_schema") or tool.get("schema") or {}
        description = str(tool.get("description") or "")
    else:
        name = str(tool or "")
        schema = {}
        description = ""
    haystack = f"{name} {description}".lower()
    normalized = name.lower()

    schema_text = str(schema).lower()
    if normalized in FORBIDDEN_LONGBRIDGE_MCP_TOOLS:
        if any(write_hint in haystack for write_hint in ("submit", "replace", "cancel", "withdraw", "deposit", "transfer", "dca")):
            return "trading_write"
        return "account_private"
    if any(write_hint in haystack for write_hint in ("submit", "replace", "cancel", "withdraw", "deposit", "transfer", "dca")):
        return "trading_write"
    # Longbridge MCP tools/list and its official schema are the source of truth.
    # Heuristics only classify otherwise unknown catalog entries; public market
    # terms are checked before generic private words such as "statement" so
    # tools like financial_statement stay available.
    if normalized in ALLOWED_LONGBRIDGE_MCP_TOOLS or any(hint in haystack for hint in PUBLIC_READONLY_TOOL_HINTS):
        if not any(hint in schema_text for hint in ("account_id", "order_id", "trade_id", "position_id", "cash_balance")):
            return "public_market_readonly"
    if any(hint in haystack for hint in ACCOUNT_PRIVATE_TOOL_HINTS):
        return "account_private"
    if any(hint in schema_text for hint in ("account_id", "order_id", "trade_id", "position_id", "cash_balance")):
        return "account_private"
    return "unknown"


def _catalog_items_from_response(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        tools = payload.get("tools") or payload.get("items") or payload.get("data") or []
    else:
        tools = payload
    if not isinstance(tools, list):
        return []
    items: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict):
            items.append(tool)
        elif isinstance(tool, str):
            items.append({"name": tool})
    return items


def _is_empty_result(value: Any) -> bool:
    if value is None:
        return True
    if value == {} or value == [] or value == "":
        return True
    if isinstance(value, dict):
        if value.get("sample_points") == 0:
            return True
        if "items" in value and value.get("items") == []:
            return True
        if "peers" in value and value.get("peers") == []:
            return True
        meaningful = {k: v for k, v in value.items() if v not in (None, "", [], {})}
        return not meaningful
    return False


def _raw_response_summary(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())[:10]
        return f"object keys={keys}" if keys else "empty object"
    if isinstance(value, list):
        first = value[0] if value else None
        first_keys = list(first.keys())[:8] if isinstance(first, dict) else []
        return f"list length={len(value)} first_keys={first_keys}"
    text = str(value)
    return text[:180]


def _normalize_public_time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if int(value.timestamp()) == 0:
            return None
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, date):
        iso = value.isoformat()
        return None if iso == "1970-01-01" else iso
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    raw = str(value).strip()
    if raw in UNKNOWN_TIME_VALUES:
        return None
    if raw.isdigit():
        number = int(raw)
        if number <= 0:
            return None
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
    if raw.startswith("1970-01-01"):
        return None
    return raw


def _flatten_present_fields(value: Any, prefix: str = "") -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if item not in (None, "", [], {}):
                fields.add(name)
                fields.add(str(key))
            fields.update(_flatten_present_fields(item, name))
    elif isinstance(value, list):
        for item in value[:3]:
            fields.update(_flatten_present_fields(item, prefix))
    return fields


def _build_tool_diagnostics(
    *,
    tool_name: str,
    mcp_tool_name: str,
    request_args: dict[str, Any],
    success: bool,
    raw_data: Any,
    parsed_data: Any,
    error_type: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    parsed_fields = sorted(_flatten_present_fields(parsed_data))
    expected_fields = EXPECTED_FIELDS_BY_TOOL.get(tool_name, [])
    missing_fields = [
        {
            "tool_name": tool_name,
            "request_args": request_args,
            "field_name": field_name,
            "success": success,
            "empty_result": _is_empty_result(parsed_data),
            "raw_response_summary": _raw_response_summary(raw_data),
            "error_type": error_type or ("empty_result" if _is_empty_result(parsed_data) else None),
        }
        for field_name in expected_fields
        if field_name not in parsed_fields
    ]
    return {
        "tool_name": tool_name,
        "mcp_tool_name": mcp_tool_name,
        "request_args": request_args,
        "success": success,
        "empty_result": _is_empty_result(parsed_data),
        "raw_response_summary": _raw_response_summary(raw_data),
        "parsed_fields": parsed_fields,
        "missing_fields": missing_fields,
        "error_type": error_type,
        "message": message,
    }


def _normalize_candle_items(raw: Any) -> list[dict[str, Any]]:
    """Return compact OHLCV rows for deterministic engines, not for LLM prompts."""
    items = raw
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("candles") or raw.get("data") or []
    if not isinstance(items, list):
        return []

    candles: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        close = item.get("close") if item.get("close") is not None else item.get("c")
        if close is None:
            continue
        candle = {
            "timestamp": item.get("timestamp") or item.get("date") or item.get("time"),
            "open": item.get("open") if item.get("open") is not None else item.get("o"),
            "high": item.get("high") if item.get("high") is not None else item.get("h"),
            "low": item.get("low") if item.get("low") is not None else item.get("l"),
            "close": close,
            "volume": item.get("volume") if item.get("volume") is not None else item.get("v"),
        }
        candles.append({key: value for key, value in candle.items() if value is not None})
    return candles


def _build_engine_payload(tool_name: str, raw_data: Any, *, symbol: str | None = None) -> dict[str, Any] | None:
    if tool_name not in {"candlesticks", "history_candlesticks"}:
        return None
    candles = _normalize_candle_items(raw_data)
    if not candles:
        return None
    return {
        "kind": "ohlcv_candles",
        "symbol": symbol,
        "candles": candles,
    }


class LongbridgeMCPToolAdapter:
    """
    Adapter for Longbridge MCP calls.
    - Enforces whitelist (only read-only market data tools)
    - Enforces forbidden list (blocks all write/trade/account operations)
    - Returns structured dicts, never raises
    - Compacts output before returning
    - Ensures tokens/headers never appear in returned data
    """

    def __init__(self, client: LongbridgeMCPClient | None) -> None:
        self.client = client
        self._tool_catalog_cache: dict[str, Any] | None = None

    def get_tool_catalog(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return classified MCP tool catalog, falling back to static public aliases."""
        if self._tool_catalog_cache is not None and not force_refresh:
            return self._tool_catalog_cache

        tools: list[dict[str, Any]] = []
        source = "static_fallback"
        list_error = None
        if self.client is not None and getattr(self.client, "enabled", False) and hasattr(self.client, "list_tools"):
            try:
                response = self.client.list_tools()
                if isinstance(response, dict) and response.get("ok"):
                    tools = _catalog_items_from_response(response.get("data"))
                    source = "mcp_tools_list"
                elif isinstance(response, dict):
                    list_error = response.get("message") or response.get("error_code")
            except Exception as exc:
                list_error = str(exc)[:200]

        if not tools:
            tools = [{"name": name} for name in sorted(ALLOWED_LONGBRIDGE_MCP_TOOLS | set(LOCAL_TO_MCP_TOOL_ALIASES.values()))]

        classified = []
        for tool in tools:
            name = str(tool.get("name") or "")
            classification = classify_mcp_tool(tool)
            classified.append({
                "name": name,
                "classification": classification,
                "allowed": classification == "public_market_readonly" and name not in FORBIDDEN_LONGBRIDGE_MCP_TOOLS,
                "description": tool.get("description"),
                "input_schema": tool.get("inputSchema") or tool.get("input_schema") or tool.get("schema") or {},
            })

        self._tool_catalog_cache = {
            "source": source,
            "list_error": list_error,
            "tools": classified,
            "public_market_readonly": [item["name"] for item in classified if item["classification"] == "public_market_readonly"],
            "blocked": [item["name"] for item in classified if item["classification"] != "public_market_readonly"],
        }
        return self._tool_catalog_cache

    def _is_allowed_public_tool(self, local_tool_name: str, mcp_tool_name: str) -> bool:
        if local_tool_name in FORBIDDEN_LONGBRIDGE_MCP_TOOLS or mcp_tool_name in FORBIDDEN_LONGBRIDGE_MCP_TOOLS:
            return False
        catalog = self.get_tool_catalog()
        public_tools = set(catalog.get("public_market_readonly") or [])
        if catalog.get("source") == "mcp_tools_list":
            return local_tool_name in public_tools or mcp_tool_name in public_tools
        if local_tool_name in ALLOWED_LONGBRIDGE_MCP_TOOLS or mcp_tool_name in ALLOWED_LONGBRIDGE_MCP_TOOLS:
            return True
        return local_tool_name in public_tools or mcp_tool_name in public_tools or classify_mcp_tool(local_tool_name) == "public_market_readonly"

    def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Call a Longbridge MCP tool through the adapter.
        Returns: {"ok": bool, "tool": str, "data": Any, "error_code": str|None,
                  "message": str|None, "data_limitations": list[str]}
        """
        catalog = self.get_tool_catalog()
        public_tools = set(catalog.get("public_market_readonly") or [])
        mcp_tool_name, mcp_arguments = _map_tool_call(tool_name, arguments or {}, available_tools=public_tools)

        # Step 1: Forbidden list check
        if tool_name in FORBIDDEN_LONGBRIDGE_MCP_TOOLS or mcp_tool_name in FORBIDDEN_LONGBRIDGE_MCP_TOOLS:
            return {
                "ok": False,
                "tool": tool_name,
                "mcp_tool": mcp_tool_name,
                "data": None,
                "error_code": "MCP_TOOL_FORBIDDEN",
                "message": f"Tool '{tool_name}' is explicitly forbidden",
                "data_limitations": [f"Tool '{tool_name}' is in the forbidden list: write/trade operations are not permitted"],
                "tool_call": _build_tool_diagnostics(
                    tool_name=tool_name,
                    mcp_tool_name=mcp_tool_name,
                    request_args=mcp_arguments,
                    success=False,
                    raw_data=None,
                    parsed_data=None,
                    error_type="MCP_TOOL_FORBIDDEN",
                    message=f"Tool '{tool_name}' is explicitly forbidden",
                ),
            }

        # Step 2: Dynamic public readonly catalog check
        if not self._is_allowed_public_tool(tool_name, mcp_tool_name):
            return {
                "ok": False,
                "tool": tool_name,
                "mcp_tool": mcp_tool_name,
                "data": None,
                "error_code": "MCP_TOOL_NOT_ALLOWED",
                "message": f"Tool '{tool_name}' is not classified as public market readonly",
                "data_limitations": [f"Tool '{tool_name}' is not classified as public_market_readonly"],
                "tool_call": _build_tool_diagnostics(
                    tool_name=tool_name,
                    mcp_tool_name=mcp_tool_name,
                    request_args=mcp_arguments,
                    success=False,
                    raw_data=None,
                    parsed_data=None,
                    error_type="MCP_TOOL_NOT_ALLOWED",
                    message=f"Tool '{tool_name}' is not classified as public market readonly",
                ),
            }

        # Step 3: Client disabled
        if self.client is None or not self.client.enabled:
            return {
                "ok": False,
                "tool": tool_name,
                "mcp_tool": mcp_tool_name,
                "data": None,
                "error_code": "MCP_UNAVAILABLE",
                "message": "MCP client is not available",
                "data_limitations": ["MCP is disabled or not configured"],
                "tool_call": _build_tool_diagnostics(
                    tool_name=tool_name,
                    mcp_tool_name=mcp_tool_name,
                    request_args=mcp_arguments,
                    success=False,
                    raw_data=None,
                    parsed_data=None,
                    error_type="MCP_UNAVAILABLE",
                    message="MCP client is not available",
                ),
            }

        # Step 4: Call the client (client already has its own forbidden keyword check)
        raw_result = self.client.call_tool(mcp_tool_name, mcp_arguments)

        # Step 5: Compact the output
        if raw_result.get("ok"):
            raw_data = raw_result.get("data")
            compact_data = _compact_tool_output(tool_name, raw_data)
            engine_payload = _build_engine_payload(tool_name, raw_data, symbol=mcp_arguments.get("symbol"))
            logger.info(
                "MCP tool %s: ok=True, raw_type=%s, raw_keys=%s, compact_keys=%s",
                tool_name,
                type(raw_data).__name__,
                list(raw_data.keys())[:6] if isinstance(raw_data, dict) else f"list[{len(raw_data)}]" if isinstance(raw_data, list) else "N/A",
                list(compact_data.keys())[:6] if isinstance(compact_data, dict) else "N/A",
            )
            return {
                "ok": True,
                "tool": tool_name,
                "mcp_tool": mcp_tool_name,
                "data": compact_data,
                "error_code": None,
                "message": None,
                "data_limitations": [],
                "tool_call": _build_tool_diagnostics(
                    tool_name=tool_name,
                    mcp_tool_name=mcp_tool_name,
                    request_args=mcp_arguments,
                    success=True,
                    raw_data=raw_data,
                    parsed_data=compact_data,
                ),
                **({"engine_payload": engine_payload} if engine_payload else {}),
            }
        else:
            logger.warning(
                "MCP tool %s: ok=False, error_code=%s, message=%s",
                tool_name,
                raw_result.get("error_code"),
                raw_result.get("message", "")[:200],
            )
            # Forward the error, strip any sensitive data
            return {
                "ok": False,
                "tool": tool_name,
                "mcp_tool": mcp_tool_name,
                "data": None,
                "error_code": raw_result.get("error_code", "MCP_UNKNOWN_ERROR"),
                "message": raw_result.get("message", "Unknown MCP error"),
                "data_limitations": raw_result.get("data_limitations", []),
                "tool_call": _build_tool_diagnostics(
                    tool_name=tool_name,
                    mcp_tool_name=mcp_tool_name,
                    request_args=mcp_arguments,
                    success=False,
                    raw_data=raw_result,
                    parsed_data=None,
                    error_type=raw_result.get("error_code", "MCP_UNKNOWN_ERROR"),
                    message=raw_result.get("message", "Unknown MCP error"),
                ),
            }


# === Output Compactors ===

def _compact_tool_output(tool_name: str, raw: Any) -> Any:
    """Route to the appropriate compactor based on tool name."""
    if tool_name == "quote":
        return _compact_quote(raw)
    if tool_name in ("candlesticks", "history_candlesticks"):
        return _compact_candles(raw)
    if tool_name == "news_search":
        return _compact_news(raw)
    if tool_name == "financial_report":
        return _compact_financial(raw)
    if tool_name in ("business_segments", "business_segments_history"):
        return _compact_business_segments(raw)
    if tool_name == "valuation":
        return _compact_valuation(raw)
    if tool_name == "industry_peers":
        return _compact_industry_peers(raw)
    if tool_name in ("institution_rating", "institution_rating_detail", "institution_rating_history", "consensus"):
        return _compact_institution_rating(raw)
    if tool_name == "forecast_eps":
        return _compact_forecast_eps(raw)
    if tool_name == "finance_calendar":
        return _compact_calendar(raw)
    if tool_name in ("company", "static_info"):
        return _compact_company(raw)
    if tool_name == "market_status":
        return _compact_market_status(raw)
    return raw


def _map_tool_call(tool_name: str, arguments: dict[str, Any], available_tools: set[str] | None = None) -> tuple[str, dict[str, Any]]:
    """Map local adapter names/schemas to Longbridge hosted MCP tool names/schemas."""
    symbol = arguments.get("symbol")
    if tool_name == "quote":
        return "quote", {"symbols": [symbol] if symbol else arguments.get("symbols", [])}
    if tool_name == "candlesticks":
        return "candlesticks", {
            "symbol": symbol,
            "period": arguments.get("period") or "day",
            "count": int(arguments.get("count") or 260),
            "forward_adjust": _is_forward_adjust(arguments),
            "trade_sessions": arguments.get("trade_sessions") or "all",
        }
    if tool_name == "history_candlesticks":
        return "history_candlesticks_by_date", {
            "symbol": symbol,
            "period": arguments.get("period") or "day",
            "start": arguments.get("start"),
            "end": arguments.get("end"),
            "forward_adjust": _is_forward_adjust(arguments),
            "trade_sessions": arguments.get("trade_sessions") or "all",
        }
    if tool_name == "news_search":
        return "news_search", {
            "keyword": arguments.get("keyword") or symbol or "",
            "limit": int(arguments.get("limit") or 8),
        }
    if tool_name == "financial_report":
        mapped = {
            "symbol": symbol,
            "kind": arguments.get("kind"),
            "report_type": arguments.get("report_type") or arguments.get("period"),
        }
        return "financial_report", {k: v for k, v in mapped.items() if v is not None}
    if tool_name == "static_info":
        symbols = arguments.get("symbols")
        if not symbols and symbol:
            symbols = [symbol]
        return "static_info", {"symbols": symbols or []}
    if tool_name == "forecast_eps":
        return "forecast_eps", {"symbol": symbol}
    if tool_name == "industry_peers":
        if available_tools is None:
            target = "industry_valuation"
        elif "industry_valuation" in available_tools:
            target = "industry_valuation"
        else:
            target = "industry_peers"
        return target, {"symbol": symbol}
    if tool_name == "finance_calendar":
        today = date.today()
        mapped = {
            "category": arguments.get("category") or "report",
            "start": arguments.get("start") or today.isoformat(),
            "end": arguments.get("end") or (today + timedelta(days=180)).isoformat(),
            "market": arguments.get("market"),
        }
        return "finance_calendar", {k: v for k, v in mapped.items() if v not in (None, "")}
    if tool_name == "market_status":
        return "market_status", {}
    return tool_name, arguments


def _is_forward_adjust(arguments: dict[str, Any]) -> bool:
    adjust_type = str(arguments.get("adjust_type") or "").lower()
    if adjust_type:
        return adjust_type != "none"
    return bool(arguments.get("forward_adjust", True))


def _compact_quote(raw: Any) -> dict:
    """Compress quote tool output to essential fields."""
    # The MCP quote tool may return a list (array of quotes) or a single dict.
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}
    price = raw.get("last_done") or raw.get("last_price") or raw.get("close")
    prev_close = raw.get("prev_close")
    change_pct = raw.get("change_ratio") or raw.get("change_percent")
    if change_pct in (None, "") and price not in (None, "") and prev_close not in (None, ""):
        try:
            price_num = float(price)
            prev_num = float(prev_close)
            if prev_num > 0:
                change_pct = round((price_num - prev_num) / prev_num * 100, 4)
        except (TypeError, ValueError):
            change_pct = None
    return {
        "symbol": raw.get("symbol"),
        "price": price,
        "prev_close": prev_close,
        "open": raw.get("open"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "change_pct": change_pct,
        "volume": raw.get("volume"),
        "turnover": raw.get("turnover"),
        "market_time": raw.get("timestamp") or raw.get("update_time"),
        "trade_status": raw.get("trade_status"),
    }


def _compact_candles(raw: Any) -> dict:
    """
    Compress candles list to summary stats.
    The raw may be a dict with "items" key or a list directly.
    """
    items = raw
    if isinstance(raw, dict):
        items = raw.get("items", []) or []
    if not isinstance(items, list) or not items:
        return {"sample_points": 0, "summary": "no_data"}

    def number(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    closes: list[float] = []
    daily_returns: list[float] = []
    peak: float | None = None
    max_dd = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        open_p = number(item.get("open"))
        close_p = number(item.get("close"))
        high_p = number(item.get("high"))
        low_p = number(item.get("low"))
        if close_p is not None:
            closes.append(close_p)
        if open_p is not None and close_p is not None:
            daily_returns.append((close_p - open_p) / open_p * 100)
        if high_p is not None:
            peak = high_p if peak is None else max(peak, high_p)
        if peak and low_p is not None:
            max_dd = min(max_dd, (low_p - peak) / peak * 100)

    first_open = number(items[0].get("open")) if isinstance(items[0], dict) else None
    last_close = closes[-1] if closes else None
    period_return = ((last_close - first_open) / first_open * 100) if first_open and last_close else 0
    avg_daily_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    volatility = (
        "high" if abs(avg_daily_return) > 5
        else "medium" if abs(avg_daily_return) > 2
        else "low"
    )

    return {
        "sample_points": len(items),
        "time_range": f"{items[0].get('timestamp', items[0].get('date', '?'))[:10]} to {items[-1].get('timestamp', items[-1].get('date', '?'))[:10]}",
        "return_pct": round(period_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "volatility_summary": volatility,
        "trend_summary": "bullish" if period_return > 3 else "bearish" if period_return < -3 else "neutral",
        "latest_close": last_close,
    }


def _compact_news(raw: Any, limit: int = 15) -> dict:
    """Compress news list to essential fields."""
    items = raw
    if isinstance(raw, dict):
        items = raw.get("items", []) or []
    if not isinstance(items, list):
        return {"items": []}

    result = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        published_at = _normalize_public_time(
            item.get("published_at")
            or item.get("released_at")
            or item.get("datetime")
            or item.get("time")
            or item.get("timestamp")
            or item.get("updated_at")
            or item.get("created_at")
        )
        result.append({
            "title": str(item.get("title", ""))[:120],
            "published_at": published_at[:19] if published_at else None,
            "source": str(item.get("source") or item.get("source_name") or item.get("provider") or item.get("publisher") or item.get("media") or "")[:40],
            "summary": str(item.get("summary") or item.get("description") or item.get("excerpt") or item.get("content") or "")[:200],
            "sentiment_hint": str(item.get("sentiment", item.get("label", "")))[:20],
        })
    return {"items": result, "total_returned": len(result)}


def _compact_financial(raw: Any) -> dict:
    """Compress financial report — handle Longbridge MCP nested structure.

    MCP returns:
    {
      "report": "qf",
      "list": {
        "i_s": {"indicators": [{"title": "每股收益", "accounts": [{"field": "EPS", "values": [{"year": 2026, "period": "Q3 2026", "value": "1.27", "yoy": "24.5%"}]}]}]},
        "b_s": {"indicators": [...]},
        "c_f": {"indicators": [...]}
      }
    }
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, Any] = {}
    report_type = raw.get("report", "")
    result["report_type"] = report_type

    list_data = raw.get("list", {})
    if not isinstance(list_data, dict):
        return result

    # Extract from income statement (i_s)
    _extract_indicators(list_data.get("i_s"), result, {
        "EPS": "eps",
        "OperatingRevenue": "revenue",
        "NetProfit": "net_income",
        "OperatingIncome": "operating_income",
        "GrossMgn": "gross_margin",
        "NetProfitMargin": "net_margin",
        "ROE": "roe",
        "ProfitQuality": "profit_quality",
    })

    # Extract from balance sheet (b_s)
    _extract_indicators(list_data.get("b_s"), result, {
        "TotalAssets": "total_assets",
        "TotalLiab": "total_liabilities",
        "TotalEquity": "shareholders_equity",
    })

    # Extract from cash flow (c_f)
    _extract_indicators(list_data.get("c_f"), result, {
        "OperateCashFlow": "operating_cash_flow",
        "InvestCashFlow": "investing_cash_flow",
        "FreeCashFlow": "free_cash_flow",
    })

    # Try to compute margins if we have revenue and other values
    revenue = result.get("revenue")
    net_income = result.get("net_income")
    if revenue and net_income and revenue > 0:
        result["net_margin"] = round(net_income / revenue * 100, 2)
    operating_income = result.get("operating_income")
    if revenue and operating_income and revenue > 0:
        result["operating_margin"] = round(operating_income / revenue * 100, 2)

    return result


def _compact_business_segments(raw: Any) -> dict:
    items = raw
    if isinstance(raw, dict):
        items = raw.get("segments") or raw.get("business") or raw.get("items") or raw.get("list") or raw.get("data") or []
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        return {"segments": []}
    segments = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        segments.append({
            "name": item.get("name") or item.get("segment") or item.get("business") or item.get("title"),
            "revenue": item.get("revenue") or item.get("sales") or item.get("value"),
            "revenue_pct": item.get("revenue_pct") or item.get("ratio") or item.get("percentage") or item.get("percent"),
            "period": item.get("period") or item.get("year") or (raw.get("report_txt") if isinstance(raw, dict) else None),
            "yoy": item.get("yoy"),
        })
    return {"segments": [item for item in segments if item.get("name")], "total_returned": len(segments)}


def _extract_indicators(section: Any, result: dict, field_map: dict[str, str]) -> None:
    """Extract latest values from a financial report section."""
    if not isinstance(section, dict):
        return
    indicators = section.get("indicators", [])
    if not isinstance(indicators, list):
        return
    for indicator in indicators:
        if not isinstance(indicator, dict):
            continue
        accounts = indicator.get("accounts", [])
        if not isinstance(accounts, list):
            continue
        for account in accounts:
            if not isinstance(account, dict):
                continue
            field_name = account.get("field", "")
            if field_name not in field_map:
                continue
            values = account.get("values", [])
            if not isinstance(values, list) or not values:
                continue
            # Take the latest value (first in list)
            latest = values[0] if isinstance(values[0], dict) else {}
            raw_value = latest.get("value")
            yoy = latest.get("yoy")
            period = latest.get("period", "")
            if raw_value is not None:
                try:
                    result[field_map[field_name]] = float(raw_value)
                except (TypeError, ValueError):
                    result[field_map[field_name]] = raw_value
            if yoy is not None:
                try:
                    result[f"{field_map[field_name]}_yoy"] = float(yoy)
                except (TypeError, ValueError):
                    pass
            if period:
                result["latest_period"] = period


def _compact_valuation(raw: Any) -> dict:
    """Compress valuation metrics — handle Longbridge MCP response format.

    MCP returns:
    {
      "metrics": {
        "pe": {"low": "29.81", "median": "40.93", "high": "56.15",
               "desc": "当前市盈率 33.43，处于合理区间...",
               "list": [{"timestamp": "...", "value": "33.43"}, ...]},
        "pb": {...},
        "ps": {...},
        ...
      },
      "range": 1
    }
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}

    metrics = raw.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    result: dict[str, Any] = {}

    # Extract PE
    pe_data = metrics.get("pe", {})
    if isinstance(pe_data, dict):
        pe_value = _extract_metric_current_value(pe_data)
        if pe_value is not None:
            result["pe_ttm"] = pe_value
        result["pe_range"] = {"low": pe_data.get("low"), "median": pe_data.get("median"), "high": pe_data.get("high")}
        result["pe_desc"] = _strip_html(str(pe_data.get("desc", "")))[:200]

    for key in ("forward_pe", "fwd_pe", "forward_pe_ratio", "pe_forward"):
        value = _extract_any_numeric(raw, key)
        if value is not None:
            result["forward_pe"] = value
            break

    # Extract PB
    pb_data = metrics.get("pb", {})
    if isinstance(pb_data, dict):
        pb_value = _extract_metric_current_value(pb_data)
        if pb_value is not None:
            result["pb_ratio"] = pb_value
        result["pb_desc"] = _strip_html(str(pb_data.get("desc", "")))[:200]

    # Extract PS
    ps_data = metrics.get("ps", {})
    if isinstance(ps_data, dict):
        ps_value = _extract_metric_current_value(ps_data)
        if ps_value is not None:
            result["ps_ttm"] = ps_value

    # Extract dividend yield
    div_data = metrics.get("dividend_yield", {})
    if isinstance(div_data, dict):
        div_value = _extract_metric_current_value(div_data)
        if div_value is not None:
            result["dividend_yield"] = div_value

    # Extract any other metrics dynamically
    for key in ("ev_ebitda", "roe", "roa", "market_cap"):
        m = metrics.get(key, {})
        if isinstance(m, dict):
            v = _extract_metric_current_value(m)
            if v is not None:
                result[key] = v
    if "market_cap" not in result:
        market_cap = _extract_any_numeric(raw, "market_cap") or _extract_any_numeric(raw, "total_market_value")
        if market_cap is not None:
            result["market_cap"] = market_cap

    return result


def _extract_any_numeric(value: Any, target_key: str) -> float | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == target_key.lower():
                try:
                    number = float(item)
                    return number if number > 0 else None
                except (TypeError, ValueError):
                    if isinstance(item, dict):
                        nested = _extract_metric_current_value(item)
                        if nested is not None:
                            return nested
            nested = _extract_any_numeric(item, target_key)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value[:10]:
            nested = _extract_any_numeric(item, target_key)
            if nested is not None:
                return nested
    return None


def _extract_metric_current_value(metric: dict) -> float | None:
    """Extract the current value from a Longbridge MCP metric object.

    The metric has 'list' with historical values — the last entry is current.
    Also has 'desc' with HTML containing the current value.
    """
    values = metric.get("list", [])
    if isinstance(values, list) and values:
        last = values[-1] if isinstance(values[-1], dict) else {}
        raw = last.get("value")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _compact_industry_peers(raw: Any, limit: int = 8) -> dict:
    """Compress industry peers list.

    Supports both industry_peers format (items) and industry_valuation format
    (list with symbol/name/market_value/pe/pb/ps fields).
    """
    items = raw
    if isinstance(raw, dict):
        items = raw.get("list") or raw.get("items") or raw.get("peers") or []
    if isinstance(items, dict):
        items = list(items.values()) if items else []
    if not isinstance(items, list):
        return {"peers": []}

    result = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        result.append({
            "symbol": item.get("symbol", ""),
            "name": str(item.get("name", ""))[:60],
            "market_cap": item.get("market_cap") or item.get("total_market_value") or item.get("market_value"),
            "pe": item.get("pe") or item.get("pe_ratio"),
            "pb": item.get("pb") or item.get("pb_ratio"),
            "ps": item.get("ps") or item.get("ps_ratio"),
            "recent_return": item.get("change_ratio") or item.get("return"),
        })
    return {"peers": result, "total_returned": len(result)}


def _compact_institution_rating(raw: Any) -> dict:
    """Compress institutional ratings."""
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}
    instratings = raw.get("instratings") if isinstance(raw.get("instratings"), dict) else {}
    analyst = raw.get("analyst") if isinstance(raw.get("analyst"), dict) else {}
    target = analyst.get("target") if isinstance(analyst.get("target"), dict) else {}
    evaluate = analyst.get("evaluate") if isinstance(analyst.get("evaluate"), dict) else {}
    eps_forward = _extract_consensus_estimate(raw, {"eps", "normalized_eps"})
    revenue_estimate = _extract_consensus_estimate(raw, {"revenue"})
    return {
        "consensus": raw.get("consensus") or raw.get("rating_consensus") or raw.get("rating") or raw.get("recommendation") or instratings.get("recommend"),
        "target_price": raw.get("target_price") or raw.get("target") or raw.get("price_target") or instratings.get("target"),
        "target_price_high": target.get("highest_price"),
        "target_price_low": target.get("lowest_price"),
        "rating_distribution": instratings.get("evaluate") or evaluate,
        "industry": analyst.get("industry_name"),
        "industry_rank": analyst.get("industry_rank"),
        "industry_total": analyst.get("industry_total"),
        "changes": raw.get("rating_changes") or raw.get("changes") or raw.get("items"),
        "eps_forward": eps_forward,
        "revenue_estimate": revenue_estimate,
        "updated_at": str(raw.get("updated_at") or instratings.get("updated_at") or raw.get("date") or raw.get("timestamp") or "")[:19],
    }


def _compact_forecast_eps(raw: Any) -> dict:
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        return {}
    latest = items[-1] if isinstance(items[-1], dict) else {}
    eps_forward = latest.get("forecast_eps_mean") or latest.get("forecast_eps_median")
    return {
        "eps_forward": eps_forward,
        "eps_forward_low": latest.get("forecast_eps_lowest"),
        "eps_forward_high": latest.get("forecast_eps_highest"),
        "forecast_start_date": latest.get("forecast_start_date"),
        "forecast_end_date": latest.get("forecast_end_date"),
        "sample_points": len(items),
    }


def _extract_consensus_estimate(raw: dict[str, Any], keys: set[str]) -> Any:
    rows = raw.get("list")
    if not isinstance(rows, list):
        return None
    for row in rows:
        details = row.get("details") if isinstance(row, dict) else None
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict) or detail.get("key") not in keys:
                continue
            estimate = detail.get("estimate")
            if estimate not in (None, ""):
                return estimate
    return None


def _compact_calendar(raw: Any) -> dict:
    """Compress finance calendar."""
    items = raw
    if isinstance(raw, dict):
        items = raw.get("items", []) or []
    if not isinstance(items, list) or not items:
        return {}

    first = items[0] if items else {}
    return {
        "next_earnings_date": first.get("earnings_date") or first.get("report_date") or first.get("date"),
        "dividend_date": first.get("dividend_date"),
        "important_events": [str(e.get("event") or e.get("title") or e.get("name") or e)[:80] for e in items[:5] if isinstance(e, dict)],
    }


def _compact_company(raw: Any) -> dict:
    """Compress company info — handle Longbridge MCP response format.

    Actual MCP fields: name (Chinese), company_name (English), ticker, market,
    founded, employees, website, profile, region, address, sector, etc.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return {}
    return {
        "name": raw.get("company_name") or raw.get("name_en") or raw.get("name"),
        "name_local": raw.get("name") or raw.get("name_cn") or raw.get("name_hk"),
        "symbol": raw.get("ticker") or raw.get("symbol"),
        "market": raw.get("market"),
        "exchange": raw.get("exchange"),
        "currency": raw.get("currency"),
        "region": raw.get("region"),
        "sector": raw.get("sector") or raw.get("sector_name"),
        "industry": raw.get("industry") or raw.get("industry_name") or raw.get("sector") or raw.get("sector_name"),
        "founded": raw.get("founded"),
        "listing_date": raw.get("listing_date"),
        "employees": raw.get("employees"),
        "address": str(raw.get("address", ""))[:200],
        "website": raw.get("website"),
        "description": str(raw.get("profile") or raw.get("description", ""))[:500],
        "year_end": raw.get("year_end"),
        "market_cap": raw.get("market_cap") or raw.get("total_market_value"),
        "total_shares": raw.get("total_shares"),
        "circulating_shares": raw.get("circulating_shares"),
        "eps_forward": raw.get("eps") or raw.get("eps_ttm"),
        "dividend_yield": raw.get("dividend_yield"),
        "business_segments": raw.get("business_segments") or raw.get("segments") or raw.get("business") or raw.get("business_scope"),
    }


def _compact_market_status(raw: Any) -> dict:
    """Compress market status."""
    if not isinstance(raw, dict):
        return {}
    return {
        "status": raw.get("status"),
        "session": raw.get("session"),
    }
