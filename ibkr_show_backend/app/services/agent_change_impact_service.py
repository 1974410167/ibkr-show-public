from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any

from app.services.agent_regression_profile_service import RegressionProfileService

# ── Impact Rules ─────────────────────────────────────────────────────

_AGENT_RULES: list[dict[str, Any]] = [
    {
        "agent_name": "trade_decision",
        "path_patterns": [
            "trade_decision", "trade-decision", "trade_decision_agent",
            "trading_decision", "trade_decision_graph",
        ],
        "prompt_patterns": ["prompts/trade_decision"],
        "nodes": {
            "market_trend": ["market_trend"],
            "fundamental_valuation": ["fundamental_valuation"],
            "event_catalyst": ["event_catalyst"],
            "risk_control": ["risk_control"],
            "final_decision": ["final_decision"],
        },
    },
    {
        "agent_name": "daily_position_review",
        "path_patterns": [
            "daily_position_review", "daily-position-review",
            "position_review", "daily_position_review_graph",
        ],
        "prompt_patterns": ["prompts/daily_position_review"],
        "nodes": {
            "compose_daily_review": ["compose_daily_review"],
            "position_summary": ["position_summary"],
            "pnl_analysis": ["pnl_analysis"],
            "risk_summary": ["risk_summary"],
            "news_summary": ["news_summary"],
        },
    },
    {
        "agent_name": "trade_review",
        "path_patterns": [
            "trade_review", "trade-review", "trade_review_graph",
        ],
        "prompt_patterns": ["prompts/trade_review"],
        "nodes": {},
    },
    {
        "agent_name": "account_copilot",
        "path_patterns": [
            "account_copilot", "account-copilot",
        ],
        "prompt_patterns": ["prompts/account_copilot"],
        "nodes": {},
    },
]

_EVAL_HARNESS_PATTERNS = [
    "app/agents/eval_",
    "app/services/agent_eval",
    "app/api/routes/admin_agent_eval.py",
    "ibkr_show_frontend/src/views/AdminHarnessView.vue",
    "ibkr_show_frontend/src/components/admin/AgentRegressionRunPanel.vue",
    "ibkr_show_frontend/src/components/admin/RegressionProfilePanel.vue",
]

_PROMPT_MANAGEMENT_PATTERNS = [
    "AdminPromptsView.vue",
    "adminPrompts",
    "prompt_service",
    "prompt_repository",
    "app/agents/prompt_registry.py",
    "app/agents/prompt_runtime.py",
]


