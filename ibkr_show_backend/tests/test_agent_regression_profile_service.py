from __future__ import annotations

import pytest

from app.services.agent_regression_profile_service import RegressionProfileService


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict] = {}

    def save_profile(self, profile: dict) -> dict:
        self.profiles[profile["profile_id"]] = profile
        return profile

    def get_profile(self, profile_id: str) -> dict | None:
        return self.profiles.get(profile_id)

    def list_profiles(self, *, enabled=None, agent_name=None, query=None, limit=100) -> list[dict]:
        items = list(self.profiles.values())
        if enabled is not None:
            items = [p for p in items if p.get("enabled", True) == enabled]
        if agent_name:
            items = [p for p in items if p.get("agent_name") == agent_name]
        return items[:limit]

    def delete_profile(self, profile_id: str) -> bool:
        return self.profiles.pop(profile_id, None) is not None


def _make_service() -> tuple[RegressionProfileService, FakeProfileRepository]:
    repo = FakeProfileRepository()
    return RegressionProfileService(repo), repo


class TestUpsertRegressionProfile:
    def test_create_profile_success(self):
        svc, repo = _make_service()
        result = svc.upsert_regression_profile("trade_decision", {
            "mode": "static",
            "case_tag": "regression",
            "limit": 50,
        })
        assert result["agent_name"] == "trade_decision"
        assert result["profile_id"] == "trade_decision"
        assert result["mode"] == "static"
        assert result["case_tag"] == "regression"
        assert result["limit"] == 50
        assert result["enabled"] is True
        assert result["version"] == 1
        assert "created_at" in result
        assert "updated_at" in result
        assert repo.profiles["trade_decision"] is result

    def test_update_profile_success(self):
        svc, repo = _make_service()
        svc.upsert_regression_profile("trade_decision", {"mode": "static", "limit": 50})
        result = svc.upsert_regression_profile("trade_decision", {"limit": 200, "notes": "updated"})
        assert result["limit"] == 200
        assert result["notes"] == "updated"
        assert result["version"] == 2
        assert result["mode"] == "static"

    def test_default_gate_filled(self):
        svc, _ = _make_service()
        result = svc.upsert_regression_profile("trade_decision", {})
        gate = result["gate"]
        assert gate["fail_on_critical"] is True
        assert gate["fail_on_high"] is False
        assert gate["min_pass_rate"] == 0.9
        assert gate["max_failed"] is None

    def test_custom_gate_merged(self):
        svc, _ = _make_service()
        result = svc.upsert_regression_profile("trade_decision", {
            "gate": {"fail_on_high": True, "min_pass_rate": 0.8},
        })
        gate = result["gate"]
        assert gate["fail_on_critical"] is True
        assert gate["fail_on_high"] is True
        assert gate["min_pass_rate"] == 0.8
        assert gate["max_failed"] is None

    def test_default_trigger_policy_filled(self):
        svc, _ = _make_service()
        result = svc.upsert_regression_profile("trade_decision", {})
        tp = result["trigger_policy"]
        assert tp["on_prompt_save"] is False
        assert tp["on_code_change"] is False
        assert tp["on_deploy"] is False

    def test_invalid_mode_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="invalid mode"):
            svc.upsert_regression_profile("trade_decision", {"mode": "invalid_mode"})

    def test_invalid_severity_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="invalid severity"):
            svc.upsert_regression_profile("trade_decision", {"severity": "ultra"})

    def test_min_pass_rate_gt_1_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="min_pass_rate"):
            svc.upsert_regression_profile("trade_decision", {"gate": {"min_pass_rate": 1.5}})

    def test_min_pass_rate_lt_0_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="min_pass_rate"):
            svc.upsert_regression_profile("trade_decision", {"gate": {"min_pass_rate": -0.1}})

    def test_max_failed_negative_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="max_failed"):
            svc.upsert_regression_profile("trade_decision", {"gate": {"max_failed": -1}})

    def test_limit_out_of_range_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="limit"):
            svc.upsert_regression_profile("trade_decision", {"limit": 0})
        with pytest.raises(ValueError, match="limit"):
            svc.upsert_regression_profile("trade_decision", {"limit": 1001})

    def test_agent_name_mismatch_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="does not match"):
            svc.upsert_regression_profile("trade_decision", {"agent_name": "daily_position_review"})

    def test_empty_agent_name_returns_400(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="agent_name is required"):
            svc.upsert_regression_profile("", {})


