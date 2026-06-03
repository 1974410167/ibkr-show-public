from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from app.services.llm_call_metrics_repository import LLMCallMetricsRepository
from app.services.llm_observability import LLMCallResult, response_format_type

logger = logging.getLogger(__name__)


class LLMCallMetricsService:
    def __init__(self, repository: LLMCallMetricsRepository) -> None:
        self.repository = repository

    def record_call_result(
        self,
        result: LLMCallResult,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        metadata = result.call_metadata
        usage = metadata.usage
        document = {
            "call_id": metadata.call_id,
            "run_id": run_id,
            "session_id": session_id,
            "provider_id": metadata.provider_id,
            "provider_name": metadata.provider_name,
            "provider_type": metadata.provider_type,
            "model": metadata.model,
            "call_type": metadata.call_type,
            "agent_name": metadata.agent_name,
            "node_name": metadata.node_name,
            "prompt_key": metadata.prompt_key,
            "prompt_version": metadata.prompt_version,
            "prompt_hash": metadata.prompt_hash,
            "prompt_source": metadata.prompt_source,
            "response_format_type": response_format_type(metadata.response_format),
            "tool_calling": metadata.tool_calling,
            "tool_count": metadata.tool_count,
            "temperature": metadata.temperature,
            "max_tokens": metadata.max_tokens,
            "latency_ms": metadata.latency_ms,
            "ok": metadata.ok,
            "error_code": metadata.error_code,
            "error_message": _truncate(metadata.error_message, 500),
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cached_tokens": usage.cached_tokens,
            "estimated_cost": metadata.estimated_cost,
            "created_at": metadata.created_at,
        }
        try:
            self.repository.create_metric(document)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to record LLM call metric: %s", exc)

    def list_calls(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        prompt_key: str | None = None,
        model: str | None = None,
        ok: bool | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        items = self.repository.list_recent(
            hours=hours,
            agent_name=agent_name,
            prompt_key=prompt_key,
            model=model,
            ok=ok,
            limit=limit,
        )
        return {"items": items, "summary": self._summary(items)}

    def get_call(self, call_id: str) -> dict | None:
        return self.repository.get_metric(call_id)

    def _summary(self, items: list[dict]) -> dict[str, Any]:
        count = len(items)
        latencies = [int(item.get("latency_ms") or 0) for item in items]
        costs = [float(item.get("estimated_cost") or 0) for item in items]
        ok_count = sum(1 for item in items if item.get("ok") is True)
        return {
            "call_count": count,
            "success_rate": (ok_count / count) if count else 0,
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in items),
            "total_estimated_cost": sum(costs),
            "avg_latency_ms": int(mean(latencies)) if latencies else 0,
            "p95_latency_ms": _percentile(latencies, 95),
            "by_model": _bucket(items, "model"),
            "by_agent": _bucket(items, "agent_name"),
            "by_prompt_key": _bucket(items, "prompt_key"),
        }


def _bucket(items: list[dict], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = buckets.setdefault(name, {"call_count": 0, "total_tokens": 0, "avg_latency_ms": 0})
        bucket["call_count"] += 1
        bucket["total_tokens"] += int(item.get("total_tokens") or 0)
        bucket["_latency_sum"] = bucket.get("_latency_sum", 0) + int(item.get("latency_ms") or 0)
    for bucket in buckets.values():
        bucket["avg_latency_ms"] = int(bucket["_latency_sum"] / bucket["call_count"]) if bucket["call_count"] else 0
        bucket.pop("_latency_sum", None)
    return buckets


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
    return int(ordered[index])


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."
