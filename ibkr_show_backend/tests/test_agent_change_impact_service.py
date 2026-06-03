from __future__ import annotations

import pytest

from app.services.agent_change_impact_service import AgentChangeImpactService, _normalize_paths


class FakeProfileServiceForImpact:
    def __init__(self) -> None:
        self.profiles: dict[str, dict] = {}

    def get_regression_profile(self, agent_name: str) -> dict | None:
        return self.profiles.get(agent_name)

    def list_regression_profiles(self, *, enabled=None, query=None, limit=100) -> dict:
        items = list(self.profiles.values())
        if enabled is not None:
            items = [p for p in items if p.get("enabled", True) == enabled]
        return {"items": items, "summary": {"profile_count": len(items), "enabled_count": sum(1 for p in items if p.get("enabled", True))}}

    def build_regression_payload_from_profile(self, agent_name: str, overrides=None) -> dict:
        profile = self.profiles.get(agent_name)
        if profile is None:
            raise ValueError(f"Profile for '{agent_name}' not found")
        payload = {"agent_name": agent_name, "mode": profile.get("mode", "static"), "limit": profile.get("limit", 100), "gate": profile.get("gate", {})}
        if overrides:
            for k, v in overrides.items():
                if v is not None:
                    payload[k] = v
        return payload


def _make_profile(agent_name: str, *, enabled=True, on_code_change=True, include_node_eval=False) -> dict:
    return {
        "profile_id": agent_name,
        "agent_name": agent_name,
        "enabled": enabled,
        "mode": "static",
        "case_tag": "regression",
        "include_node_eval": include_node_eval,
        "limit": 100,
        "gate": {"fail_on_critical": True, "min_pass_rate": 0.9},
        "trigger_policy": {"on_prompt_save": False, "on_code_change": on_code_change, "on_deploy": False},
    }


def _make_service(profiles: list[dict] | None = None) -> tuple[AgentChangeImpactService, FakeProfileServiceForImpact]:
    fake = FakeProfileServiceForImpact()
    for p in (profiles or []):
        fake.profiles[p["agent_name"]] = p
    return AgentChangeImpactService(fake), fake


class TestNormalizePaths:
    def test_dedup(self):
        assert _normalize_paths(["a.py", "a.py", "b.py"]) == ["a.py", "b.py"]

    def test_strip_whitespace(self):
        assert _normalize_paths(["  a.py  ", "b.py"]) == ["a.py", "b.py"]

    def test_skip_empty(self):
        assert _normalize_paths(["", "  ", "a.py"]) == ["a.py"]

    def test_skip_absolute(self):
        assert _normalize_paths(["/etc/passwd", "a.py"]) == ["a.py"]

    def test_skip_parent_traversal(self):
        assert _normalize_paths(["../../etc/passwd", "a.py"]) == ["a.py"]


