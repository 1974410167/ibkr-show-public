from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from app.services.account_copilot.monitoring_repository import AccountCopilotMonitoringRepository
from app.services.account_copilot.tool_reliability_service import percentile

logger = logging.getLogger(__name__)

SENSITIVE_TEXT = ("token", "api_key", "password", "cookie", "authorization", "secret", "prompt", "response")
_ALLOWED_SO_METADATA_KEYS = frozenset({"monitoring_recorded", "fallback_reason", "initial_error_code"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    lowered = text.lower()
    if any(key in lowered for key in ("token=", "api_key", "authorization:", "cookie:")):
        text = "[redacted]"
    return text[:limit]


def _safe_metadata(metadata: dict | None) -> dict:
    safe = {}
    for key, value in (metadata or {}).items():
        lower = str(key).lower()
        if any(sensitive in lower for sensitive in SENSITIVE_TEXT):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def tool_domain_for_name(tool_name: str) -> str | None:
    name = str(tool_name or "")
    if name.startswith("ibkr_"):
        return "ibkr"
    if name.startswith("longbridge_") or name == "longbridge_call_public_tool":
        return "longbridge"
    return None


def provider_for_name(name: str) -> str:
    lower = str(name or "").lower()
    for provider in ("xiaomi", "deepseek", "minimax", "openai"):
        if provider in lower:
            return provider
    return "unknown"


class AccountCopilotMonitoringService:
    def __init__(self, repository: AccountCopilotMonitoringRepository) -> None:
        self.repository = repository

    def record_tool_call(
        self,
        *,
        run_id: str | None,
        session_id: str | None,
        tool_name: str,
        ok: bool,
        task_id: str | None = None,
        agent_name: str | None = None,
        node_name: str | None = None,
        tool_domain: str | None = None,
        latency_ms: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        source: str = "runtime",
        metadata: dict | None = None,
        empty_result: bool | None = None,
        raw_ok: bool | None = None,
        compact_ok: bool | None = None,
        parsed_fields_count: int | None = None,
        missing_fields_count: int | None = None,
        fallback_used: bool | None = None,
    ) -> dict | None:
        domain = tool_domain if tool_domain in {"ibkr", "longbridge"} else tool_domain_for_name(tool_name)
        if domain not in {"ibkr", "longbridge"}:
            return None
        metric = {
            "run_id": run_id or "",
            "task_id": task_id or "",
            "session_id": session_id or "",
            "agent_name": agent_name or "account_copilot",
            "node_name": node_name or "unknown",
            "tool_domain": domain,
            "tool_name": tool_name,
            "ok": bool(ok),
            "latency_ms": max(0, int(latency_ms or 0)),
            "error_code": error_code,
            "error_message": _safe_text(error_message),
            "source": source,
            "empty_result": bool(empty_result) if empty_result is not None else False,
            "raw_ok": bool(raw_ok) if raw_ok is not None else None,
            "compact_ok": bool(compact_ok) if compact_ok is not None else None,
            "parsed_fields_count": max(0, int(parsed_fields_count or 0)),
            "missing_fields_count": max(0, int(missing_fields_count or 0)),
            "fallback_used": bool(fallback_used) if fallback_used is not None else False,
            "created_at": _utc_now_iso(),
            "metadata": _safe_metadata(metadata),
        }
        try:
            return self.repository.create_tool_metric(metric)
        except Exception as exc:
            logger.warning("Account Copilot tool metric write failed: %s", exc)
            return None

    def record_llm_call(
        self,
        *,
        run_id: str | None,
        session_id: str | None,
        provider: str,
        model: str,
        call_type: str = "unknown",
        ok: bool,
        task_id: str | None = None,
        agent_name: str | None = None,
        node_name: str | None = None,
        latency_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        metric = {
            "run_id": run_id or "",
            "task_id": task_id or "",
            "session_id": session_id or "",
            "agent_name": agent_name or "account_copilot",
            "node_name": node_name or "unknown",
            "provider": provider or "unknown",
            "model": model or "unknown",
            "call_type": call_type or "unknown",
            "ok": bool(ok),
            "latency_ms": max(0, int(latency_ms or 0)),
            "prompt_tokens": max(0, int(prompt_tokens or 0)),
            "completion_tokens": max(0, int(completion_tokens or 0)),
            "total_tokens": max(0, int(total_tokens or 0)),
            "error_code": error_code,
            "error_message": _safe_text(error_message),
            "created_at": _utc_now_iso(),
            "metadata": _safe_metadata(metadata),
        }
        try:
            return self.repository.create_llm_metric(metric)
        except Exception as exc:
            logger.warning("Account Copilot LLM metric write failed: %s", exc)
            return None

    def record_probe_results(self, *, probe_run_id: str | None, results: list[dict]) -> None:
        for result in results:
            if result.get("probe_type") != "invoke":
                continue
            if result.get("tool_domain") not in {"ibkr", "longbridge"}:
                continue
            if result.get("status") == "skipped":
                continue
            ok = result.get("status") == "pass"
            self.record_tool_call(
                run_id="",
                session_id="",
                tool_name=str(result.get("tool_name") or ""),
                tool_domain=str(result.get("tool_domain") or ""),
                ok=ok,
                latency_ms=int(result.get("latency_ms") or 0),
                error_code=result.get("error_code"),
                error_message=result.get("error_message"),
                source="runtime",
                metadata={
                    "probe_run_id": probe_run_id or result.get("probe_run_id") or "",
                    "probe_type": result.get("probe_type") or "",
                    "category": result.get("category") or "",
                },
                agent_name="probe",
                node_name=str(result.get("category") or "probe"),
                empty_result=bool(result.get("data_empty")),
                parsed_fields_count=0,
                missing_fields_count=len(result.get("data_limitations") or []),
            )

    def get_monitoring_overview(self, hours: int = 24, bucket: str = "1h") -> dict:
        tool_metrics = self.repository.query_tool_metrics(hours=hours, bucket=bucket)
        llm_metrics = self.repository.query_llm_metrics(hours=hours, bucket=bucket)
        failures = self.get_recent_failures(hours=hours, limit=50)["items"]
        llm_models = sorted({str(item.get("model") or "unknown") for item in llm_metrics})
        return {
            "range": {"hours": hours, "bucket": bucket},
            "ibkr": self._overview_for([item for item in tool_metrics if item.get("tool_domain") == "ibkr"], hours),
            "longbridge": self._overview_for([item for item in tool_metrics if item.get("tool_domain") == "longbridge"], hours),
            "llm": {**self._overview_for(llm_metrics, hours), "models": llm_models},
            "recent_failure_count": len(failures),
            "last_probe_at": self._latest_created_at(tool_metrics),
        }

    def get_tool_metrics(self, hours: int = 24, bucket: str = "1h") -> dict:
        metrics = self.repository.query_tool_metrics(hours=hours, bucket=bucket)
        return {
            "range": {"hours": hours, "bucket": bucket},
            "ibkr": {"series": self._series([item for item in metrics if item.get("tool_domain") == "ibkr"], bucket)},
            "longbridge": {"series": self._series([item for item in metrics if item.get("tool_domain") == "longbridge"], bucket)},
        }

    def get_llm_metrics(self, hours: int = 24, bucket: str = "1h") -> dict:
        metrics = self.repository.query_llm_metrics(hours=hours, bucket=bucket)
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for item in metrics:
            grouped[(str(item.get("model") or "unknown"), str(item.get("provider") or "unknown"))].append(item)
        return {
            "range": {"hours": hours, "bucket": bucket},
            "models": [
                {
                    "model": model,
                    "provider": provider,
                    "series": self._series(items, bucket, include_tokens=True),
                }
                for (model, provider), items in sorted(grouped.items())
            ],
        }

    def get_recent_failures(self, hours: int = 24, limit: int = 50) -> dict:
        failures = self.repository.query_recent_failures(hours=hours, limit=limit)
        items = []
        for item in failures.get("tool", []):
            items.append(
                {
                    "created_at": item.get("created_at") or "",
                    "kind": "tool",
                    "name": item.get("tool_name") or "",
                    "domain": item.get("tool_domain") or "unknown",
                    "error_code": item.get("error_code"),
                    "error_message": _safe_text(item.get("error_message")),
                    "latency_ms": int(item.get("latency_ms") or 0),
                    "run_id": item.get("run_id") or "",
                }
            )
        for item in failures.get("llm", []):
            items.append(
                {
                    "created_at": item.get("created_at") or "",
                    "kind": "llm",
                    "name": item.get("model") or "unknown",
                    "domain": "llm",
                    "error_code": item.get("error_code"),
                    "error_message": _safe_text(item.get("error_message")),
                    "latency_ms": int(item.get("latency_ms") or 0),
                    "run_id": item.get("run_id") or "",
                }
            )
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {"items": items[: max(1, int(limit))]}

    def get_recent_tool_calls(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        tool_domain: str | None = None,
        tool_name: str | None = None,
        include_debug: bool = False,
    ) -> dict:
        items = self.repository.query_recent_tool_calls(
            limit=limit,
            agent_name=agent_name,
            tool_domain=tool_domain,
            tool_name=tool_name,
        )
        normalized = [self._public_tool_call(item, include_debug=include_debug) for item in reversed(items)]
        return {"items": self._with_rolling_rates(normalized)}

    def record_structured_output_event(self, metadata: dict) -> dict | None:
        safe = _safe_metadata(metadata)
        metric = {
            "source": safe.get("source", "runtime"),
            "agent_name": safe.get("agent_name", ""),
            "node_name": safe.get("node_name", ""),
            "contract_name": safe.get("contract_name", ""),
            "run_id": safe.get("run_id", ""),
            "task_id": safe.get("task_id", ""),
            "session_id": safe.get("session_id", ""),
            "ok": bool(safe.get("ok") or safe.get("schema_validation_passed")),
            "schema_validation_passed": bool(safe.get("schema_validation_passed")),
            "repaired": bool(safe.get("repaired")),
            "repair_attempts": max(0, int(safe.get("repair_attempts") or 0)),
            "fallback_used": bool(safe.get("fallback_used")),
            "error_code": safe.get("error_code"),
            "error_message": _safe_text(safe.get("error_message")),
            "output_model_name": safe.get("output_model_name"),
            "raw_response_preview": _safe_text(safe.get("raw_response_preview"), limit=1000),
            "final_response_preview": _safe_text(safe.get("final_response_preview"), limit=1000),
            "created_at": _utc_now_iso(),
            "metadata": {
                k: v
                for k, v in safe.items()
                if k in _ALLOWED_SO_METADATA_KEYS and (isinstance(v, (str, int, float, bool)) or v is None)
            },
        }
        try:
            return self.repository.create_structured_output_metric(metric)
        except Exception as exc:
            logger.warning("Structured output metric write failed: %s", exc)
            return None

    def query_recent_structured_output_events(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        contract_name: str | None = None,
        node_name: str | None = None,
        ok: bool | None = None,
        repaired: bool | None = None,
        fallback_used: bool | None = None,
    ) -> dict:
        items = self.repository.query_recent_structured_output_events(
            limit=limit,
            agent_name=agent_name,
            contract_name=contract_name,
            node_name=node_name,
            ok=ok,
            repaired=repaired,
            fallback_used=fallback_used,
        )
        normalized = [self._public_structured_output_event(item) for item in reversed(items)]
        return {"items": self._with_so_rolling_rates(normalized)}

    def _public_structured_output_event(self, item: dict) -> dict:
        return {
            "id": item.get("id") or "",
            "created_at": item.get("created_at") or "",
            "source": item.get("source") or "runtime",
            "agent_name": item.get("agent_name") or "",
            "node_name": item.get("node_name") or "",
            "contract_name": item.get("contract_name") or "",
            "run_id": item.get("run_id") or "",
            "task_id": item.get("task_id") or "",
            "session_id": item.get("session_id") or "",
            "ok": item.get("ok") is True,
            "schema_validation_passed": item.get("schema_validation_passed") is True,
            "repaired": item.get("repaired") is True,
            "repair_attempts": int(item.get("repair_attempts") or 0),
            "fallback_used": item.get("fallback_used") is True,
            "error_code": item.get("error_code"),
            "error_message": _safe_text(item.get("error_message")),
            "output_model_name": item.get("output_model_name") or "",
        }

    def _with_so_rolling_rates(self, items: list[dict]) -> list[dict]:
        for index, item in enumerate(items):
            window = items[max(0, index - 9): index + 1]
            size = len(window)
            ok_count = sum(1 for row in window if row.get("ok") is True)
            repair_count = sum(1 for row in window if row.get("repaired") is True)
            fallback_count = sum(1 for row in window if row.get("fallback_used") is True)
            item["rolling_success_rate_10"] = ok_count / size if size else 0
            item["rolling_repair_rate_10"] = repair_count / size if size else 0
            item["rolling_fallback_rate_10"] = fallback_count / size if size else 0
            item["rolling_window_size"] = size
        return items

    def get_recent_llm_calls(
        self,
        *,
        limit: int = 100,
        agent_name: str | None = None,
        model: str | None = None,
        include_debug: bool = False,
    ) -> dict:
        items = self.repository.query_recent_llm_calls(limit=limit, agent_name=agent_name, model=model)
        normalized = [self._public_llm_call(item, include_debug=include_debug) for item in reversed(items)]
        return {"items": self._with_rolling_rates(normalized)}

    def _overview_for(self, items: list[dict], hours: int) -> dict:
        total = len(items)
        success = len([item for item in items if item.get("ok") is True])
        success_rate = success / total if total else 0
        failure_rate = 1 - success_rate if total else 0
        latencies = [int(item.get("latency_ms") or 0) for item in items]
        return {
            "status": self._status(success_rate, total),
            f"success_rate_{hours}h": success_rate,
            f"failure_rate_{hours}h": failure_rate,
            f"call_count_{hours}h": total,
            f"p95_latency_ms_{hours}h": percentile(latencies, 0.95),
        }

    def _series(self, items: list[dict], bucket: str, *, include_tokens: bool = False) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            grouped[self._bucket_start(str(item.get("created_at") or ""), bucket)].append(item)
        series = []
        for bucket_start, bucket_items in sorted(grouped.items()):
            total = len(bucket_items)
            success = len([item for item in bucket_items if item.get("ok") is True])
            latencies = [int(item.get("latency_ms") or 0) for item in bucket_items]
            row = {
                "bucket_start": bucket_start,
                "success_rate": success / total if total else 0,
                "failure_rate": (total - success) / total if total else 0,
                "call_count": total,
                "avg_latency_ms": int(mean(latencies)) if latencies else 0,
                "p95_latency_ms": percentile(latencies, 0.95),
            }
            if include_tokens:
                row.update(
                    {
                        "avg_prompt_tokens": int(mean([int(item.get("prompt_tokens") or 0) for item in bucket_items])) if bucket_items else 0,
                        "avg_completion_tokens": int(mean([int(item.get("completion_tokens") or 0) for item in bucket_items])) if bucket_items else 0,
                        "avg_total_tokens": int(mean([int(item.get("total_tokens") or 0) for item in bucket_items])) if bucket_items else 0,
                    }
                )
            series.append(row)
        return series

    def _bucket_start(self, created_at: str, bucket: str) -> str:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            dt = datetime.now(timezone.utc)
        if bucket.endswith("d"):
            return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        return dt.replace(minute=0, second=0, microsecond=0).isoformat()

    def _status(self, success_rate: float, total: int) -> str:
        if total <= 0:
            return "unknown"
        if success_rate >= 0.95:
            return "healthy"
        if success_rate >= 0.80:
            return "degraded"
        return "down"

    def _latest_created_at(self, items: list[dict]) -> str:
        values = [str(item.get("created_at") or "") for item in items if item.get("created_at")]
        return max(values) if values else ""

    def _with_rolling_rates(self, items: list[dict]) -> list[dict]:
        for index, item in enumerate(items):
            window = items[max(0, index - 9): index + 1]
            ok_count = sum(1 for row in window if row.get("ok") is True)
            size = len(window)
            success_rate = ok_count / size if size else 0
            item["rolling_success_rate_10"] = success_rate
            item["rolling_failure_rate_10"] = 1 - success_rate if size else 0
            item["rolling_window_size"] = size
        return items

    def _public_tool_call(self, item: dict, *, include_debug: bool) -> dict:
        metadata = _safe_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
        if not include_debug:
            metadata = {k: v for k, v in metadata.items() if k in {"round", "probe_run_id", "probe_type", "category"}}
        return {
            "id": item.get("id") or "",
            "created_at": item.get("created_at") or "",
            "run_id": item.get("run_id") or "",
            "task_id": item.get("task_id") or "",
            "session_id": item.get("session_id") or "",
            "agent_name": item.get("agent_name") or "unknown",
            "node_name": item.get("node_name") or "unknown",
            "tool_domain": item.get("tool_domain") or "unknown",
            "tool_name": item.get("tool_name") or "",
            "ok": item.get("ok") is True,
            "latency_ms": int(item.get("latency_ms") or 0),
            "error_code": item.get("error_code"),
            "error_message": _safe_text(item.get("error_message")),
            "source": item.get("source") or "runtime",
            "metadata": metadata,
            "empty_result": bool(item.get("empty_result")),
            "raw_ok": item.get("raw_ok"),
            "compact_ok": item.get("compact_ok"),
            "parsed_fields_count": int(item.get("parsed_fields_count") or 0),
            "missing_fields_count": int(item.get("missing_fields_count") or 0),
            "fallback_used": bool(item.get("fallback_used")),
        }

    def _public_llm_call(self, item: dict, *, include_debug: bool) -> dict:
        metadata = _safe_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
        if not include_debug:
            metadata = {}
        return {
            "id": item.get("id") or "",
            "created_at": item.get("created_at") or "",
            "run_id": item.get("run_id") or "",
            "task_id": item.get("task_id") or "",
            "session_id": item.get("session_id") or "",
            "agent_name": item.get("agent_name") or "unknown",
            "node_name": item.get("node_name") or "unknown",
            "provider": item.get("provider") or "unknown",
            "model": item.get("model") or "unknown",
            "call_type": item.get("call_type") or "unknown",
            "ok": item.get("ok") is True,
            "latency_ms": int(item.get("latency_ms") or 0),
            "prompt_tokens": int(item.get("prompt_tokens") or 0),
            "completion_tokens": int(item.get("completion_tokens") or 0),
            "total_tokens": int(item.get("total_tokens") or 0),
            "error_code": item.get("error_code"),
            "error_message": _safe_text(item.get("error_message")),
            "metadata": metadata,
        }
