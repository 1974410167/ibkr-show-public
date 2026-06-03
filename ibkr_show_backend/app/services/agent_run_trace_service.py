from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from app.agents.agent_run_trace import AgentRunTrace, sanitize_trace_payload
from app.services.agent_run_trace_repository import AgentRunTraceRepository

logger = logging.getLogger(__name__)


class AgentRunTraceService:
    def __init__(self, repository: AgentRunTraceRepository) -> None:
        self.repository = repository

    def record_trace(self, trace: AgentRunTrace | dict) -> dict:
        payload = trace.to_dict() if isinstance(trace, AgentRunTrace) else sanitize_trace_payload(trace)
        document = self._prepare_document(payload)
        return self.repository.save_trace(document)

    def get_trace(self, run_id: str) -> dict | None:
        return self.repository.get_trace(run_id)

    def list_traces(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        final_status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        items = self.repository.list_traces(
            hours=hours,
            agent_name=agent_name,
            final_status=final_status,
            limit=limit,
        )
        return {"items": items, "summary": self.summary(items)}

    def summary(self, items: list[dict]) -> dict[str, Any]:
        count = len(items)
        status_counts = {
            "success": sum(1 for item in items if item.get("final_status") == "success"),
            "partial": sum(1 for item in items if item.get("final_status") == "partial"),
            "failed": sum(1 for item in items if item.get("final_status") == "failed"),
        }
        latencies = [int(item.get("latency_ms") or 0) for item in items]
        return {
            "run_count": count,
            "success_rate": status_counts["success"] / count if count else 0,
            "partial_rate": status_counts["partial"] / count if count else 0,
            "failure_rate": status_counts["failed"] / count if count else 0,
            "avg_latency_ms": int(mean(latencies)) if latencies else 0,
            "p95_latency_ms": _percentile(latencies, 95),
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in items),
            "total_estimated_cost": sum(float(item.get("estimated_cost") or 0) for item in items),
            "by_agent": _bucket(items, "agent_name"),
            "by_status": _bucket(items, "final_status"),
        }

    def _prepare_document(self, payload: dict) -> dict:
        prompt_metadata = payload.get("prompt_metadata") if isinstance(payload.get("prompt_metadata"), dict) else {}
        llm_calls = payload.get("llm_calls") if isinstance(payload.get("llm_calls"), list) else []
        tool_calls = payload.get("tool_calls") if isinstance(payload.get("tool_calls"), list) else []
        prompt_keys = sorted({str(key) for key in prompt_metadata.keys()} | {str(call.get("prompt_key")) for call in llm_calls if call.get("prompt_key")})
        prompt_versions = sorted({str(value.get("version")) for value in prompt_metadata.values() if isinstance(value, dict) and value.get("version")})
        prompt_versions.extend(str(call.get("prompt_version")) for call in llm_calls if call.get("prompt_version") and str(call.get("prompt_version")) not in prompt_versions)
        prompt_hashes = sorted({str(value.get("content_hash")) for value in prompt_metadata.values() if isinstance(value, dict) and value.get("content_hash")})
        prompt_hashes.extend(str(call.get("prompt_hash")) for call in llm_calls if call.get("prompt_hash") and str(call.get("prompt_hash")) not in prompt_hashes)
        return {
            **payload,
            "prompt_keys": prompt_keys,
            "prompt_versions": prompt_versions,
            "prompt_hashes": prompt_hashes,
            "llm_call_count": len(llm_calls),
            "tool_call_count": len(tool_calls),
            "total_tokens": sum(int(call.get("total_tokens") or 0) for call in llm_calls),
            "estimated_cost": sum(float(call.get("estimated_cost") or 0) for call in llm_calls),
        }


def _bucket(items: list[dict], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = buckets.setdefault(name, {"run_count": 0, "avg_latency_ms": 0, "total_tokens": 0})
        bucket["run_count"] += 1
        bucket["total_tokens"] += int(item.get("total_tokens") or 0)
        bucket["_latency_sum"] = bucket.get("_latency_sum", 0) + int(item.get("latency_ms") or 0)
    for bucket in buckets.values():
        bucket["avg_latency_ms"] = int(bucket["_latency_sum"] / bucket["run_count"]) if bucket["run_count"] else 0
        bucket.pop("_latency_sum", None)
    return buckets


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return int(ordered[index])