class TestGetRegressionProfile:
    def test_get_existing(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        result = svc.get_regression_profile("trade_decision")
        assert result is not None
        assert result["agent_name"] == "trade_decision"

    def test_get_nonexistent_returns_none(self):
        svc, _ = _make_service()
        assert svc.get_regression_profile("nonexistent") is None


class TestListRegressionProfiles:
    def test_list_all(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        svc.upsert_regression_profile("trade_review", {})
        result = svc.list_regression_profiles()
        assert result["summary"]["profile_count"] == 2
        assert result["summary"]["enabled_count"] == 2
        assert len(result["items"]) == 2

    def test_list_enabled_filter(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {"enabled": True})
        svc.upsert_regression_profile("trade_review", {"enabled": False})
        result = svc.list_regression_profiles(enabled=True)
        assert result["summary"]["profile_count"] == 1
        assert result["items"][0]["agent_name"] == "trade_decision"

    def test_list_empty(self):
        svc, _ = _make_service()
        result = svc.list_regression_profiles()
        assert result["summary"]["profile_count"] == 0
        assert result["summary"]["enabled_count"] == 0


class TestDisableRegressionProfile:
    def test_disable_existing(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        result = svc.disable_regression_profile("trade_decision")
        assert result is not None
        assert result["enabled"] is False
        assert result["version"] == 2

    def test_disable_nonexistent_returns_none(self):
        svc, _ = _make_service()
        assert svc.disable_regression_profile("nonexistent") is None


class TestBuildRegressionPayloadFromProfile:
    def test_build_payload_success(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {
            "mode": "static",
            "case_tag": "regression",
            "severity": "high",
            "include_node_eval": True,
            "limit": 50,
        })
        payload = svc.build_regression_payload_from_profile("trade_decision")
        assert payload["agent_name"] == "trade_decision"
        assert payload["mode"] == "static"
        assert payload["case_tag"] == "regression"
        assert payload["severity"] == "high"
        assert payload["include_node_eval"] is True
        assert payload["limit"] == 50
        assert "gate" in payload

    def test_build_payload_with_overrides(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {"mode": "static", "limit": 50})
        payload = svc.build_regression_payload_from_profile("trade_decision", {"limit": 200, "mode": "live_mock"})
        assert payload["limit"] == 200
        assert payload["mode"] == "live_mock"

    def test_build_payload_nonexistent_raises(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="not found"):
            svc.build_regression_payload_from_profile("nonexistent")

    def test_build_payload_with_trigger_override(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {"mode": "static", "limit": 50})
        payload = svc.build_regression_payload_from_profile("trade_decision", {"trigger": "prompt_save"})
        assert payload["trigger"] == "prompt_save"
        assert payload["agent_name"] == "trade_decision"
        assert payload["limit"] == 50

    def test_build_payload_with_prompt_metadata_override(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        prompt_meta = {
            "prompt_key": "trade_decision_system",
            "prompt_version": "v3",
            "prompt_hash": "abc123",
            "saved_at": "2026-01-01T00:00:00+00:00",
            "source": "admin_prompt_save",
        }
        payload = svc.build_regression_payload_from_profile("trade_decision", {
            "trigger": "prompt_save",
            "name": "Prompt regression - trade_decision - trade_decision_system",
            "prompt": prompt_meta,
        })
        assert payload["trigger"] == "prompt_save"
        assert payload["name"] == "Prompt regression - trade_decision - trade_decision_system"
        assert payload["prompt"]["prompt_key"] == "trade_decision_system"
        assert payload["prompt"]["source"] == "admin_prompt_save"
        assert payload["agent_name"] == "trade_decision"

    def test_build_payload_override_does_not_mutate_profile(self):
        svc, repo = _make_service()
        svc.upsert_regression_profile("trade_decision", {"mode": "static", "limit": 50})
        svc.build_regression_payload_from_profile("trade_decision", {"trigger": "prompt_save", "limit": 200})
        profile = repo.get_profile("trade_decision")
        assert profile["limit"] == 50
        assert "trigger" not in profile

    def test_build_payload_with_git_override(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        payload = svc.build_regression_payload_from_profile("trade_decision", {
            "git": {"commit": "abc123", "branch": "main"},
        })
        assert payload["git"]["commit"] == "abc123"
        assert payload["agent_name"] == "trade_decision"

    def test_build_payload_with_baseline_override(self):
        svc, _ = _make_service()
        svc.upsert_regression_profile("trade_decision", {})
        payload = svc.build_regression_payload_from_profile("trade_decision", {
            "baseline_eval_run_id": "run-123",
        })
        assert payload["baseline_eval_run_id"] == "run-123"
