from __future__ import annotations

from collections import Counter

from app.agents.eval_simulation_scenarios import (
    VALID_SYNTHETIC_AGENT_NAMES,
    VALID_SYNTHETIC_SEVERITIES,
    filter_synthetic_scenarios,
    get_synthetic_scenario,
    list_synthetic_scenarios,
    list_synthetic_scenarios_by_agent,
    summarize_synthetic_scenarios,
)


def test_list_synthetic_scenarios_has_required_volume_by_agent() -> None:
    scenarios = list_synthetic_scenarios()
    counts = Counter(item["agent_name"] for item in scenarios)

    assert len(scenarios) >= 70
    assert set(counts) == VALID_SYNTHETIC_AGENT_NAMES
    assert counts["trade_decision"] >= 25
    assert counts["daily_position_review"] >= 15
    assert counts["trade_review"] >= 15
    assert counts["account_copilot"] >= 10


def test_each_synthetic_scenario_has_required_fields_and_tags() -> None:
    scenarios = list_synthetic_scenarios()
    required_fields = {
        "scenario_id",
        "agent_name",
        "title",
        "description",
        "user_question",
        "user_profile",
        "mock_context",
        "data_availability",
        "expected_good_behavior",
        "failure_traps",
        "stress_dimensions",
        "tags",
        "severity",
        "category",
        "source",
        "metadata",
    }

    for scenario in scenarios:
        assert required_fields.issubset(scenario)
        assert scenario["scenario_id"]
        assert scenario["agent_name"] in VALID_SYNTHETIC_AGENT_NAMES
        assert scenario["severity"] in VALID_SYNTHETIC_SEVERITIES
        assert scenario["user_question"]
        assert scenario["expected_good_behavior"]
        assert scenario["failure_traps"]
        assert scenario["stress_dimensions"]
        assert scenario["tags"]
        assert scenario["source"] == "synthetic"
        assert "synthetic" in scenario["tags"]
        assert "p3_5" in scenario["tags"]
        assert scenario["agent_name"] in scenario["tags"]
        assert scenario["metadata"]["scenario_type"] in scenario["tags"]


def test_daily_position_review_scenarios_include_report_date_context() -> None:
    scenarios = list_synthetic_scenarios_by_agent("daily_position_review")

    assert scenarios
    for scenario in scenarios:
        context = scenario["mock_context"]
        metadata = scenario["metadata"]
        assert context.get("report_date") or context.get("report_date_strategy")
        assert metadata.get("report_date") or metadata.get("report_date_strategy")


def test_trade_review_scenarios_include_real_executor_context() -> None:
    scenarios = list_synthetic_scenarios_by_agent("trade_review")

    assert scenarios
    for scenario in scenarios:
        context = scenario["mock_context"]
        metadata = scenario["metadata"]
        review_type = metadata.get("review_type") or context.get("review_type")
        assert review_type
        if review_type == "symbol_level_review":
            assert context.get("symbol") or metadata.get("symbol")
            assert (context.get("start_date") or context.get("start_date_strategy") or metadata.get("start_date") or metadata.get("start_date_strategy"))
            assert (context.get("end_date") or context.get("end_date_strategy") or metadata.get("end_date") or metadata.get("end_date_strategy"))
        elif review_type == "single_trade_review":
            assert context.get("trade_id") or metadata.get("trade_id") or metadata.get("real_run_supported") is False
        else:
            raise AssertionError(f"Unexpected review_type: {review_type}")


def test_stress_scenarios_do_not_treat_chasing_dip_buying_or_concentration_as_inherently_wrong() -> None:
    scenarios = list_synthetic_scenarios()
    stress_types = {
        "chase_high",
        "right_side_breakout",
        "left_side_accumulation",
        "falling_knife",
        "concentrated_position",
        "margin_high_volatility",
    }
    stress_scenarios = [
        scenario
        for scenario in scenarios
        if scenario["agent_name"] == "trade_decision"
        and scenario["metadata"]["scenario_type"] in stress_types
    ]

    assert stress_scenarios
    for scenario in stress_scenarios:
        expected_text = "\n".join(scenario["expected_good_behavior"])
        assert "条件" in expected_text or "分批" in expected_text
        assert "本身定义为错误" in expected_text or "同时满足" in expected_text


def test_filter_synthetic_scenarios_by_agent_tag_severity_category_and_limit() -> None:
    trade_decision = filter_synthetic_scenarios(agent_name="trade_decision", limit=100)
    chase_high = filter_synthetic_scenarios(tag="chase_high", limit=100)
    high = filter_synthetic_scenarios(severity="high", limit=100)
    valuation = filter_synthetic_scenarios(category="valuation", limit=100)
    limited = filter_synthetic_scenarios(agent_name="trade_decision", limit=3)

    assert trade_decision
    assert all(item["agent_name"] == "trade_decision" for item in trade_decision)
    assert chase_high
    assert all("chase_high" in item["tags"] for item in chase_high)
    assert high
    assert all(item["severity"] == "high" for item in high)
    assert valuation
    assert all(item["category"] == "valuation" for item in valuation)
    assert len(limited) == 3


def test_get_and_list_synthetic_scenarios_by_agent() -> None:
    items = list_synthetic_scenarios_by_agent("account_copilot")
    assert items
    assert all(item["agent_name"] == "account_copilot" for item in items)

    scenario = get_synthetic_scenario(items[0]["scenario_id"])
    assert scenario is not None
    assert scenario["scenario_id"] == items[0]["scenario_id"]
    assert get_synthetic_scenario("missing") is None


def test_summarize_synthetic_scenarios() -> None:
    summary = summarize_synthetic_scenarios()

    assert summary["total_count"] == len(list_synthetic_scenarios())
    assert summary["by_agent"]["trade_decision"] >= 25
    assert summary["by_agent"]["daily_position_review"] >= 15
    assert summary["by_agent"]["trade_review"] >= 15
    assert summary["by_agent"]["account_copilot"] >= 10
    assert summary["by_severity"]
    assert summary["by_category"]
    assert summary["by_tag"]["synthetic"] == summary["total_count"]
    assert summary["by_tag"]["p3_5"] == summary["total_count"]
