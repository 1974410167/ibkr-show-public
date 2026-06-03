#!/usr/bin/env python3
"""Measure input token cost of MCP tool schemas passed to trade decision LLMs.

Reads .env from project root, initializes the real MCP adapter, builds the
tool list via _build_mcp_tools(), converts to OpenAI tools format, and reports
token estimates. Does NOT call any LLM or real MCP tool.

Usage:
    cd /root/ibkr_show
    cd ibkr_show_backend && ../.venv/bin/python ../scripts/measure_trade_decision_tool_tokens.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env from project root (simple KEY=VALUE parser, no dependency)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if not all(c.isalnum() or c == "_" for c in key):
            continue
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


_load_env(_ENV_FILE)

# Ensure backend package is importable
_BACKEND_DIR = _PROJECT_ROOT / "ibkr_show_backend"
sys.path.insert(0, str(_BACKEND_DIR))

# ---------------------------------------------------------------------------
# Imports (after sys.path fix)
# ---------------------------------------------------------------------------
from app.services.mcp.longbridge_mcp_client import (  # noqa: E402
    LongbridgeMCPClient,
    get_longbridge_mcp_config,
)
from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter  # noqa: E402
from app.services.trade_decision_sub_agents import (  # noqa: E402
    MarketTrendSubAgent,
    FundamentalValuationSubAgent,
    EventCatalystSubAgent,
    _build_mcp_tools,
)

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------
try:
    import tiktoken

    _ENC_CL100K = tiktoken.get_encoding("cl100k_base")
    _ENC_O200K = tiktoken.get_encoding("o200k_base")

    def _count_tokens(text: str, enc) -> int:
        return len(enc.encode(text))

    _HAS_TIKTOKEN = True
except Exception:
    _HAS_TIKTOKEN = False
    _ENC_CL100K = None
    _ENC_O200K = None

    def _count_tokens(text: str, enc) -> int:  # type: ignore[misc]
        return 0


def _compact_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _estimate_tokens_approx(text: str, divisor: float = 3.5) -> int:
    return int(len(text) / divisor)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Trade Decision MCP Tool Token Report")
    print("=" * 60)
    print()

    # --- MCP config ---
    config = get_longbridge_mcp_config()
    mcp_enabled = config.enabled
    endpoint = config.endpoint
    print(f"MCP enabled: {mcp_enabled}")
    print(f"MCP endpoint: {endpoint}")
    print()

    # --- Build adapter (pass None client if MCP disabled, adapter handles it) ---
    client: LongbridgeMCPClient | None = None
    if mcp_enabled:
        client = LongbridgeMCPClient(config=config)
    adapter = LongbridgeMCPToolAdapter(client)

    # --- Catalog info ---
    catalog = adapter.get_tool_catalog()
    catalog_source = catalog.get("source", "unknown")
    public_tools_list = catalog.get("public_market_readonly") or []
    blocked_tools_list = catalog.get("blocked") or []
    print(f"MCP catalog source: {catalog_source}")
    print(f"public_market_readonly_count: {len(public_tools_list)}")
    print(f"blocked_count: {len(blocked_tools_list)}")
    if catalog.get("list_error"):
        print(f"catalog list_error: {catalog['list_error']}")
    print()

    # --- Build tools ---
    tools = _build_mcp_tools(adapter)
    openai_tools = [t.to_openai_tool() for t in tools]
    tool_names = [t.name for t in tools]

    print(f"Total exposed agent tools: {len(tools)}")
    print(f"Tool names: {', '.join(tool_names)}")
    print()

    # --- Per-tool measurement ---
    per_tool: list[dict] = []
    for tool, oai_tool in zip(tools, openai_tools):
        schema_json = _compact_json(oai_tool)
        chars = len(schema_json)
        bytes_utf8 = len(schema_json.encode("utf-8"))
        tokens_cl = _count_tokens(schema_json, _ENC_CL100K) if _HAS_TIKTOKEN else _estimate_tokens_approx(schema_json, 3.5)
        tokens_o2 = _count_tokens(schema_json, _ENC_O200K) if _HAS_TIKTOKEN else _estimate_tokens_approx(schema_json, 4.0)
        per_tool.append({
            "name": tool.name,
            "chars": chars,
            "bytes_utf8": bytes_utf8,
            "tokens_cl100k": tokens_cl,
            "tokens_o200k": tokens_o2,
        })

    # --- Totals ---
    all_tools_json = _compact_json(openai_tools)
    total_chars = len(all_tools_json)
    total_bytes = len(all_tools_json.encode("utf-8"))
    total_cl = _count_tokens(all_tools_json, _ENC_CL100K) if _HAS_TIKTOKEN else _estimate_tokens_approx(all_tools_json, 3.5)
    total_o2 = _count_tokens(all_tools_json, _ENC_O200K) if _HAS_TIKTOKEN else _estimate_tokens_approx(all_tools_json, 4.0)

    method = "tiktoken" if _HAS_TIKTOKEN else "approximate (len/3.5 and len/4.0)"
    print(f"Token counting method: {method}")
    print()
    print("Total tools schema:")
    print(f"  chars: {total_chars}")
    print(f"  bytes_utf8: {total_bytes}")
    print(f"  tokens_cl100k: {total_cl}")
    print(f"  tokens_o200k: {total_o2}")
    print()

    # --- Per sub-agent info ---
    print("Per sub-agent exposed tools:")
    for agent_name, cls in [
        ("market_trend", MarketTrendSubAgent),
        ("fundamental_valuation", FundamentalValuationSubAgent),
        ("event_catalyst", EventCatalystSubAgent),
    ]:
        print(f"  {agent_name}: {len(tools)} tools, same shared toolset")

    print()
    print("Initial tool calls (symbol=AAPL.US):")
    dummy_llm = type("L", (), {})()  # mock, only need _get_initial_tool_calls
    for agent_name, cls in [
        ("market_trend", MarketTrendSubAgent),
        ("fundamental_valuation", FundamentalValuationSubAgent),
        ("event_catalyst", EventCatalystSubAgent),
    ]:
        # _get_initial_tool_calls is an instance method, create a minimal instance
        agent = cls.__new__(cls)
        calls = agent._get_initial_tool_calls("AAPL.US")
        call_names = [c["name"] for c in calls]
        print(f"  {agent_name}: {len(calls)} calls -> {', '.join(call_names)}")

    print()

    # --- Top 20 largest schemas ---
    per_tool.sort(key=lambda x: x["tokens_cl100k"], reverse=True)
    print("Top 20 largest tool schemas:")
    for i, item in enumerate(per_tool[:20], 1):
        print(f"  {i:2d}. {item['name']:<30s} chars={item['chars']:>5d}  tokens_cl100k={item['tokens_cl100k']:>5d}  tokens_o200k={item['tokens_o200k']:>5d}")

    print()

    # --- Optimization hint ---
    print("Analysis:")
    print(f"  All 3 sub-agents share the same {len(tools)}-tool toolset.")
    print(f"  Each sub-agent LLM call sends ~{total_cl} input tokens (cl100k) for tool schemas.")
    if total_cl > 3000:
        print("  This is a significant chunk. Per-agent tool whitelisting could save ~{:.0f}% tokens.".format(
            (1 - max(len(tools) - 5, 5) / len(tools)) * 100
        ))
    else:
        print("  Token cost is modest; per-agent whitelisting has limited benefit.")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
