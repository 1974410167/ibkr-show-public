"""
Tests for LongbridgeMCPToolAdapter - whitelist enforcement, forbidden list,
output compaction, and security checks.
"""

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

REMOVED_MCP_TOKEN_ENV = "LONGBRIDGE_MCP_" + "ACCESS_TOKEN"
REMOVED_OPENAPI_TOKEN_ENV = "LONGBRIDGE_" + "ACCESS_TOKEN"


class TestLongbridgeMCPConfig:
    """Tests for MCP config and OAuth Store-only handling."""

    def test_removed_openapi_token_env_is_not_reused(self, monkeypatch):
        from app.services.mcp.longbridge_mcp_client import get_longbridge_mcp_config

        monkeypatch.setenv("LONGBRIDGE_MCP_ENABLED", "true")
        monkeypatch.delenv(REMOVED_MCP_TOKEN_ENV, raising=False)
        monkeypatch.setenv(REMOVED_OPENAPI_TOKEN_ENV, "legacy-token")

        config = get_longbridge_mcp_config()

        assert config.enabled is True
        assert not hasattr(config, "access_token")

    def test_settings_legacy_token_is_not_used_for_mcp(self, monkeypatch):
        from app.services.mcp.longbridge_mcp_client import get_longbridge_mcp_config

        monkeypatch.setenv("LONGBRIDGE_MCP_ENABLED", "true")
        monkeypatch.delenv(REMOVED_MCP_TOKEN_ENV, raising=False)
        monkeypatch.delenv(REMOVED_OPENAPI_TOKEN_ENV, raising=False)

        config = get_longbridge_mcp_config(SimpleNamespace())

        assert config.enabled is True
        assert not hasattr(config, "access_token")

    def test_removed_mcp_specific_token_is_ignored(self, monkeypatch):
        from app.services.mcp.longbridge_mcp_client import get_longbridge_mcp_config

        monkeypatch.setenv("LONGBRIDGE_MCP_ENABLED", "true")
        monkeypatch.setenv(REMOVED_MCP_TOKEN_ENV, "mcp-token")
        monkeypatch.setenv(REMOVED_OPENAPI_TOKEN_ENV, "existing-token")

        config = get_longbridge_mcp_config()

        assert config.enabled is True
        assert not hasattr(config, "access_token")

    def test_enabled_does_not_require_static_token(self, monkeypatch):
        from app.services.mcp.longbridge_mcp_client import get_longbridge_mcp_config

        monkeypatch.setenv("LONGBRIDGE_MCP_ENABLED", "true")
        monkeypatch.delenv(REMOVED_MCP_TOKEN_ENV, raising=False)
        monkeypatch.delenv(REMOVED_OPENAPI_TOKEN_ENV, raising=False)

        config = get_longbridge_mcp_config()

        assert config.enabled is True
        assert not hasattr(config, "access_token")


class TestLongbridgeMCPToolMapping:
    """Tests for local tool schema to hosted MCP schema mapping."""

    def test_quote_maps_symbol_to_symbols(self):
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        name, arguments = _map_tool_call("quote", {"symbol": "ORCL.US"})

        assert name == "quote"
        assert arguments == {"symbols": ["ORCL.US"]}

    def test_candlesticks_maps_count_and_adjustment(self):
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        name, arguments = _map_tool_call("candlesticks", {"symbol": "ORCL.US", "period": "day", "adjust_type": "forward"})

        assert name == "candlesticks"
        assert arguments["symbol"] == "ORCL.US"
        assert arguments["count"] == 260
        assert arguments["forward_adjust"] is True
        assert arguments["trade_sessions"] == "all"

    def test_history_candlesticks_maps_to_date_tool(self):
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        name, arguments = _map_tool_call(
            "history_candlesticks",
            {"symbol": "ORCL.US", "period": "day", "start": "2026-01-01", "end": "2026-05-20"},
        )

        assert name == "history_candlesticks_by_date"
        assert arguments["start"] == "2026-01-01"
        assert arguments["end"] == "2026-05-20"

    def test_news_search_uses_symbol_as_keyword(self):
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        name, arguments = _map_tool_call("news_search", {"symbol": "ORCL.US", "limit": 3})

        assert name == "news_search"
        assert arguments == {"keyword": "ORCL.US", "limit": 3}