class TestAnalyzeChangedFiles:
    def test_trade_decision_hit(self):
        svc, _ = _make_service([_make_profile("trade_decision")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 1
        assert result["impacted_agents"][0]["agent_name"] == "trade_decision"
        assert result["impacted_agents"][0]["confidence"] == "high"
        assert result["impacted_agents"][0]["recommended"] is True

    def test_trade_decision_risk_control_node(self):
        svc, _ = _make_service([_make_profile("trade_decision", include_node_eval=True)])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/risk_control.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["agent_name"] == "trade_decision"
        assert "risk_control" in agent["impacted_nodes"]

    def test_shared_nodes_file_no_specific_node(self):
        svc, _ = _make_service([_make_profile("trade_decision", include_node_eval=True)])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["agent_name"] == "trade_decision"
        assert agent["impacted_nodes"] == []

    def test_daily_position_review_hit(self):
        svc, _ = _make_service([_make_profile("daily_position_review")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/daily_position_review_graph/nodes.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 1
        assert result["impacted_agents"][0]["agent_name"] == "daily_position_review"

    def test_trade_review_hit(self):
        svc, _ = _make_service([_make_profile("trade_review")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_review_graph/prompts.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 1
        assert result["impacted_agents"][0]["agent_name"] == "trade_review"

    def test_account_copilot_hit(self):
        svc, _ = _make_service([_make_profile("account_copilot")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/account_copilot/runtime.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 1
        assert result["impacted_agents"][0]["agent_name"] == "account_copilot"

    def test_unmatched_file(self):
        svc, _ = _make_service()
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/services/account_service.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 0
        assert result["unmatched_files"] == ["ibkr_show_backend/app/services/account_service.py"]

    def test_eval_harness_file_affects_all_enabled_profiles(self):
        svc, _ = _make_service([
            _make_profile("trade_decision"),
            _make_profile("trade_review", enabled=False),
        ])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/services/agent_eval_service.py",
        ])
        agents = {a["agent_name"] for a in result["impacted_agents"]}
        assert "trade_decision" in agents
        assert "trade_review" not in agents
        for agent in result["impacted_agents"]:
            assert agent["confidence"] == "medium"
            assert "eval harness" in agent["reason"]

    def test_prompt_management_file_affects_on_prompt_save_profiles(self):
        svc, _ = _make_service([
            _make_profile("trade_decision"),
            _make_profile("trade_review"),
        ])
        svc.profile_service.profiles["trade_decision"]["trigger_policy"]["on_prompt_save"] = True
        result = svc.analyze_changed_files([
            "ibkr_show_frontend/src/views/AdminPromptsView.vue",
        ])
        agents = {a["agent_name"] for a in result["impacted_agents"]}
        assert "trade_decision" in agents
        assert "trade_review" not in agents

    def test_profile_not_exists_recommended_false(self):
        svc, _ = _make_service([])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["profile_exists"] is False
        assert agent["recommended"] is False
        assert "missing regression profile" in agent["reason"]
        assert agent["regression_payload"] is None

    def test_profile_disabled_recommended_false(self):
        svc, _ = _make_service([_make_profile("trade_decision", enabled=False)])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["profile_enabled"] is False
        assert agent["recommended"] is False
        assert "disabled" in agent["reason"]

    def test_on_code_change_false_recommended_false(self):
        svc, _ = _make_service([_make_profile("trade_decision", on_code_change=False)])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["trigger_policy_on_code_change"] is False
        assert agent["recommended"] is False
        assert "on_code_change disabled" in agent["reason"]

    def test_on_code_change_true_recommended_true(self):
        svc, _ = _make_service([_make_profile("trade_decision", on_code_change=True)])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        agent = result["impacted_agents"][0]
        assert agent["recommended"] is True

    def test_payload_includes_trigger_and_git(self):
        svc, _ = _make_service([_make_profile("trade_decision")])
        result = svc.analyze_changed_files(
            ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"],
            base_ref="origin/main", head_ref="HEAD",
        )
        agent = result["impacted_agents"][0]
        payload = agent["regression_payload"]
        assert payload is not None
        assert payload["trigger"] == "code_change"
        assert payload["name"] == "Code change regression - trade_decision"
        assert payload["git"]["base_ref"] == "origin/main"
        assert payload["git"]["head_ref"] == "HEAD"
        assert "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py" in payload["git"]["changed_files"]

    def test_payload_not_generated_when_no_profile(self):
        svc, _ = _make_service([])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ], include_payload=True)
        agent = result["impacted_agents"][0]
        assert agent["regression_payload"] is None

    def test_multiple_files_dedup(self):
        svc, _ = _make_service([_make_profile("trade_decision")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
        ])
        assert result["summary"]["changed_file_count"] == 1

    def test_empty_files_raises(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="empty"):
            svc.analyze_changed_files([])

    def test_include_payload_false(self):
        svc, _ = _make_service([_make_profile("trade_decision")])
        result = svc.analyze_changed_files(
            ["ibkr_show_backend/app/agents/trade_decision_graph/nodes.py"],
            include_payload=False,
        )
        agent = result["impacted_agents"][0]
        assert agent["regression_payload"] is None
        assert agent["recommended"] is True

    def test_multiple_agents(self):
        svc, _ = _make_service([
            _make_profile("trade_decision"),
            _make_profile("trade_review"),
        ])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/agents/trade_decision_graph/nodes.py",
            "ibkr_show_backend/app/agents/trade_review_graph/prompts.py",
        ])
        assert result["summary"]["impacted_agent_count"] == 2
        agents = {a["agent_name"] for a in result["impacted_agents"]}
        assert agents == {"trade_decision", "trade_review"}

    def test_prompt_key_match(self):
        svc, _ = _make_service([_make_profile("trade_decision")])
        result = svc.analyze_changed_files([
            "ibkr_show_backend/app/prompts/trade_decision/risk_control.md",
        ])
        assert result["summary"]["impacted_agent_count"] == 1
        assert result["impacted_agents"][0]["agent_name"] == "trade_decision"
