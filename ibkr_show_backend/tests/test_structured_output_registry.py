"""Tests for Structured Output Contract Registry."""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.agents.structured_output.registry import (
    get_contract_spec_by_name,
    get_structured_output_contract_specs,
    group_contract_specs_by_agent,
)

REQUIRED_CONTRACT_NAMES = [
    "account_copilot_planner",
    "account_copilot_after_approval_final_answer",
    "trade_decision_market_trend",
    "trade_decision_fundamental_valuation",
    "trade_decision_event_catalyst",
    "daily_review_symbol_evidence_card",
    "daily_review_macro_evidence_card",
    "daily_position_review_main",
    "trade_review_behavior_pattern",
    "trade_review_opportunity_cost",
    "trade_review_main",
]


class TestRegistryCompleteness:
    def test_registry_not_empty(self):
        specs = get_structured_output_contract_specs()
        assert len(specs) > 0

    def test_required_contracts_present(self):
        specs = get_structured_output_contract_specs()
        names = {s.name for s in specs}
        for name in REQUIRED_CONTRACT_NAMES:
            assert name in names, f"Missing required contract: {name}"

    def test_no_duplicate_names(self):
        specs = get_structured_output_contract_specs()
        names = [s.name for s in specs]
        assert len(names) == len(set(names)), f"Duplicate names found: {[n for n in names if names.count(n) > 1]}"

    def test_all_fields_non_empty(self):
        specs = get_structured_output_contract_specs()
        for spec in specs:
            assert spec.agent_name, f"{spec.name}: agent_name is empty"
            assert spec.node_name, f"{spec.name}: node_name is empty"
            assert spec.output_model_name, f"{spec.name}: output_model_name is empty"
            assert spec.description, f"{spec.name}: description is empty"

    def test_examples_count_at_least_one(self):
        specs = get_structured_output_contract_specs()
        for spec in specs:
            assert spec.examples_count >= 1, f"{spec.name}: examples_count={spec.examples_count}"

    def test_schema_hint_available(self):
        specs = get_structured_output_contract_specs()
        for spec in specs:
            assert spec.schema_hint_available, f"{spec.name}: schema_hint_available=False"

    def test_max_repair_attempts_non_negative(self):
        specs = get_structured_output_contract_specs()
        for spec in specs:
            assert spec.max_repair_attempts >= 0, f"{spec.name}: max_repair_attempts={spec.max_repair_attempts}"


class TestRegistryLookup:
    def test_get_by_name_found(self):
        spec = get_contract_spec_by_name("account_copilot_planner")
        assert spec is not None
        assert spec.agent_name == "account_copilot"

    def test_get_by_name_not_found(self):
        spec = get_contract_spec_by_name("nonexistent_contract")
        assert spec is None

    def test_group_by_agent(self):
        grouped = group_contract_specs_by_agent()
        assert "account_copilot" in grouped
        assert "trade_decision" in grouped
        assert "daily_position_review" in grouped
        assert "trade_review" in grouped
        assert len(grouped["trade_decision"]) == 4


class TestAuditScript:
    @pytest.fixture(autouse=True)
    def _repo_root(self, tmp_path):
        from pathlib import Path
        self._repo_root = Path(__file__).resolve().parents[2]

    def test_audit_passes(self):
        result = subprocess.run(
            [sys.executable, "scripts/audit_structured_output_contracts.py"],
            capture_output=True,
            text=True,
            cwd=str(self._repo_root),
        )
        assert result.returncode == 0, f"Audit failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout

    def test_audit_json_mode(self):
        result = subprocess.run(
            [sys.executable, "scripts/audit_structured_output_contracts.py", "--json"],
            capture_output=True,
            text=True,
            cwd=str(self._repo_root),
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["passed"] is True
        assert data["total"] >= 11

    def test_audit_agent_filter(self):
        result = subprocess.run(
            [sys.executable, "scripts/audit_structured_output_contracts.py", "--agent", "trade_decision", "--json"],
            capture_output=True,
            text=True,
            cwd=str(self._repo_root),
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["total"] == 4