class TestLongbridgeMCPToolAdapter:
    """Tests for LongbridgeMCPToolAdapter security and functionality."""

    @pytest.fixture
    def mock_mcp_client(self):
        client = MagicMock()
        client.enabled = True
        client.call_tool = MagicMock(return_value={"ok": True, "data": {}})
        return client

    @pytest.fixture
    def adapter(self, mock_mcp_client):
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
        return LongbridgeMCPToolAdapter(mock_mcp_client)

    # === Forbidden Tool Tests ===

    def test_submit_order_forbidden(self, adapter):
        """submit_order is explicitly forbidden."""
        result = adapter.call("submit_order")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"
        assert "forbidden" in result["message"].lower()

    def test_replace_order_forbidden(self, adapter):
        """replace_order is explicitly forbidden."""
        result = adapter.call("replace_order")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_cancel_order_forbidden(self, adapter):
        """cancel_order is explicitly forbidden."""
        result = adapter.call("cancel_order")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_dca_create_forbidden(self, adapter):
        """dca_create is explicitly forbidden."""
        result = adapter.call("dca_create")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_withdrawal_forbidden(self, adapter):
        """withdrawal is explicitly forbidden."""
        result = adapter.call("withdrawal")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_withdrawals_forbidden(self, adapter):
        """withdrawals is explicitly forbidden."""
        result = adapter.call("withdrawals")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_account_statement_forbidden(self, adapter):
        """account_statement is explicitly forbidden."""
        result = adapter.call("account_statement")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_account_balance_forbidden(self, adapter):
        """account_balance is explicitly forbidden."""
        result = adapter.call("account_balance")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_stock_positions_forbidden(self, adapter):
        """stock_positions is explicitly forbidden."""
        result = adapter.call("stock_positions")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_orders_forbidden(self, adapter):
        """orders is explicitly forbidden."""
        result = adapter.call("orders")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_executions_forbidden(self, adapter):
        """executions is explicitly forbidden."""
        result = adapter.call("executions")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_trade_context_forbidden(self, adapter):
        """trade_context is explicitly forbidden."""
        result = adapter.call("trade_context")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    def test_positions_forbidden(self, adapter):
        """positions is explicitly forbidden."""
        result = adapter.call("positions")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_FORBIDDEN"

    # === Whitelist Tests ===

    def test_unknown_tool_not_in_whitelist(self, adapter):
        """Unknown tools not in whitelist return MCP_TOOL_NOT_ALLOWED."""
        result = adapter.call("some_unknown_tool")
        assert result["ok"] is False
        assert result["error_code"] == "MCP_TOOL_NOT_ALLOWED"

    def test_quote_allowed(self, adapter, mock_mcp_client):
        """quote is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {"symbol": "AAPL", "last_price": 150.0, "change_ratio": 1.5}
        }
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is True
        assert result["tool"] == "quote"

    def test_candlesticks_allowed(self, adapter, mock_mcp_client):
        """candlesticks is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {"items": [{"open": 100, "close": 105, "high": 110, "low": 99}]}
        }
        result = adapter.call("candlesticks", {"symbol": "AAPL", "count": 100})
        assert result["ok"] is True
        assert result["tool"] == "candlesticks"

    def test_news_search_allowed(self, adapter, mock_mcp_client):
        """news_search is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {"items": [{"title": "AAPL News", "published_at": "2024-01-01"}]}
        }
        result = adapter.call("news_search", {"symbol": "AAPL", "limit": 10})
        assert result["ok"] is True

    def test_company_allowed(self, adapter, mock_mcp_client):
        """company is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"name": "Apple Inc."}}
        result = adapter.call("company", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_financial_report_allowed(self, adapter, mock_mcp_client):
        """financial_report is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"revenue": 100000}}
        result = adapter.call("financial_report", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_valuation_allowed(self, adapter, mock_mcp_client):
        """valuation is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"pe_ttm": 25.0}}
        result = adapter.call("valuation", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_industry_peers_allowed(self, adapter, mock_mcp_client):
        """industry_peers is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": []}}
        result = adapter.call("industry_peers", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_institution_rating_allowed(self, adapter, mock_mcp_client):
        """institution_rating is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"consensus": "BUY"}}
        result = adapter.call("institution_rating", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_finance_calendar_allowed(self, adapter, mock_mcp_client):
        """finance_calendar is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": []}}
        result = adapter.call("finance_calendar", {"symbol": "AAPL"})
        assert result["ok"] is True

    def test_market_status_allowed(self, adapter, mock_mcp_client):
        """market_status is in the allowed list."""
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"status": "open"}}
        result = adapter.call("market_status")
        assert result["ok"] is True

    # === MCP Disabled Tests ===

    def test_mcp_disabled_returns_unavailable(self):
        """When MCP client is disabled or None, returns MCP_UNAVAILABLE."""
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
        adapter = LongbridgeMCPToolAdapter(None)
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is False
        assert result["error_code"] == "MCP_UNAVAILABLE"
        assert "MCP is disabled" in result["data_limitations"][0]

    def test_mcp_client_not_enabled(self, mock_mcp_client):
        """When client.enabled is False, returns MCP_UNAVAILABLE."""
        mock_mcp_client.enabled = False
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
        adapter = LongbridgeMCPToolAdapter(mock_mcp_client)
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is False
        assert result["error_code"] == "MCP_UNAVAILABLE"

    # === Output Compaction Tests ===

    def test_quote_compact_output(self, adapter, mock_mcp_client):
        """Quote output is compacted to essential fields only."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {
                "symbol": "AAPL",
                "last_price": 150.0,
                "change_ratio": 1.5,
                "volume": 1000000,
                "timestamp": "2024-01-01T09:00:00Z",
                "extra_field": "should_not_appear",
            }
        }
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is True
        data = result["data"]
        assert "symbol" in data
        assert "price" in data
        assert "change_pct" in data
        assert "extra_field" not in data

    def test_candlesticks_stats_use_full_series(self, adapter, mock_mcp_client):
        """Candlestick summary stats should use the full series, not a truncated sample."""
        items = [{"open": 100 + i, "close": 105 + i, "high": 110 + i, "low": 99 + i, "timestamp": f"2024-01-{i:02d}"} for i in range(1, 51)]
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": items}}
        result = adapter.call("history_candlesticks", {"symbol": "AAPL", "count": 50})
        assert result["ok"] is True
        data = result["data"]
        assert data["sample_points"] == 50
        assert data["return_pct"] == 53.47

    def test_candlesticks_keep_engine_payload_outside_llm_data(self, adapter, mock_mcp_client):
        """Raw OHLCV is retained for deterministic engines without bloating LLM-facing data."""
        items = [
            {"open": 100, "close": 105, "high": 110, "low": 99, "volume": 1000, "timestamp": "2024-01-01"},
            {"open": 105, "close": 106, "high": 108, "low": 104, "volume": 1200, "timestamp": "2024-01-02"},
        ]
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": items}}

        result = adapter.call("candlesticks", {"symbol": "AAPL.US", "count": 2})

        assert result["ok"] is True
        assert "items" not in result["data"]
        assert "candles" not in result["data"]
        assert result["engine_payload"]["symbol"] == "AAPL.US"
        assert result["engine_payload"]["kind"] == "ohlcv_candles"
        assert result["engine_payload"]["candles"][0] == {
            "timestamp": "2024-01-01",
            "open": 100,
            "high": 110,
            "low": 99,
            "close": 105,
            "volume": 1000,
        }

    def test_news_search_limited_to_15_items(self, adapter, mock_mcp_client):
        """News search output is limited to 15 compact items."""
        items = [{"title": f"News {i}", "published_at": "2024-01-01", "source": "WSJ", "summary": "Summary", "sentiment": "POSITIVE"} for i in range(20)]
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": items}}
        result = adapter.call("news_search", {"symbol": "AAPL"})
        assert result["ok"] is True
        data = result["data"]
        assert len(data["items"]) <= 15

    def test_news_search_timestamp_zero_is_unknown(self, adapter, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": [{"title": "News", "timestamp": 0, "source": "WSJ"}]}}
        result = adapter.call("news_search", {"symbol": "AAPL"})
        assert result["data"]["items"][0]["published_at"] is None

    def test_news_search_valid_timestamp_is_converted(self, adapter, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": [{"title": "News", "timestamp": 1714521600, "source": "WSJ"}]}}
        result = adapter.call("news_search", {"symbol": "AAPL"})
        assert result["data"]["items"][0]["published_at"].startswith("2024-05-01")

    def test_news_search_iso_time_is_preserved(self, adapter, mock_mcp_client):
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": [{"title": "News", "published_at": "2026-05-01T12:30:00Z", "source": "WSJ"}]}}
        result = adapter.call("news_search", {"symbol": "AAPL"})
        assert result["data"]["items"][0]["published_at"] == "2026-05-01T12:30:00"

    def test_company_compact_output(self, adapter, mock_mcp_client):
        """Company output is compacted to essential fields."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {
                "name": "Apple Inc.",
                "industry": "Technology",
                "market_cap": 3000000000000,
                "extra_field": "should_not_appear",
            }
        }
        result = adapter.call("company", {"symbol": "AAPL"})
        assert result["ok"] is True
        data = result["data"]
        assert "name" in data
        assert "industry" in data
        assert "market_cap" in data
        assert "extra_field" not in data

    def test_valuation_compact_output(self, adapter, mock_mcp_client):
        """Valuation output is compacted to essential fields."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {
                "metrics": {
                    "pe": {
                        "low": "25.0",
                        "median": "30.0",
                        "high": "40.0",
                        "desc": "当前市盈率 28.5",
                        "list": [
                            {"timestamp": "2025-05-01", "value": "27.0"},
                            {"timestamp": "2025-05-15", "value": "28.5"},
                        ],
                    },
                    "pb": {
                        "list": [{"timestamp": "2025-05-15", "value": "5.2"}],
                    },
                    "ps": {
                        "list": [{"timestamp": "2025-05-15", "value": "7.5"}],
                    },
                },
                "range": 1,
            }
        }
        result = adapter.call("valuation", {"symbol": "AAPL"})
        assert result["ok"] is True
        data = result["data"]
        assert data["pe_ttm"] == 28.5
        assert data["pb_ratio"] == 5.2
        assert data["ps_ttm"] == 7.5
        assert "pe_range" in data

    def test_industry_peers_limited_to_8(self, adapter, mock_mcp_client):
        """Industry peers output is limited to 8 items."""
        items = [{"symbol": f"SYM{i}", "name": f"Company {i}", "market_cap": 1000000, "pe": 20, "ps": 5, "change_ratio": 1.5} for i in range(15)]
        mock_mcp_client.call_tool.return_value = {"ok": True, "data": {"items": items}}
        result = adapter.call("industry_peers", {"symbol": "AAPL"})
        assert result["ok"] is True
        data = result["data"]
        assert len(data["peers"]) <= 8

    # === Security Tests ===

    def test_no_tokens_in_result(self, adapter, mock_mcp_client):
        """Response should not contain sensitive tokens/headers."""
        mock_mcp_client.call_tool.return_value = {
            "ok": True,
            "data": {
                "symbol": "AAPL",
                "last_price": 150.0,
                "authorization": "Bearer secret_token_12345",
                "x-api-key": "sk-secret-key",
            }
        }
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is True
        import json
        result_str = json.dumps(result)
        assert "secret_token" not in result_str
        assert "sk-secret-key" not in result_str

    def test_error_result_does_not_leak_sensitive_data(self, adapter, mock_mcp_client):
        """Error responses should not leak sensitive data."""
        mock_mcp_client.call_tool.return_value = {
            "ok": False,
            "error_code": "MCP_UNKNOWN_ERROR",
            "message": "Access denied",
            "data_limitations": ["Rate limit exceeded"],
        }
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is False
        import json
        result_str = json.dumps(result)
        # Error result should not contain API keys or tokens even on failure
        assert "sk-" not in result_str
        assert "token" not in result_str.lower() or "data_limitations" in result_str

    # === Fallback Behavior Tests ===

    def test_mcp_call_returns_error_on_failure(self, adapter, mock_mcp_client):
        """When MCP call fails, error code and message are forwarded."""
        mock_mcp_client.call_tool.return_value = {
            "ok": False,
            "error_code": "TOOL_NOT_FOUND",
            "message": "Quote tool not found",
            "data_limitations": ["Service unavailable"],
        }
        result = adapter.call("quote", {"symbol": "AAPL"})
        assert result["ok"] is False
        assert result["error_code"] == "TOOL_NOT_FOUND"
        assert result["message"] == "Quote tool not found"
        assert result["data_limitations"] == ["Service unavailable"]

    def test_compact_function_for_unknown_tool_returns_raw(self, adapter, mock_mcp_client):
        """For unknown tools not in compaction list, raw data is returned."""
        # This is actually covered by the fact that _compact_tool_output
        # returns raw for unknown tools
        pass


