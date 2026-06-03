from __future__ import annotations

from typing import Any

from app.services.agent_eval_repository import RegressionProfileRepository
from app.services.agent_eval_service import _DEFAULT_GATE, _SEVERITY_VALUES

_DEFAULT_TRIGGER_POLICY = {
    "on_prompt_save": False,
    "on_code_change": False,
    "on_deploy": False,
}

_VALID_MODES = {"static", "live_mock"}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _validate_gate(gate: dict[str, Any]) -> None:
    min_pass_rate = gate.get("min_pass_rate")
    if min_pass_rate is not None:
        if not isinstance(min_pass_rate, (int, float)):
            raise ValueError("gate.min_pass_rate must be a number")
        if min_pass_rate < 0 or min_pass_rate > 1:
            raise ValueError("gate.min_pass_rate must be between 0 and 1")
    max_failed = gate.get("max_failed")
    if max_failed is not None:
        if not isinstance(max_failed, (int, float)):
            raise ValueError("gate.max_failed must be a number")
        if max_failed < 0:
            raise ValueError("gate.max_failed must be >= 0")


def _merge_gate(gate: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(_DEFAULT_GATE)
    if gate:
        merged.update(gate)
    return merged


def _merge_trigger_policy(tp: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(_DEFAULT_TRIGGER_POLICY)
    if tp:
        merged.update(tp)
    return merged


def _build_default_profile(agent_name: str) -> dict[str, Any]:
    now = _utc_now_iso()
    return {
        "profile_id": agent_name,
        "agent_name": agent_name,
        "enabled": True,
        "mode": "static",
        "case_tag": "regression",
        "severity": None,
        "category": None,
        "include_disabled": False,
        "include_judge": False,
        "include_node_eval": False,
        "node_name": None,
        "limit": 100,
        "gate": dict(_DEFAULT_GATE),
        "trigger_policy": dict(_DEFAULT_TRIGGER_POLICY),
        "notes": f"{agent_name} 默认回归配置",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


class RegressionProfileService:
    def __init__(self, profile_repository: RegressionProfileRepository) -> None:
        self.profile_repository = profile_repository

    def get_regression_profile(self, agent_name: str) -> dict[str, Any] | None:
        return self.profile_repository.get_profile(agent_name)

    def list_regression_profiles(
        self,
        *,
        enabled: bool | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        items = self.profile_repository.list_profiles(enabled=enabled, query=query, limit=limit)
        enabled_count = sum(1 for p in items if p.get("enabled", True) is not False)
        return {
            "items": items,
            "summary": {
                "profile_count": len(items),
                "enabled_count": enabled_count,
            },
        }

    def upsert_regression_profile(self, agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not agent_name:
            raise ValueError("agent_name is required")
        if payload.get("agent_name") and payload["agent_name"] != agent_name:
            raise ValueError(f"body agent_name '{payload['agent_name']}' does not match path agent_name '{agent_name}'")

        mode = payload.get("mode", "static")
        if mode not in _VALID_MODES:
            raise ValueError(f"invalid mode '{mode}', must be one of {_VALID_MODES}")

        severity = payload.get("severity")
        if severity is not None and severity not in _SEVERITY_VALUES:
            raise ValueError(f"invalid severity '{severity}', must be one of {_SEVERITY_VALUES}")

        limit = payload.get("limit", 100)
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("limit must be an integer between 1 and 1000")

        gate = _merge_gate(payload.get("gate"))
        _validate_gate(gate)

        trigger_policy = _merge_trigger_policy(payload.get("trigger_policy"))

        now = _utc_now_iso()
        existing = self.profile_repository.get_profile(agent_name)

        profile: dict[str, Any] = {
            "profile_id": agent_name,
            "agent_name": agent_name,
            "enabled": payload.get("enabled", True),
            "mode": mode,
            "case_tag": payload.get("case_tag"),
            "severity": severity,
            "category": payload.get("category"),
            "include_disabled": payload.get("include_disabled", False),
            "include_judge": payload.get("include_judge", False),
            "include_node_eval": payload.get("include_node_eval", False),
            "node_name": payload.get("node_name"),
            "limit": limit,
            "gate": gate,
            "trigger_policy": trigger_policy,
            "notes": payload.get("notes", ""),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
            "version": (existing.get("version", 0) or 0) + 1 if existing else 1,
        }

        return self.profile_repository.save_profile(profile)

    def disable_regression_profile(self, agent_name: str) -> dict[str, Any] | None:
        existing = self.profile_repository.get_profile(agent_name)
        if existing is None:
            return None
        existing["enabled"] = False
        existing["updated_at"] = _utc_now_iso()
        existing["version"] = (existing.get("version", 0) or 0) + 1
        return self.profile_repository.save_profile(existing)

    def build_regression_payload_from_profile(
        self, agent_name: str, overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self.profile_repository.get_profile(agent_name)
        if profile is None:
            raise ValueError(f"Regression profile for agent '{agent_name}' not found")

        payload: dict[str, Any] = {
            "agent_name": profile["agent_name"],
            "mode": profile.get("mode", "static"),
            "case_tag": profile.get("case_tag"),
            "severity": profile.get("severity"),
            "category": profile.get("category"),
            "include_disabled": profile.get("include_disabled", False),
            "include_judge": profile.get("include_judge", False),
            "include_node_eval": profile.get("include_node_eval", False),
            "node_name": profile.get("node_name"),
            "limit": profile.get("limit", 100),
            "gate": profile.get("gate", dict(_DEFAULT_GATE)),
        }

        if overrides:
            for key, value in overrides.items():
                if value is not None:
                    payload[key] = value

        return payload
