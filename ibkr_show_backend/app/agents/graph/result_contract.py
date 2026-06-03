"""Shared result-contract helpers for LangGraph agents."""

from __future__ import annotations

from typing import Any


def get_public_data_runtime_status(
    *,
    mcp_adapter: Any = None,
    mcp_enabled: bool | None = None,
    mcp_available: bool | None = None,
    longbridge_sdk_configured: bool = False,
    mcp_auth_status: str | None = None,
    mcp_last_error: str | None = None,
) -> dict[str, Any]:
    """Return a stable public-data runtime status used by health and metadata."""
    resolved_enabled = bool(mcp_enabled)
    resolved_available = bool(mcp_available)
    last_error = mcp_last_error or ""

    if mcp_adapter is not None:
        try:
            client = getattr(mcp_adapter, "client", None)
            if client is not None:
                resolved_enabled = bool(getattr(client, "enabled", resolved_enabled))
                if mcp_available is None:
                    health = client.health() if hasattr(client, "health") else {}
                    resolved_available = bool(health.get("ok")) if isinstance(health, dict) else resolved_enabled
                    if isinstance(health, dict):
                        mcp_auth_status = (
                            health.get("auth_mode")
                            or ("connected" if health.get("oauth_connected") else None)
                            or mcp_auth_status
                        )
                        last_error = str(
                            health.get("oauth_last_error")
                            or (health.get("message") if not health.get("ok") else "")
                            or last_error
                        )
                last_error = str(getattr(client, "last_error", "") or last_error)
        except Exception as exc:
            last_error = str(exc)[:200]
            resolved_available = False

    public_data_mode = "mcp" if resolved_available else "sdk_fallback" if longbridge_sdk_configured else "unavailable"
    return {
        "mcp_enabled": resolved_enabled,
        "mcp_available": resolved_available,
        "mcp_auth_status": mcp_auth_status or ("connected" if resolved_available else "unavailable"),
        "mcp_last_error": last_error,
        "sdk_fallback_available": bool(longbridge_sdk_configured),
        "longbridge_sdk_configured": bool(longbridge_sdk_configured),
        "public_data_mode": public_data_mode,
        "public_market_data_source": "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"
        if (resolved_available or longbridge_sdk_configured)
        else "unavailable",
    }


def build_agent_metadata(
    *,
    base_metadata: dict[str, Any] | None = None,
    agent_mode: str,
    graph_version: str,
    graph_schema_version: str | None = None,
    card_schema_version: str | None = None,
    account_data_source: str = "IBKR_ONLY",
    trade_data_source: str | None = None,
    position_data_source: str | None = None,
    public_market_data_source: str = "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
    public_data_status: dict[str, Any] | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    metadata = dict(base_metadata or {})
    metadata.update(
        {
            "agent_mode": agent_mode,
            "graph_version": graph_version,
            "account_data_source": account_data_source,
            "public_market_data_source": public_market_data_source,
            "fallback_used": bool(fallback_used),
            "fallback_reason": fallback_reason,
        }
    )
    if graph_schema_version:
        metadata["graph_schema_version"] = graph_schema_version
    if card_schema_version:
        metadata["card_schema_version"] = card_schema_version
    if trade_data_source:
        metadata["trade_data_source"] = trade_data_source
    if position_data_source:
        metadata["position_data_source"] = position_data_source
    if public_data_status:
        metadata.update(
            {
                "mcp_enabled": public_data_status.get("mcp_enabled", False),
                "mcp_available": public_data_status.get("mcp_available", False),
                "public_data_mode": public_data_status.get("public_data_mode", "unavailable"),
                "longbridge_sdk_configured": public_data_status.get("longbridge_sdk_configured", False),
            }
        )
        metadata["public_market_data_source"] = public_data_status.get(
            "public_market_data_source",
            metadata["public_market_data_source"],
        )
    return metadata


def build_run_trace_from_state(state: dict, persist_trace: dict | None = None) -> list[dict]:
    traces = list(state.get("node_traces") or [])
    if persist_trace is not None:
        traces.append(persist_trace)
    run_trace = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        item = {k: v for k, v in trace.items() if k != "_start_perf"}
        status = str(item.get("status") or "unknown")
        item.setdefault("event", f"node_{status}")
        run_trace.append(item)
    return run_trace


def assert_saved_document_contract(
    document: dict,
    *,
    required_nodes: list[str] | None = None,
    required_fields: list[str] | None = None,
) -> None:
    metadata = document.get("metadata") or {}
    if not metadata.get("agent_mode"):
        raise ValueError("metadata.agent_mode is required")
    if not metadata.get("graph_version"):
        raise ValueError("metadata.graph_version is required")
    for field in required_fields or []:
        if field not in document:
            raise ValueError(f"{field} is required")
    run_trace = document.get("run_trace")
    if run_trace is None:
        raise ValueError("run_trace is required")
    if not document.get("fallback_used") and not run_trace:
        raise ValueError("successful document must have non-empty run_trace")
    present_nodes = {item.get("node_name") for item in run_trace if isinstance(item, dict)}
    missing = [node for node in required_nodes or [] if node not in present_nodes]
    if missing:
        raise ValueError(f"run_trace missing required nodes: {', '.join(missing)}")
    if document.get("fallback_used") and not document.get("fallback_reason"):
        raise ValueError("fallback_reason is required when fallback_used=True")
    if document.get("fallback_used") and not document.get("data_limitations"):
        raise ValueError("data_limitations is required when fallback_used=True")


def classify_agent_status(document: dict) -> str:
    limitations = [str(item) for item in document.get("data_limitations") or []]
    reason = str(document.get("fallback_reason") or "")
    if any("graph completed without saving" in item or "graph_failed" in item for item in limitations) or "graph completed without saving" in reason:
        return "failed"
    if not document.get("run_trace"):
        return "failed"
    if document.get("fallback_used"):
        core_empty = not (document.get("card_pack") or document.get("evidence_pack") or document.get("subagent_card_pack"))
        return "failed" if core_empty else "completed_with_fallback"
    return "success"