class TestForbiddenToolsConstants:
    """Tests for ALLOWED and FORBIDDEN tool constants."""

    def test_submit_order_in_forbidden(self):
        from app.services.mcp.longbridge_mcp_tools import FORBIDDEN_LONGBRIDGE_MCP_TOOLS
        assert "submit_order" in FORBIDDEN_LONGBRIDGE_MCP_TOOLS

    def test_no_overlap_between_allowed_and_forbidden(self):
        from app.services.mcp.longbridge_mcp_tools import ALLOWED_LONGBRIDGE_MCP_TOOLS, FORBIDDEN_LONGBRIDGE_MCP_TOOLS
        overlap = ALLOWED_LONGBRIDGE_MCP_TOOLS & FORBIDDEN_LONGBRIDGE_MCP_TOOLS
        assert len(overlap) == 0, f"Tools in both allow and forbid lists: {overlap}"

    def test_all_forbidden_tools_are_strings(self):
        from app.services.mcp.longbridge_mcp_tools import FORBIDDEN_LONGBRIDGE_MCP_TOOLS
        for tool in FORBIDDEN_LONGBRIDGE_MCP_TOOLS:
            assert isinstance(tool, str), f"Non-string tool in forbidden list: {tool}"

    def test_all_allowed_tools_are_strings(self):
        from app.services.mcp.longbridge_mcp_tools import ALLOWED_LONGBRIDGE_MCP_TOOLS
        for tool in ALLOWED_LONGBRIDGE_MCP_TOOLS:
            assert isinstance(tool, str), f"Non-string tool in allowed list: {tool}"


