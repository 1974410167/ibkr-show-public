"""Shared trace utilities for LangGraph nodes."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_node_trace(node_name: str) -> dict:
    return {
        "node_name": node_name,
        "started_at": now_iso(),
        "finished_at": None,
        "elapsed_ms": 0,
        "status": "running",
        "fallback_used": False,
        "fallback_reason": None,
        "error": None,
        "tools_called": [],
        "rounds_used": 0,
        "data_limitations": [],
        "_start_perf": time.perf_counter(),
    }


def finish_node_trace(trace: dict, status: str = "success", **extra) -> dict:
    start_perf = trace.get("_start_perf")
    if start_perf is None:
        elapsed = int(trace.get("elapsed_ms") or 0)
    else:
        elapsed = int((time.perf_counter() - start_perf) * 1000)
    result = {
        **trace,
        "finished_at": now_iso(),
        "elapsed_ms": elapsed,
        "status": status,
        "_start_perf": None,
    }
    result.update(extra)
    return result


def fallback_node_trace(node_name: str, error: Exception | str, **extra) -> dict:
    error_msg = str(error)[:200]
    return {
        "node_name": node_name,
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "elapsed_ms": 0,
        "status": "fallback",
        "fallback_used": True,
        "fallback_reason": error_msg,
        "error": error_msg,
        "tools_called": [],
        "rounds_used": 0,
        "data_limitations": [f"node_failed: {error_msg}"],
        **extra,
    }


def append_node_trace(state: dict, trace: dict) -> None:
    traces = state.get("node_traces") or []
    traces.append(trace)
    state["node_traces"] = traces


def summarize_node_traces(traces: list[dict]) -> dict:
    total_ms = sum(t.get("elapsed_ms", 0) for t in traces)
    fallback_count = sum(1 for t in traces if t.get("fallback_used"))
    failed = [t for t in traces if t.get("status") == "failed"]
    return {
        "total_elapsed_ms": total_ms,
        "node_count": len(traces),
        "fallback_count": fallback_count,
        "failed_count": len(failed),
        "nodes": [
            {
                "node_name": t.get("node_name"),
                "status": t.get("status"),
                "elapsed_ms": t.get("elapsed_ms", 0),
                "fallback_used": t.get("fallback_used", False),
            }
            for t in traces
        ],
    }
