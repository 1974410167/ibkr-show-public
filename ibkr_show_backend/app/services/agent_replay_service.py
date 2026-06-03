from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from app.agents.run_replay import AgentReplaySnapshot, sanitize_replay_payload
from app.services.agent_replay_repository import AgentReplayRepository

logger = logging.getLogger(__name__)


class AgentReplayService:
    def __init__(self, repository: AgentReplayRepository) -> None:
        self.repository = repository

    def record_snapshot(self, snapshot: AgentReplaySnapshot | dict) -> dict:
        payload = snapshot.to_dict() if isinstance(snapshot, AgentReplaySnapshot) else sanitize_replay_payload(snapshot)
        document = self._prepare_document(payload)
        return self.repository.save_snapshot(document)

    def get_snapshot(self, replay_id: str) -> dict | None:
        return self.repository.get_snapshot(replay_id)

    def get_by_run_id(self, run_id: str) -> dict | None:
        return self.repository.get_by_run_id(run_id)

    def list_snapshots(
        self,
        *,
        hours: int = 24,
        agent_name: str | None = None,
        final_status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        items = self.repository.list_snapshots(
            hours=hours,
            agent_name=agent_name,
            final_status=final_status,
            limit=limit,
        )
        return {"items": items, "summary": self.summary(items)}

    def export_replay_package(self, replay_id: str) -> dict | None:
        snapshot = self.get_snapshot(replay_id)
        if snapshot is None:
            return None
        return {
            "package_type": "agent_replay_package",
            "package_version": "v1",
            "snapshot": snapshot,
            "notes": [
                "P0 package is for inspection and future replay wiring.",
                "System prompts and secrets are intentionally omitted.",
            ],
        }

    def summary(self, items: list[dict]) -> dict[str, Any]:
        count = len(items)
        return {
            "snapshot_count": count,
            "success_rate": sum(1 for item in items if item.get("final_status") == "success") / count if count else 0,
            "partial_rate": sum(1 for item in items if item.get("final_status") == "partial") / count if count else 0,
            "failure_rate": sum(1 for item in items if item.get("final_status") == "failed") / count if count else 0,
            "avg_llm_calls": mean([len(item.get("llm_snapshots") or []) for item in items]) if items else 0,
            "by_agent": _bucket(items, "agent_name"),
            "by_status": _bucket(items, "final_status"),
        }

    def _prepare_document(self, payload: dict) -> dict:
        prompt_refs = payload.get("prompt_refs") if isinstance(payload.get("prompt_refs"), list) else []
        model_config = payload.get("model_config") if isinstance(payload.get("model_config"), dict) else {}
        tool_snapshots = payload.get("tool_snapshots") if isinstance(payload.get("tool_snapshots"), list) else []
        llm_snapshots = payload.get("llm_snapshots") if isinstance(payload.get("llm_snapshots"), list) else []
        return {
            **payload,
            "prompt_keys": sorted({str(item.get("prompt_key")) for item in prompt_refs if isinstance(item, dict) and item.get("prompt_key")}),
            "model": model_config.get("model"),
            "tool_names": sorted({str(item.get("tool_name")) for item in tool_snapshots if isinstance(item, dict) and item.get("tool_name")}),
            "llm_call_ids": sorted({str(item.get("call_id")) for item in llm_snapshots if isinstance(item, dict) and item.get("call_id")}),
        }


def _bucket(items: list[dict], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = buckets.setdefault(name, {"snapshot_count": 0})
        bucket["snapshot_count"] += 1
    return buckets