def test_mcp_tool_catalog_classifies_public_readonly_tools():
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter, classify_mcp_tool

    assert classify_mcp_tool({"name": "valuation", "description": "public valuation metrics"}) == "public_market_readonly"
    assert classify_mcp_tool({"name": "news_search", "description": "market news"}) == "public_market_readonly"
    assert classify_mcp_tool({"name": "business_segments"}) == "public_market_readonly"
    assert classify_mcp_tool({"name": "financial_statement"}) == "public_market_readonly"
    assert classify_mcp_tool({"name": "trading_days", "description": "market trading calendar"}) == "public_market_readonly"

    client = MagicMock()
    client.enabled = True
    client.list_tools.return_value = {
        "ok": True,
        "data": {"tools": [{"name": "valuation"}, {"name": "company"}, {"name": "financial_statement"}, {"name": "stock_positions"}]},
    }
    adapter = LongbridgeMCPToolAdapter(client)
    catalog = adapter.get_tool_catalog()

    assert "valuation" in catalog["public_market_readonly"]
    assert "company" in catalog["public_market_readonly"]
    assert "financial_statement" in catalog["public_market_readonly"]
    assert "stock_positions" in catalog["blocked"]


def test_mcp_tool_catalog_blocks_account_and_trading_tools():
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter, classify_mcp_tool

    assert classify_mcp_tool({"name": "account_balance"}) == "account_private"
    assert classify_mcp_tool({"name": "submit_order"}) == "trading_write"

    client = MagicMock()
    client.enabled = True
    client.call_tool.return_value = {"ok": True, "data": {}}
    client.list_tools.return_value = {
        "ok": True,
        "data": {"tools": [{"name": "submit_order"}, {"name": "account_balance"}, {"name": "quote"}]},
    }
    adapter = LongbridgeMCPToolAdapter(client)

    assert adapter.call("submit_order")["error_code"] == "MCP_TOOL_FORBIDDEN"
    assert adapter.call("account_balance")["error_code"] == "MCP_TOOL_FORBIDDEN"
    assert adapter.call("quote", {"symbol": "AAPL.US"})["ok"] is True


