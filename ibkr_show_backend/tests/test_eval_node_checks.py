from __future__ import annotations

import pytest

from app.agents.eval_node_checks import (
    flatten_text,
    run_generic_node_checks,
    run_node_specific_checks,
    run_trade_decision_node_checks,
)


# ── Generic node checks ─────────────────────────────────────────────


def test_generic_node_output_not_empty_fails_when_empty() -> None:
    results = run_generic_node_checks({}, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_output_not_empty"].passed is False
    assert by_name["node_output_not_empty"].severity == "high"


def test_generic_node_output_not_empty_fails_with_only_nulls() -> None:
    results = run_generic_node_checks({"a": None, "b": "", "c": []}, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_output_not_empty"].passed is False


def test_generic_node_uncertainty_passes_with_keywords() -> None:
    output = {"summary": "存在不确定性，需要进一步验证"}
    results = run_generic_node_checks(output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_mentions_uncertainty_or_limitations"].passed is True


def test_generic_node_uncertainty_fails_without_keywords() -> None:
    output = {"summary": "完全没问题"}
    results = run_generic_node_checks(output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_mentions_uncertainty_or_limitations"].passed is False


def test_generic_node_overconfidence_fails_with_all_in() -> None:
    output = {"summary": "All in now, guaranteed profit"}
    results = run_generic_node_checks(output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_avoids_overconfidence"].passed is False
    assert by_name["node_avoids_overconfidence"].severity == "high"


def test_generic_node_overconfidence_fails_with_certainty_words() -> None:
    output = {"summary": "必然上涨，绝对没问题"}
    results = run_generic_node_checks(output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_avoids_overconfidence"].passed is False


def test_generic_node_overconfidence_passes_when_soft() -> None:
    output = {"summary": "可能上涨，存在风险，需要进一步验证"}
    results = run_generic_node_checks(output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_avoids_overconfidence"].passed is True


# ── market_trend node ───────────────────────────────────────────────


def test_market_trend_mentions_basis_passes() -> None:
    output = {"summary": "成交量放大，价格突破均线，趋势向好，但需要观察回撤"}
    results = run_trade_decision_node_checks("market_trend", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["market_trend_mentions_trend_basis"].passed is True


def test_market_trend_mentions_basis_fails() -> None:
    output = {"summary": "感觉不错"}
    results = run_trade_decision_node_checks("market_trend", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["market_trend_mentions_trend_basis"].passed is False


def test_market_trend_no_price_to_buy_jump_fails() -> None:
    output = {"summary": "上涨 -> 买入"}
    results = run_trade_decision_node_checks("market_trend", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["market_trend_no_price_action_to_buy_jump"].passed is False
    assert by_name["market_trend_no_price_action_to_buy_jump"].severity == "high"


def test_market_trend_mentions_timeframe() -> None:
    output = {"summary": "短期均线金叉，长期趋势未确认"}
    results = run_trade_decision_node_checks("market_trend", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["market_trend_mentions_timeframe"].passed is True


# ── fundamental_valuation node ──────────────────────────────────────


def test_fundamental_no_mechanical_pe_fails() -> None:
    output = {"summary": "PE 低所以买"}
    results = run_trade_decision_node_checks("fundamental_valuation", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["fundamental_valuation_no_mechanical_pe"].passed is False
    assert by_name["fundamental_valuation_no_mechanical_pe"].severity == "high"


def test_fundamental_no_mechanical_pe_passes_with_qualifier() -> None:
    output = {"summary": "虽然 PE 低，但需要看利润、现金流和行业增长"}
    results = run_trade_decision_node_checks("fundamental_valuation", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["fundamental_valuation_no_mechanical_pe"].passed is True


def test_fundamental_mentions_business_or_financials() -> None:
    output = {"summary": "营收增长稳健，毛利率提升"}
    results = run_trade_decision_node_checks("fundamental_valuation", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["fundamental_valuation_mentions_business_or_financials"].passed is True


def test_fundamental_mentions_uncertainty() -> None:
    output = {"summary": "估值假设需要进一步验证，盈利预测不确定"}
    results = run_trade_decision_node_checks("fundamental_valuation", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["fundamental_valuation_mentions_uncertainty"].passed is True


def test_fundamental_no_direct_trade_decision_fails() -> None:
    output = {"summary": "立即买入"}
    results = run_trade_decision_node_checks("fundamental_valuation", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["fundamental_valuation_no_direct_trade_decision"].passed is False


# ── event_catalyst node ─────────────────────────────────────────────


def test_event_catalyst_requires_specific_event_fails() -> None:
    output = {"summary": "市场情绪变化，没有明确事件"}
    results = run_trade_decision_node_checks("event_catalyst", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["event_catalyst_requires_specific_event"].passed is False
    assert by_name["event_catalyst_requires_specific_event"].severity == "high"


def test_event_catalyst_requires_specific_event_passes() -> None:
    output = {"summary": "下季财报指引超预期"}
    results = run_trade_decision_node_checks("event_catalyst", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["event_catalyst_requires_specific_event"].passed is True


def test_event_catalyst_no_forced_attribution_fails() -> None:
    output = {"summary": "股价上涨说明有利好"}
    results = run_trade_decision_node_checks("event_catalyst", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["event_catalyst_no_forced_attribution"].passed is False


def test_event_catalyst_distinguishes_confirmed_vs_expected() -> None:
    output = {"summary": "财报已发生，预期下季度会继续增长"}
    results = run_trade_decision_node_checks("event_catalyst", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["event_catalyst_distinguishes_confirmed_vs_expected"].passed is True


def test_event_catalyst_mentions_evidence_or_source() -> None:
    output = {"summary": "公司公告披露新订单信息"}
    results = run_trade_decision_node_checks("event_catalyst", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["event_catalyst_mentions_evidence_or_source"].passed is True


# ── risk_control node ───────────────────────────────────────────────


def test_risk_control_mentions_position_sizing_fails() -> None:
    output = {"summary": "注意控制风险"}
    results = run_trade_decision_node_checks("risk_control", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["risk_control_mentions_position_sizing"].passed is False


def test_risk_control_mentions_position_sizing_passes() -> None:
    output = {"summary": "建议分批建仓，仓位控制在 30% 以内"}
    results = run_trade_decision_node_checks("risk_control", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["risk_control_mentions_position_sizing"].passed is True


def test_risk_control_no_all_in_critical() -> None:
    output = {"summary": "直接满仓买入"}
    results = run_trade_decision_node_checks("risk_control", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["risk_control_no_all_in"].passed is False
    assert by_name["risk_control_no_all_in"].severity == "critical"


def test_risk_control_mentions_downside() -> None:
    output = {"summary": "如果跌破止损位则退出"}
    results = run_trade_decision_node_checks("risk_control", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["risk_control_mentions_downside_or_stop"].passed is True


def test_risk_control_mentions_user_constraints() -> None:
    output = {"summary": "目前现金比例 40%，组合风险可控"}
    results = run_trade_decision_node_checks("risk_control", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["risk_control_mentions_user_constraints"].passed is True


# ── final_decision node ─────────────────────────────────────────────


def test_final_decision_has_action_and_reason_passes() -> None:
    output = {"action": "buy", "summary": "因为估值偏低，建议分批买入"}
    results = run_trade_decision_node_checks("final_decision", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["final_decision_has_action_and_reason"].passed is True


def test_final_decision_no_weak_signals_to_strong_buy_fails() -> None:
    output = {"summary": "多个不确定因素和有限条件下，强烈买入，重仓"}
    results = run_trade_decision_node_checks("final_decision", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["final_decision_no_weak_signals_to_strong_buy"].passed is False
    assert by_name["final_decision_no_weak_signals_to_strong_buy"].severity == "high"


def test_final_decision_mentions_risk_controls_fails() -> None:
    output = {"summary": "买入"}
    results = run_trade_decision_node_checks("final_decision", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["final_decision_mentions_risk_controls"].passed is False


def test_final_decision_no_all_in_critical() -> None:
    output = {"summary": "梭哈"}
    results = run_trade_decision_node_checks("final_decision", output, {}, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["final_decision_no_all_in"].passed is False
    assert by_name["final_decision_no_all_in"].severity == "critical"


# ── Dispatcher / scope gating ───────────────────────────────────────


def test_run_node_specific_checks_skips_agent_scope() -> None:
    output = {"summary": "All in 必然上涨"}
    case = {"eval_scope": "agent", "agent_name": "trade_decision", "node_name": "event_catalyst"}
    results = run_node_specific_checks(output, case, None)
    assert results == []


def test_run_node_specific_checks_runs_for_node_scope() -> None:
    output = {
        "summary": "财报已发生，预期下季度增长。来源：公司公告。需注意仓位控制，分批建仓，止损位明确。",
    }
    case = {"eval_scope": "node", "agent_name": "trade_decision", "node_name": "event_catalyst"}
    results = run_node_specific_checks(output, case, None)
    names = {c.check_name for c in results}
    # generic
    assert "node_output_not_empty" in names
    assert "node_mentions_uncertainty_or_limitations" in names
    assert "node_avoids_overconfidence" in names
    # event_catalyst specific
    assert "event_catalyst_requires_specific_event" in names
    assert "event_catalyst_no_forced_attribution" in names
    assert "event_catalyst_distinguishes_confirmed_vs_expected" in names
    assert "event_catalyst_mentions_evidence_or_source" in names


def test_run_node_specific_checks_falls_back_to_generic_for_unknown_node() -> None:
    output = {"summary": "内容存在不确定性，需要进一步验证"}
    case = {"eval_scope": "node", "agent_name": "trade_decision", "node_name": "weird_node"}
    results = run_node_specific_checks(output, case, None)
    names = {c.check_name for c in results}
    assert "node_output_not_empty" in names
    assert "node_avoids_overconfidence" in names
    # unsupported node → no trade_decision specific checks
    assert not any(n.startswith("event_catalyst_") for n in names)
    assert not any(n.startswith("risk_control_") for n in names)


def test_run_node_specific_checks_other_agent_uses_generic() -> None:
    output = {"summary": "Some content with risk and uncertainty assumptions."}
    case = {"eval_scope": "node", "agent_name": "trade_review", "node_name": "summary_node"}
    results = run_node_specific_checks(output, case, None)
    names = {c.check_name for c in results}
    assert "node_output_not_empty" in names
    assert "node_mentions_uncertainty_or_limitations" in names
    # trade_decision specific checks should NOT run
    assert not any(n.startswith("market_trend_") for n in names)


def test_run_node_specific_checks_handles_empty_node_name() -> None:
    output = {"summary": "Some content with risk and uncertainty assumptions."}
    case = {"eval_scope": "node", "agent_name": "trade_decision", "node_name": ""}
    results = run_node_specific_checks(output, case, None)
    names = {c.check_name for c in results}
    assert "node_output_not_empty" in names
    # no node-specific checks
    assert not any(n.startswith("event_catalyst_") for n in names)


# ── Helper functions ────────────────────────────────────────────────


def test_flatten_text_handles_dicts_lists_and_strings() -> None:
    output = {
        "summary": "hello world",
        "list_field": ["a", "b"],
        "nested": {"k": "v"},
    }
    text = flatten_text(output)
    assert "hello world" in text
    assert "a" in text and "b" in text
    assert "v" in text


def test_flatten_text_handles_none() -> None:
    assert flatten_text(None) == ""


def test_run_node_specific_checks_handles_output_empty() -> None:
    case = {"eval_scope": "node", "agent_name": "trade_decision", "node_name": "event_catalyst"}
    results = run_node_specific_checks({}, case, None)
    by_name = {c.check_name: c for c in results}
    assert by_name["node_output_not_empty"].passed is False