def _normalize_paths(files: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for f in files:
        if not f or not f.strip():
            continue
        p = PurePosixPath(f.strip())
        normalized = str(p)
        if normalized.startswith("/") or ".." in normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _matches_any(path: str, patterns: list[str]) -> bool:
    lower = path.lower()
    return any(p.lower() in lower for p in patterns)


def _detect_impacted_nodes(path: str, nodes: dict[str, list[str]]) -> list[str]:
    lower = path.lower()
    matched: list[str] = []
    for node_name, node_patterns in nodes.items():
        if any(p.lower() in lower for p in node_patterns):
            matched.append(node_name)
    return matched


class AgentChangeImpactService:
    def __init__(self, profile_service: RegressionProfileService, repo_root: str | None = None) -> None:
        self.profile_service = profile_service
        self.repo_root = repo_root

    def analyze_changed_files(
        self,
        changed_files: list[str],
        *,
        base_ref: str | None = None,
        head_ref: str | None = None,
        include_payload: bool = True,
    ) -> dict[str, Any]:
        normalized = _normalize_paths(changed_files)
        if not normalized:
            raise ValueError("changed_files is empty after normalization")

        agent_hits: dict[str, dict[str, Any]] = {}
        unmatched: list[str] = []

        for filepath in normalized:
            matched_agent = False

            for rule in _AGENT_RULES:
                if _matches_any(filepath, rule["path_patterns"]) or _matches_any(filepath, rule.get("prompt_patterns", [])):
                    agent_name = rule["agent_name"]
                    if agent_name not in agent_hits:
                        agent_hits[agent_name] = {
                            "agent_name": agent_name,
                            "confidence": "high",
                            "matched_files": [],
                            "impacted_nodes": set(),
                            "match_reason": "agent/node files changed",
                        }
                    agent_hits[agent_name]["matched_files"].append(filepath)
                    nodes = _detect_impacted_nodes(filepath, rule.get("nodes", {}))
                    agent_hits[agent_name]["impacted_nodes"].update(nodes)
                    matched_agent = True

            if not matched_agent and _matches_any(filepath, _EVAL_HARNESS_PATTERNS):
                profiles = self.profile_service.list_regression_profiles(enabled=True)
                for profile in profiles.get("items", []):
                    aname = profile["agent_name"]
                    if aname not in agent_hits:
                        agent_hits[aname] = {
                            "agent_name": aname,
                            "confidence": "medium",
                            "matched_files": [],
                            "impacted_nodes": set(),
                            "match_reason": "eval harness changed",
                        }
                    agent_hits[aname]["matched_files"].append(filepath)
                    matched_agent = True

            if not matched_agent and _matches_any(filepath, _PROMPT_MANAGEMENT_PATTERNS):
                profiles = self.profile_service.list_regression_profiles()
                for profile in profiles.get("items", []):
                    if profile.get("trigger_policy", {}).get("on_prompt_save"):
                        aname = profile["agent_name"]
                        if aname not in agent_hits:
                            agent_hits[aname] = {
                                "agent_name": aname,
                                "confidence": "medium",
                                "matched_files": [],
                                "impacted_nodes": set(),
                                "match_reason": "prompt management changed",
                            }
                        agent_hits[aname]["matched_files"].append(filepath)
                        matched_agent = True

            if not matched_agent:
                unmatched.append(filepath)

        impacted_agents: list[dict[str, Any]] = []
        recommended_count = 0

        for agent_name, hit in sorted(agent_hits.items()):
            impacted_nodes = sorted(hit["impacted_nodes"])
            profile = self.profile_service.get_regression_profile(agent_name)

            profile_exists = profile is not None
            profile_enabled = profile.get("enabled", True) if profile else False
            on_code_change = profile.get("trigger_policy", {}).get("on_code_change", False) if profile else False

            recommended = profile_exists and profile_enabled and on_code_change
            reason_parts = [hit["match_reason"]]
            if not profile_exists:
                reason_parts.append("missing regression profile")
            elif not profile_enabled:
                reason_parts.append("regression profile disabled")
            elif not on_code_change:
                reason_parts.append("on_code_change disabled")

            entry: dict[str, Any] = {
                "agent_name": agent_name,
                "confidence": hit["confidence"],
                "matched_files": hit["matched_files"],
                "impacted_nodes": impacted_nodes,
                "profile_exists": profile_exists,
                "profile_enabled": profile_enabled,
                "trigger_policy_on_code_change": on_code_change,
                "recommended": recommended,
                "reason": "; ".join(reason_parts),
            }

            if include_payload and profile_exists:
                overrides: dict[str, Any] = {
                    "trigger": "code_change",
                    "name": f"Code change regression - {agent_name}",
                    "git": {
                        "base_ref": base_ref or "",
                        "head_ref": head_ref or "",
                        "changed_files": hit["matched_files"],
                    },
                }
                if len(impacted_nodes) == 1 and profile.get("include_node_eval"):
                    overrides["node_name"] = impacted_nodes[0]
                if len(impacted_nodes) > 1:
                    entry["recommended_node_names"] = impacted_nodes
                try:
                    entry["regression_payload"] = self.profile_service.build_regression_payload_from_profile(
                        agent_name, overrides,
                    )
                except Exception:
                    entry["regression_payload"] = None
            else:
                entry["regression_payload"] = None

            if recommended:
                recommended_count += 1
            impacted_agents.append(entry)

        return {
            "impacted_agents": impacted_agents,
            "unmatched_files": unmatched,
            "summary": {
                "changed_file_count": len(normalized),
                "impacted_agent_count": len(impacted_agents),
                "recommended_run_count": recommended_count,
            },
            "base_ref": base_ref,
            "head_ref": head_ref,
        }

    def analyze_git_diff(
        self,
        base_ref: str,
        head_ref: str,
        *,
        include_payload: bool = True,
    ) -> dict[str, Any]:
        if not base_ref or not head_ref:
            raise ValueError("base_ref and head_ref are required")
        cwd = self.repo_root
        if cwd:
            from pathlib import Path
            if not Path(cwd).is_dir():
                raise ValueError(f"repo_root '{cwd}' is not a directory")
            if not Path(cwd, ".git").exists():
                raise ValueError(f"repo_root '{cwd}' is not a git repository")
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref, head_ref],
                capture_output=True, text=True, timeout=30, cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("git diff timed out after 30 seconds")
        except FileNotFoundError:
            raise ValueError("git command not found")
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ValueError(f"git diff failed (exit {result.returncode}): {stderr}")
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return self.analyze_changed_files(
            files, base_ref=base_ref, head_ref=head_ref, include_payload=include_payload,
        )