def test_finance_calendar_uses_official_category_date_schema():
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

    client = MagicMock()
    client.enabled = True
    client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "finance_calendar"}]}}
    client.call_tool.return_value = {"ok": True, "data": []}
    adapter = LongbridgeMCPToolAdapter(client)

    adapter.call("finance_calendar", {"symbol": "ORCL.US"})

    called_args = client.call_tool.call_args.args[1]
    assert called_args["category"] == "report"
    assert "start" in called_args
    assert "end" in called_args
    assert "symbol" not in called_args


def test_static_info_uses_official_symbols_array_schema():
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

    client = MagicMock()
    client.enabled = True
    client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "static_info"}]}}
    client.call_tool.return_value = {"ok": True, "data": [{"symbol": "ORCL.US", "name_en": "Oracle"}]}
    adapter = LongbridgeMCPToolAdapter(client)

    result = adapter.call("static_info", {"symbol": "ORCL.US"})

    assert result["ok"] is True
    assert client.call_tool.call_args.args[1] == {"symbols": ["ORCL.US"]}


def test_parse_market_cap_industry_forward_pe_from_mcp_response():
    from app.services.mcp.longbridge_mcp_tools import _compact_business_segments, _compact_company, _compact_institution_rating, _compact_valuation

    company = _compact_company({
        "company_name": "Apple Inc.",
        "sector_name": "Technology",
        "industry_name": "Consumer Electronics",
        "total_market_value": 3000000000000,
        "business_segments": [{"name": "iPhone", "revenue_pct": 50}],
    })
    valuation = _compact_valuation({
        "metrics": {
            "pe": {"list": [{"value": "28.5"}]},
            "ps": {"list": [{"value": "7.5"}]},
        },
        "forward_pe": "24.2",
    })

    assert company["market_cap"] == 3000000000000
    assert company["industry"] == "Consumer Electronics"
    assert company["business_segments"][0]["name"] == "iPhone"
    assert valuation["pe_ttm"] == 28.5
    assert valuation["forward_pe"] == 24.2

    static_info = _compact_company([{
        "symbol": "ORCL.US",
        "name_en": "Oracle",
        "total_shares": 2876046000,
        "eps": "7.57",
    }])
    segments = _compact_business_segments({
        "report_txt": "2026.Q3",
        "business": [{"name": "Cloud and software", "percent": "87.45", "value": "15033000000"}],
    })
    rating = _compact_institution_rating({
        "analyst": {"industry_name": "系统软件", "industry_rank": 6, "industry_total": 45},
        "instratings": {"recommend": "buy", "target": "244.02513", "updated_at": "2026 年 5 月 20 日"},
    })

    assert static_info["name"] == "Oracle"
    assert static_info["total_shares"] == 2876046000
    assert static_info["eps_forward"] == "7.57"
    assert segments["segments"][0]["name"] == "Cloud and software"
    assert segments["segments"][0]["revenue_pct"] == "87.45"
    assert rating["consensus"] == "buy"
    assert rating["target_price"] == "244.02513"
    assert rating["industry"] == "系统软件"


def test_missing_field_reports_tool_and_field_level_reason():
    from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

    client = MagicMock()
    client.enabled = True
    client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "valuation"}]}}
    client.call_tool.return_value = {"ok": True, "data": {"metrics": {"pe": {"list": [{"value": "28.5"}]}}}}
    adapter = LongbridgeMCPToolAdapter(client)

    result = adapter.call("valuation", {"symbol": "AAPL.US"})
    missing = result["tool_call"]["missing_fields"]

    # pe_range is expected but pe_data has no low/median/high keys directly
    # pe_ttm should be present (extracted from list), so it should NOT be missing
    missing_field_names = [item["field_name"] for item in missing]
    assert "pe_ttm" not in missing_field_names  # successfully extracted
    # forward_pe is NOT expected for valuation tool anymore
    assert "forward_pe" not in missing_field_names
    # All missing entries should reference the valuation tool
    for item in missing:
        assert item["tool_name"] == "valuation"
        assert item["request_args"]["symbol"] == "AAPL.US"
        assert item["success"] is True
        assert item["empty_result"] is False


class TestIndustryPeersMapping:
    """Tests for industry_peers → industry_valuation mapping."""

    def test_industry_peers_maps_to_industry_valuation_first(self):
        """When industry_valuation is in catalog, industry_peers should map to it."""
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        available = {"industry_valuation", "industry_peers", "quote"}
        name, args = _map_tool_call("industry_peers", {"symbol": "CRWV.US"}, available_tools=available)

        assert name == "industry_valuation"
        assert args == {"symbol": "CRWV.US"}

    def test_industry_peers_falls_back_to_industry_peers(self):
        """When only industry_peers is in catalog, use it."""
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        available = {"industry_peers", "quote"}
        name, args = _map_tool_call("industry_peers", {"symbol": "CRWV.US"}, available_tools=available)

        assert name == "industry_peers"
        assert args == {"symbol": "CRWV.US"}

    def test_industry_peers_defaults_to_valuation_when_no_catalog(self):
        """When available_tools is None, default to industry_valuation."""
        from app.services.mcp.longbridge_mcp_tools import _map_tool_call

        name, args = _map_tool_call("industry_peers", {"symbol": "CRWV.US"}, available_tools=None)

        assert name == "industry_valuation"


class TestCompactIndustryValuation:
    """Tests for _compact_industry_peers with industry_valuation format."""

    def test_compact_industry_valuation_list_to_peers(self):
        """industry_valuation format with 'list' key should compact to peers."""
        from app.services.mcp.longbridge_mcp_tools import _compact_industry_peers

        raw = {
            "list": [
                {"symbol": "EQIX.US", "name": "Equinix", "market_value": 75000000000, "pe": 85.2, "pb": 6.1, "ps": 10.5},
                {"symbol": "DLR.US", "name": "Digital Realty", "market_value": 45000000000, "pe": 42.1, "pb": 3.2, "ps": 8.3},
                {"symbol": "AMT.US", "name": "American Tower", "market_value": 100000000000, "pe": 55.0, "pb": 12.0, "ps": 12.0},
            ]
        }
        result = _compact_industry_peers(raw)

        assert result["total_returned"] == 3
        assert len(result["peers"]) == 3
        assert result["peers"][0]["symbol"] == "EQIX.US"
        assert result["peers"][0]["market_cap"] == 75000000000
        assert result["peers"][0]["pe"] == 85.2
        assert result["peers"][0]["pb"] == 6.1
        assert result["peers"][0]["ps"] == 10.5

    def test_compact_industry_valuation_items_format(self):
        """industry_peers format with 'items' key should also work."""
        from app.services.mcp.longbridge_mcp_tools import _compact_industry_peers

        raw = {
            "items": [
                {"symbol": "EQIX.US", "name": "Equinix", "market_cap": 75000000000, "pe": 85.2},
            ]
        }
        result = _compact_industry_peers(raw)

        assert result["total_returned"] == 1
        assert result["peers"][0]["symbol"] == "EQIX.US"

    def test_compact_industry_peers_raw_list(self):
        """Raw list input should also work."""
        from app.services.mcp.longbridge_mcp_tools import _compact_industry_peers

        raw = [
            {"symbol": "EQIX.US", "name": "Equinix"},
        ]
        result = _compact_industry_peers(raw)

        assert result["total_returned"] == 1

    def test_crwv_like_industry_valuation_not_empty(self):
        """CRWV-like industry_valuation returning peers should not be empty."""
        from app.services.mcp.longbridge_mcp_tools import _compact_industry_peers

        raw = {
            "list": [
                {"symbol": "EQIX.US", "name": "Equinix Inc", "market_value": 75000000000, "pe": 85.2, "pb": 6.1, "ps": 10.5, "change_ratio": 2.1},
                {"symbol": "DLR.US", "name": "Digital Realty Trust", "market_value": 45000000000, "pe": 42.1, "pb": 3.2, "ps": 8.3, "change_ratio": -0.5},
                {"symbol": "CRWV.US", "name": "CoreWeave Inc", "market_value": 30000000000, "pe": -35.5, "pb": 15.0, "ps": 25.0, "change_ratio": 5.0},
            ]
        }
        result = _compact_industry_peers(raw)

        assert result["total_returned"] == 3
        assert len(result["peers"]) == 3
        # Even though CRWV.US is in the list, peers should not be empty
        assert result["peers"]


class TestExpectedFieldsByToolSemantics:
    """Tests that EXPECTED_FIELDS_BY_TOOL only declares fields the tool actually returns."""

    def test_company_expected_fields_do_not_include_sector_industry(self):
        from app.services.mcp.longbridge_mcp_tools import EXPECTED_FIELDS_BY_TOOL
        expected = EXPECTED_FIELDS_BY_TOOL["company"]
        assert "sector" not in expected
        assert "industry" not in expected
        assert "market_cap" not in expected
        assert "business_segments" not in expected

    def test_static_info_expected_fields_do_not_include_industry_market_cap(self):
        from app.services.mcp.longbridge_mcp_tools import EXPECTED_FIELDS_BY_TOOL
        expected = EXPECTED_FIELDS_BY_TOOL["static_info"]
        assert "industry" not in expected
        assert "market_cap" not in expected

    def test_valuation_expected_fields_do_not_include_forward_pe(self):
        from app.services.mcp.longbridge_mcp_tools import EXPECTED_FIELDS_BY_TOOL
        expected = EXPECTED_FIELDS_BY_TOOL["valuation"]
        assert "forward_pe" not in expected
        assert "market_cap" not in expected
        assert "ps_ttm" not in expected

    def test_consensus_expected_fields_are_eps_revenue(self):
        from app.services.mcp.longbridge_mcp_tools import EXPECTED_FIELDS_BY_TOOL
        expected = EXPECTED_FIELDS_BY_TOOL["consensus"]
        assert "eps_forward" in expected
        assert "revenue_estimate" in expected
        assert "consensus" not in expected
        assert "target_price" not in expected

    def test_institution_rating_expected_fields_include_industry(self):
        from app.services.mcp.longbridge_mcp_tools import EXPECTED_FIELDS_BY_TOOL
        expected = EXPECTED_FIELDS_BY_TOOL["institution_rating"]
        assert "industry" in expected
        assert "consensus" in expected
        assert "target_price" in expected


class TestMissingFieldsDiagnosticNoise:
    """Tests that tool diagnostics do not flag fields the tool is not responsible for."""

    def test_company_does_not_flag_sector_industry_missing(self):
        """Company tool returning only name/description should not flag sector/industry."""
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

        client = MagicMock()
        client.enabled = True
        client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "company"}]}}
        client.call_tool.return_value = {
            "ok": True,
            "data": {"company_name": "CoreWeave Inc", "profile": "Cloud infrastructure provider"},
        }
        adapter = LongbridgeMCPToolAdapter(client)

        result = adapter.call("company", {"symbol": "CRWV.US"})
        missing = result["tool_call"]["missing_fields"]
        missing_field_names = [m["field_name"] for m in missing]

        assert "sector" not in missing_field_names
        assert "industry" not in missing_field_names
        assert "market_cap" not in missing_field_names
        assert "business_segments" not in missing_field_names

    def test_static_info_does_not_flag_industry_market_cap_missing(self):
        """Static_info returning name/total_shares/eps should not flag industry/market_cap."""
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

        client = MagicMock()
        client.enabled = True
        client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "static_info"}]}}
        client.call_tool.return_value = {
            "ok": True,
            "data": {"name_en": "CoreWeave", "total_shares": 500000000, "eps": "-2.588"},
        }
        adapter = LongbridgeMCPToolAdapter(client)

        result = adapter.call("static_info", {"symbol": "CRWV.US"})
        missing = result["tool_call"]["missing_fields"]
        missing_field_names = [m["field_name"] for m in missing]

        assert "industry" not in missing_field_names
        assert "market_cap" not in missing_field_names

    def test_valuation_does_not_flag_forward_pe_market_cap_missing(self):
        """Valuation returning pe_ttm should not flag forward_pe/market_cap."""
        from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter

        client = MagicMock()
        client.enabled = True
        client.list_tools.return_value = {"ok": True, "data": {"tools": [{"name": "valuation"}]}}
        client.call_tool.return_value = {
            "ok": True,
            "data": {"metrics": {"pe": {"list": [{"value": "-35.5"}]}}},
        }
        adapter = LongbridgeMCPToolAdapter(client)

        result = adapter.call("valuation", {"symbol": "CRWV.US"})
        missing = result["tool_call"]["missing_fields"]
        missing_field_names = [m["field_name"] for m in missing]

        assert "forward_pe" not in missing_field_names
        assert "market_cap" not in missing_field_names
        assert "ps_ttm" not in missing_field_names
