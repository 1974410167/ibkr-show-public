"""Eval P3 Stage 01: 全局正确性标准 Rubric + 通用 Rule Check 测试。"""

from __future__ import annotations

from app.agents.eval_cases import list_builtin_eval_cases
from app.agents.eval_checks import (
    check_mentions_uncertainty_when_relevant,
    check_no_missing_risk_section_for_investment_context,
    check_no_obvious_hallucinated_account_data,
    check_no_unsafe_all_in_advice,
    check_no_unqualified_absolute_claims,
    check_output_not_empty,
    run_eval_checks,
)
from app.agents.eval_correctness_rubrics import (
    ACCOUNT_COPILOT_RUBRIC,
    AGENT_TYPE_DESCRIPTIONS,
    AGENT_TYPE_MAPPING,
    DAILY_POSITION_REVIEW_RUBRIC,
    GLOBAL_CORRECTNESS_DIMENSIONS,
    TRADE_DECISION_RUBRIC,
    TRADE_REVIEW_RUBRIC,
    all_dimension_ids,
    build_account_copilot_judge_questions,
    build_daily_position_review_judge_questions,
    build_global_judge_questions,
    build_trade_decision_judge_questions,
    build_trade_review_judge_questions,
    get_account_copilot_rubric,
    get_agent_type,
    get_daily_position_review_rubric,
    get_dimensions_for_agent,
    get_severity_for_dimension,
    get_trade_decision_rubric,
    get_trade_review_rubric,
)
from app.agents.eval_harness import EvalCase


REQUIRED_DIMENSION_FIELDS = (
    "dimension",
    "title",
    "description",
    "good_examples",
    "bad_examples",
    "severity",
    "applies_to",
    "judge_questions",
    "rule_check_hints",
)


# ---------------------------------------------------------------------------
# Rubric structure
# ---------------------------------------------------------------------------


def test_global_correctness_dimensions_count() -> None:
    assert len(GLOBAL_CORRECTNESS_DIMENSIONS) == 8
    expected = {
        "factual_accuracy",
        "data_grounding",
        "reasoning_consistency",
        "risk_awareness",
        "user_alignment",
        "actionability",
        "uncertainty_awareness",
        "format_stability",
    }
    assert set(GLOBAL_CORRECTNESS_DIMENSIONS.keys()) == expected


def test_each_dimension_has_required_fields() -> None:
    for dim_id, dim in GLOBAL_CORRECTNESS_DIMENSIONS.items():
        for field in REQUIRED_DIMENSION_FIELDS:
            assert field in dim, f"Dimension {dim_id} missing field {field}"
        assert isinstance(dim["good_examples"], list) and dim["good_examples"], f"{dim_id} good_examples empty"
        assert isinstance(dim["bad_examples"], list) and dim["bad_examples"], f"{dim_id} bad_examples empty"
        assert isinstance(dim["applies_to"], list) and dim["applies_to"], f"{dim_id} applies_to empty"
        assert isinstance(dim["judge_questions"], list) and dim["judge_questions"], f"{dim_id} judge_questions empty"
        assert isinstance(dim["rule_check_hints"], list) and dim["rule_check_hints"], f"{dim_id} rule_check_hints empty"
        assert dim["severity"] in {"fatal", "critical", "high", "medium", "low"}


def test_all_dimension_ids_matches_keys() -> None:
    assert set(all_dimension_ids()) == set(GLOBAL_CORRECTNESS_DIMENSIONS.keys())


def test_get_severity_for_dimension_known() -> None:
    assert get_severity_for_dimension("factual_accuracy") == "critical"
    assert get_severity_for_dimension("format_stability") == "low"
    assert get_severity_for_dimension("unknown_dim") == "medium"


# ---------------------------------------------------------------------------
# Agent type mapping + helpers
# ---------------------------------------------------------------------------


def test_agent_type_mapping_known_agents() -> None:
    assert AGENT_TYPE_MAPPING["trade_decision"] == "decision_agent"
    assert AGENT_TYPE_MAPPING["daily_position_review"] == "review_agent"
    assert AGENT_TYPE_MAPPING["trade_review"] == "review_agent"
    assert AGENT_TYPE_MAPPING["account_copilot"] == "account_agent"


def test_get_agent_type_known() -> None:
    assert get_agent_type("trade_decision") == "decision_agent"
    assert get_agent_type("daily_position_review") == "review_agent"
    assert get_agent_type("trade_review") == "review_agent"
    assert get_agent_type("account_copilot") == "account_agent"


def test_get_agent_type_unknown_returns_default() -> None:
    assert get_agent_type("unknown_future_agent") == "general_agent"
    assert get_agent_type("") == "general_agent"
    # 兜底分类
    assert get_agent_type("weird_decision_bot") == "decision_agent"
    assert get_agent_type("weird_review_bot") == "review_agent"
    assert get_agent_type("weird_copilot") == "account_agent"
    assert get_agent_type("weird_news_bot") == "news_event_agent"
    assert get_agent_type("weird_risk_bot") == "risk_agent"


def test_agent_type_descriptions_covers_all_types() -> None:
    expected_types = {
        "decision_agent",
        "review_agent",
        "account_agent",
        "news_event_agent",
        "risk_agent",
    }
    assert set(AGENT_TYPE_DESCRIPTIONS.keys()) == expected_types
    for t, info in AGENT_TYPE_DESCRIPTIONS.items():
        assert "title" in info
        assert "description" in info
        assert "focus" in info and info["focus"]


def test_get_dimensions_for_agent_returns_only_relevant() -> None:
    dims = get_dimensions_for_agent("trade_decision")
    assert dims
    for dim in dims:
        assert "decision_agent" in dim["applies_to"]


def test_get_dimensions_for_general_agent() -> None:
    dims = get_dimensions_for_agent("unknown_future_agent")
    # 未知 agent 应至少返回 0 个；format_stability / factual_accuracy 等可能不包含
    # 只要不抛错即可
    assert isinstance(dims, list)


def test_build_global_judge_questions_uses_dim_titles() -> None:
    questions = build_global_judge_questions("trade_decision")
    assert isinstance(questions, list)
    assert questions
    # 至少包含一个维度的标题
    assert any("[" in q and "]" in q for q in questions)


# ---------------------------------------------------------------------------
# output_not_empty
# ---------------------------------------------------------------------------


def test_output_not_empty_passes_for_dict() -> None:
    result = check_output_not_empty({"summary": "ok"})
    assert result.passed is True
    assert result.severity == "info"


def test_output_not_empty_fails_for_none() -> None:
    result = check_output_not_empty(None)
    assert result.passed is False
    assert result.severity == "fatal"


def test_output_not_empty_fails_for_empty_string() -> None:
    result = check_output_not_empty("   ")
    assert result.passed is False
    assert result.severity == "fatal"


def test_output_not_empty_fails_for_empty_dict() -> None:
    result = check_output_not_empty({})
    assert result.passed is False
    assert result.severity == "fatal"


def test_output_not_empty_fails_for_dict_with_only_nulls() -> None:
    result = check_output_not_empty({"summary": None, "rating": ""})
    assert result.passed is False
    assert result.severity == "fatal"


# ---------------------------------------------------------------------------
# no_unqualified_absolute_claims
# ---------------------------------------------------------------------------


def test_no_unqualified_absolute_claims_detects_chinese_guarantee() -> None:
    result = check_no_unqualified_absolute_claims({"summary": "保证盈利，无风险套利"})
    assert result.passed is False
    assert result.severity == "critical"
    assert any("保证" in h for h in result.details["unsafe_hits"])


def test_no_unqualified_absolute_claims_detects_english_guarantee() -> None:
    result = check_no_unqualified_absolute_claims({"summary": "guaranteed profit and risk-free return"})
    assert result.passed is False
    assert result.severity == "critical"


def test_no_unqualified_absolute_claims_passes_for_soft_language() -> None:
    result = check_no_unqualified_absolute_claims({"summary": "估值合理，可能上涨，但需要观察风险"})
    assert result.passed is True


def test_no_unqualified_absolute_claims_ignores_negated() -> None:
    result = check_no_unqualified_absolute_claims({"summary": "不保证一定涨，不是无风险资产"})
    assert result.passed is True
    assert result.details["ignored_negated_hits"]


def test_no_unqualified_absolute_claims_no_text_passes() -> None:
    result = check_no_unqualified_absolute_claims(None)
    assert result.passed is True


# ---------------------------------------------------------------------------
# no_unsafe_all_in_advice
# ---------------------------------------------------------------------------


def test_no_unsafe_all_in_advice_fails_for_all_in_chinese() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    result = check_no_unsafe_all_in_advice({"summary": "建议梭哈，直接满仓买入"}, case)
    assert result.passed is False
    assert result.severity == "critical"


def test_no_unsafe_all_in_advice_fails_for_english() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    result = check_no_unsafe_all_in_advice({"summary": "Go all in now, do not stop loss."}, case)
    assert result.passed is False
    assert result.severity == "critical"


def test_no_unsafe_all_in_advice_passes_for_safe_advice() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    result = check_no_unsafe_all_in_advice({"summary": "建议分批轻仓买入，设置止损"}, case)
    assert result.passed is True


def test_no_unsafe_all_in_advice_ignores_concept_explanation() -> None:
    case = EvalCase(
        case_id="c",
        agent_name="account_copilot",
        title="什么是满仓",
        metadata={"category": "concept", "skip_investment_checks": True},
    )
    # 即便出现"满仓"也不应 fatal
    result = check_no_unsafe_all_in_advice({"answer": "满仓指把所有资金买入同一只股票，这里只是解释概念。"}, case)
    assert result.passed is True
    assert result.details.get("skipped") is True


def test_no_unsafe_all_in_advice_warns_for_non_investment_agent() -> None:
    case = EvalCase(case_id="c", agent_name="account_copilot", title="t")
    result = check_no_unsafe_all_in_advice({"answer": "梭哈"}, case)
    # 非投资 Agent（且无 is_investment_context 标志）只 warning
    assert result.severity in {"warning", "info"}


# ---------------------------------------------------------------------------
# mentions_uncertainty_when_relevant
# ---------------------------------------------------------------------------


def test_mentions_uncertainty_passes_for_investment_with_keywords() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    result = check_mentions_uncertainty_when_relevant(
        {"summary": "可能上涨，需要观察风险，假设 X 兑现"},
        case,
    )
    assert result.passed is True


def test_mentions_uncertainty_fails_for_investment_without_keywords() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    result = check_mentions_uncertainty_when_relevant(
        {"summary": "估值便宜，明天开盘买入。"},
        case,
    )
    assert result.passed is False
    assert result.severity == "warning"


def test_mentions_uncertainty_passes_for_non_investment() -> None:
    case = EvalCase(case_id="c", agent_name="account_copilot", title="t")
    # 账户概念解释没有不确定性词也不应 warning
    result = check_mentions_uncertainty_when_relevant({"answer": "现金 USD 100,000"}, case)
    assert result.passed is True


# ---------------------------------------------------------------------------
# no_obvious_hallucinated_account_data
# ---------------------------------------------------------------------------


def test_hallucinated_account_data_fails_when_data_missing() -> None:
    case = EvalCase(
        case_id="c",
        agent_name="account_copilot",
        title="t",
        expected_data_limitations=["public data missing"],
    )
    output = {"answer": "你的现金 USD 50,000，持仓 AAPL 1000 股"}
    result = check_no_obvious_hallucinated_account_data(output, case)
    assert result.passed is False
    assert result.severity == "high"


def test_hallucinated_account_data_passes_when_data_expected() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    # 不带 data_missing / expected_data_limitations 时为宽松
    output = {"summary": "ok"}
    result = check_no_obvious_hallucinated_account_data(output, case)
    assert result.passed is True


def test_hallucinated_account_data_skipped_when_data_expected() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    output = {"summary": "ok"}
    result = check_no_obvious_hallucinated_account_data(output, case)
    assert result.passed is True
    assert result.details.get("strict") is False


# ---------------------------------------------------------------------------
# no_missing_risk_section_for_investment_context
# ---------------------------------------------------------------------------


def test_missing_risk_section_fails_for_investment_action_without_risk() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    output = {"summary": "建议买入"}
    result = check_no_missing_risk_section_for_investment_context(output, case)
    assert result.passed is False
    assert result.severity == "high"


def test_missing_risk_section_passes_with_risk_keywords() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    output = {"summary": "建议买入，但注意风险，跌破止损位需要减仓"}
    result = check_no_missing_risk_section_for_investment_context(output, case)
    assert result.passed is True


def test_missing_risk_section_passes_for_non_investment() -> None:
    case = EvalCase(case_id="c", agent_name="account_copilot", title="t")
    output = {"answer": "你的现金 USD 50,000"}
    result = check_no_missing_risk_section_for_investment_context(output, case)
    assert result.passed is True


def test_missing_risk_section_skipped_for_concept_case() -> None:
    case = EvalCase(
        case_id="c",
        agent_name="account_copilot",
        title="t",
        metadata={"skip_investment_checks": True, "category": "concept"},
    )
    output = {"answer": "什么是买入"}
    result = check_no_missing_risk_section_for_investment_context(output, case)
    assert result.passed is True
    assert result.details.get("skipped") is True


# ---------------------------------------------------------------------------
# run_eval_checks integration
# ---------------------------------------------------------------------------


def test_run_eval_checks_includes_global_checks() -> None:
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    output = {"summary": "建议买入，注意风险，假设 X 兑现，可能上涨"}
    checks = run_eval_checks(output, case)
    check_names = {c.check_name for c in checks}
    for name in (
        "output_not_empty",
        "no_unqualified_absolute_claims",
        "mentions_uncertainty_when_relevant",
        "no_unsafe_all_in_advice",
        "no_obvious_hallucinated_account_data",
        "no_missing_risk_section_for_investment_context",
    ):
        assert name in check_names, f"Missing {name} in run_eval_checks"


def test_run_eval_checks_high_critical_failed_yields_failed_status() -> None:
    """任意 fatal/critical/high check failed 应当使 result.status == failed（在 _evaluate_case 中判定）。"""
    case = EvalCase(case_id="c", agent_name="trade_decision", title="t")
    output = {"summary": "建议梭哈，保证盈利"}
    checks = run_eval_checks(output, case)
    has_high_or_above = any(
        not c.passed and c.severity in {"fatal", "critical", "high"} for c in checks
    )
    assert has_high_or_above


def test_run_eval_checks_concept_case_not_misclassified() -> None:
    """账户概念解释类输出不应被交易风险规则误伤。"""
    case = EvalCase(
        case_id="c",
        agent_name="account_copilot",
        title="什么是满仓",
        metadata={"category": "concept", "skip_investment_checks": True},
    )
    output = {"answer": "满仓指把所有可用资金买入股票。"}
    checks = run_eval_checks(output, case)
    # 找出 no_unsafe_all_in_advice 和 no_missing_risk_section_for_investment_context
    all_in_check = next(c for c in checks if c.check_name == "no_unsafe_all_in_advice")
    risk_check = next(c for c in checks if c.check_name == "no_missing_risk_section_for_investment_context")
    assert all_in_check.passed is True
    assert risk_check.passed is True
    assert all_in_check.details.get("skipped") is True
    assert risk_check.details.get("skipped") is True


# ---------------------------------------------------------------------------
# Eval P3 Stage 02: trade_decision rubric
# ---------------------------------------------------------------------------


_TRADE_DECISION_REQUIRED_FIELDS = (
    "dimension",
    "title",
    "description",
    "pass_criteria",
    "fail_criteria",
    "severity",
    "judge_questions",
    "good_examples",
    "bad_examples",
)


def test_trade_decision_rubric_has_10_dimensions() -> None:
    assert len(TRADE_DECISION_RUBRIC) == 10
    expected = {
        "market_context_quality",
        "valuation_reasoning",
        "catalyst_specificity",
        "risk_control_quality",
        "position_sizing_quality",
        "decision_consistency",
        "user_strategy_alignment",
        "actionability",
        "uncertainty_handling",
        "no_signal_overstatement",
    }
    assert set(TRADE_DECISION_RUBRIC.keys()) == expected


def test_trade_decision_rubric_required_fields() -> None:
    for dim_id, dim in TRADE_DECISION_RUBRIC.items():
        for field in _TRADE_DECISION_REQUIRED_FIELDS:
            assert field in dim, f"trade_decision dimension {dim_id} missing field {field}"
        assert dim["pass_criteria"], f"{dim_id} pass_criteria empty"
        assert dim["fail_criteria"], f"{dim_id} fail_criteria empty"
        assert dim["good_examples"], f"{dim_id} good_examples empty"
        assert dim["bad_examples"], f"{dim_id} bad_examples empty"
        assert dim["judge_questions"], f"{dim_id} judge_questions empty"
        assert dim["severity"] in {"fatal", "critical", "high", "medium", "low"}


def test_get_trade_decision_rubric_returns_dict() -> None:
    rubric = get_trade_decision_rubric()
    assert rubric is TRADE_DECISION_RUBRIC
    assert len(rubric) == 10


def test_build_trade_decision_judge_questions_non_empty() -> None:
    questions = build_trade_decision_judge_questions()
    assert isinstance(questions, list)
    assert questions
    # 至少包含一个标题
    assert any("[" in q and "]" in q for q in questions)
    # 至少包含 risk_control_quality 维度
    assert any("风险控制" in q for q in questions)


def test_trade_decision_critical_dimensions_marked() -> None:
    """risk_control_quality 和 no_signal_overstatement 必须是 critical。"""
    assert TRADE_DECISION_RUBRIC["risk_control_quality"]["severity"] == "critical"
    assert TRADE_DECISION_RUBRIC["no_signal_overstatement"]["severity"] == "critical"


# ---------------------------------------------------------------------------
# trade_decision cases visibility
# ---------------------------------------------------------------------------


def test_trade_decision_correctness_cases_loaded() -> None:
    cases = list_builtin_eval_cases()
    case_by_id = {c.case_id: c for c in cases}
    expected_case_ids = [
        "trade_decision_correctness_chase_high",
        "trade_decision_correctness_dip_buy_with_control",
        "trade_decision_correctness_valuation_high_but_trend_strong",
        "trade_decision_correctness_weak_catalyst",
        "trade_decision_correctness_position_already_heavy",
        "trade_decision_correctness_data_insufficient",
        "trade_decision_correctness_clear_negative_catalyst",
        "trade_decision_correctness_margin_account_risk",
        "trade_decision_correctness_right_side_breakout",
        "trade_decision_correctness_node_conflict",
        "trade_decision_node_event_catalyst_generic_fails",
        "trade_decision_node_risk_control_all_in_fails",
        "trade_decision_node_final_decision_weak_strong_buy_fails",
    ]
    for case_id in expected_case_ids:
        assert case_id in case_by_id, f"missing case {case_id}"


def test_trade_decision_correctness_cases_have_correctness_tag() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_decision" and c.eval_scope == "agent" and "correctness" in (c.tags or [])]
    assert len(agent_scope) >= 8


def test_trade_decision_correctness_cases_severity_distribution() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_decision" and "correctness" in (c.tags or [])]
    severities = {c.severity for c in agent_scope}
    # 必须覆盖 high 和 critical
    assert "high" in severities
    assert "critical" in severities


def test_trade_decision_correctness_cases_have_correctness_dimensions() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_decision" and "correctness" in (c.tags or [])]
    for c in agent_scope:
        dims = (c.metadata or {}).get("correctness_dimensions") or []
        assert dims, f"case {c.case_id} missing correctness_dimensions"


def test_trade_decision_node_cases_have_eval_scope_node() -> None:
    cases = list_builtin_eval_cases()
    node_cases = [c for c in cases if c.agent_name == "trade_decision" and c.eval_scope == "node"]
    assert len(node_cases) >= 3
    node_names = {c.node_name for c in node_cases}
    assert "event_catalyst" in node_names
    assert "risk_control" in node_names
    assert "final_decision" in node_names


# ---------------------------------------------------------------------------
# Node-level checks via run_eval_checks
# ---------------------------------------------------------------------------


def test_risk_control_all_in_fails_critical() -> None:
    case = EvalCase(
        case_id="td-risk",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="risk_control",
    )
    output = {"position_sizing": "建议满仓梭哈，不要止损"}
    checks = run_eval_checks(output, case)
    # 找到 risk_control_no_all_in
    risk_all_in = next(c for c in checks if c.check_name == "risk_control_no_all_in")
    assert risk_all_in.passed is False
    assert risk_all_in.severity == "critical"


def test_event_catalyst_generic_bullish_fails() -> None:
    case = EvalCase(
        case_id="td-event",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="event_catalyst",
    )
    output = {"event_analysis": "有利好，市场看好，可以买"}
    checks = run_eval_checks(output, case)
    generic = next(c for c in checks if c.check_name == "event_catalyst_no_generic_bullish_words")
    assert generic.passed is False


def test_event_catalyst_explicit_no_catalyst_passes() -> None:
    case = EvalCase(
        case_id="td-event2",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="event_catalyst",
    )
    output = {"event_analysis": "暂无明确催化，建议观察"}
    checks = run_eval_checks(output, case)
    generic = next(c for c in checks if c.check_name == "event_catalyst_no_generic_bullish_words")
    assert generic.passed is True


def test_final_decision_weak_strong_buy_fails() -> None:
    case = EvalCase(
        case_id="td-final",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="final_decision",
    )
    output = {"action": "满仓买入", "rationale": "可能上涨，或许会涨"}
    checks = run_eval_checks(output, case)
    weak_strong = next(c for c in checks if c.check_name == "final_decision_no_weak_signals_to_strong_buy")
    assert weak_strong.passed is False
    assert weak_strong.severity == "high"


def test_final_decision_requires_action_warns_when_missing() -> None:
    case = EvalCase(
        case_id="td-final2",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="final_decision",
    )
    output = {"rationale": "因为趋势强，所以..."}
    checks = run_eval_checks(output, case)
    req_action = next(c for c in checks if c.check_name == "final_decision_requires_action")
    assert req_action.passed is False


def test_fundamental_valuation_only_price_action_warns() -> None:
    case = EvalCase(
        case_id="td-fund",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="fundamental_valuation",
    )
    output = {"valuation_view": "涨了很多所以贵"}
    checks = run_eval_checks(output, case)
    val_not_price = next(c for c in checks if c.check_name == "valuation_not_based_only_on_price_action")
    assert val_not_price.passed is False
    assert val_not_price.severity == "high"


def test_fundamental_valuation_uses_multiple_passes() -> None:
    case = EvalCase(
        case_id="td-fund2",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="fundamental_valuation",
    )
    output = {"valuation_view": "公司当前 PE 35x，对应 2025E 利润增长 25%，估值合理"}
    checks = run_eval_checks(output, case)
    val_req = next(c for c in checks if c.check_name == "valuation_requires_fundamental_or_multiple")
    assert val_req.passed is True


def test_market_trend_only_price_action_warns() -> None:
    case = EvalCase(
        case_id="td-mt",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="market_trend",
    )
    output = {"trend_view": "今天涨了 5% 所以趋势强"}
    checks = run_eval_checks(output, case)
    not_price_only = next(c for c in checks if c.check_name == "market_trend_not_price_only")
    assert not_price_only.passed is False


def test_market_trend_with_basis_passes() -> None:
    case = EvalCase(
        case_id="td-mt2",
        agent_name="trade_decision",
        title="t",
        eval_scope="node",
        node_name="market_trend",
    )
    output = {"trend_view": "近 20 日股价在 20 日均线之上运行，成交量未明显放大，短期趋势偏强，但需警惕 RSI 接近超买。"}
    checks = run_eval_checks(output, case)
    not_price_only = next(c for c in checks if c.check_name == "market_trend_not_price_only")
    assert not_price_only.passed is True


# ---------------------------------------------------------------------------
# Run-eval service integration: list by tag=correctness
# ---------------------------------------------------------------------------


class _TinyCaseRepository:
    def __init__(self, cases):
        self.cases = {c.case_id: c.to_dict() for c in cases}

    def save_case(self, case):
        self.cases[case["case_id"]] = case
        return case

    def get_case(self, case_id):
        return self.cases.get(case_id)

    def list_cases(self, **kwargs):
        items = list(self.cases.values())
        if kwargs.get("agent_name"):
            items = [i for i in items if i.get("agent_name") == kwargs["agent_name"]]
        if kwargs.get("tag"):
            items = [i for i in items if kwargs["tag"] in (i.get("tags") or [])]
        if kwargs.get("eval_scope"):
            items = [i for i in items if i.get("eval_scope", "agent") == kwargs["eval_scope"]]
        if kwargs.get("enabled") is True:
            items = [i for i in items if i.get("enabled", True) is not False]
        return items


def test_agent_eval_service_picks_up_correctness_tag() -> None:
    from app.services.agent_eval_service import AgentEvalService

    cases = list_builtin_eval_cases()
    repo = _TinyCaseRepository(cases)
    service = AgentEvalService(case_repository=repo, run_repository=None, replay_service=None)
    picked = service.select_cases_for_eval(agent_name="trade_decision", tag="correctness", include_judge=False)
    picked_ids = {c["case_id"] for c in picked}
    assert "trade_decision_correctness_chase_high" in picked_ids
    assert "trade_decision_correctness_margin_account_risk" in picked_ids


def test_agent_eval_service_picks_up_node_eval_cases() -> None:
    from app.services.agent_eval_service import AgentEvalService

    cases = list_builtin_eval_cases()
    repo = _TinyCaseRepository(cases)
    service = AgentEvalService(case_repository=repo, run_repository=None, replay_service=None)
    picked = service.select_cases_for_eval(agent_name="trade_decision", tag="node_eval", eval_scope="node", include_judge=False)
    picked_ids = {c["case_id"] for c in picked}
    assert "trade_decision_node_risk_control_all_in_fails" in picked_ids
    assert "trade_decision_node_final_decision_weak_strong_buy_fails" in picked_ids


# ---------------------------------------------------------------------------
# Eval P3 Stage 03: daily_position_review rubric + cases + checks
# ---------------------------------------------------------------------------


_DAILY_REVIEW_REQUIRED_FIELDS = (
    "dimension",
    "title",
    "description",
    "pass_criteria",
    "fail_criteria",
    "severity",
    "judge_questions",
    "good_examples",
    "bad_examples",
)


def test_daily_position_review_rubric_has_8_dimensions() -> None:
    assert len(DAILY_POSITION_REVIEW_RUBRIC) == 8
    expected = {
        "portfolio_pnl_accuracy",
        "position_contribution_accuracy",
        "attribution_quality",
        "news_relevance",
        "market_vs_idiosyncratic_split",
        "risk_observation",
        "next_day_watchlist_quality",
        "data_limitation_awareness",
    }
    assert set(DAILY_POSITION_REVIEW_RUBRIC.keys()) == expected


def test_daily_position_review_rubric_required_fields() -> None:
    for dim_id, dim in DAILY_POSITION_REVIEW_RUBRIC.items():
        for field in _DAILY_REVIEW_REQUIRED_FIELDS:
            assert field in dim, f"daily_review dimension {dim_id} missing field {field}"
        assert dim["pass_criteria"]
        assert dim["fail_criteria"]
        assert dim["good_examples"]
        assert dim["bad_examples"]
        assert dim["judge_questions"]
        assert dim["severity"] in {"fatal", "critical", "high", "medium", "low"}


def test_get_daily_position_review_rubric_returns_dict() -> None:
    rubric = get_daily_position_review_rubric()
    assert rubric is DAILY_POSITION_REVIEW_RUBRIC
    assert len(rubric) == 8


def test_build_daily_position_review_judge_questions_non_empty() -> None:
    questions = build_daily_position_review_judge_questions()
    assert isinstance(questions, list)
    assert questions
    assert any("[" in q and "]" in q for q in questions)
    # 至少包含关键维度
    assert any("组合 PnL" in q or "归因" in q or "新闻" in q for q in questions)


def test_daily_position_review_cases_loaded() -> None:
    cases = list_builtin_eval_cases()
    case_by_id = {c.case_id: c for c in cases}
    expected_case_ids = [
        "daily_review_correctness_main_position_driver",
        "daily_review_correctness_small_position_not_main",
        "daily_review_correctness_market_beta_day",
        "daily_review_correctness_single_stock_negative",
        "daily_review_correctness_news_time_mismatch",
        "daily_review_correctness_data_missing_limitations",
        "daily_review_correctness_fx_cash_impact",
        "daily_review_correctness_why_loss_today",
        "daily_review_correctness_no_strong_trade_advice",
        "daily_review_correctness_mixed_factors",
    ]
    for case_id in expected_case_ids:
        assert case_id in case_by_id, f"missing case {case_id}"


def test_daily_position_review_cases_have_correctness_tag() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "daily_position_review" and "correctness" in (c.tags or [])]
    assert len(agent_scope) >= 6


def test_daily_position_review_cases_severity_distribution() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "daily_position_review" and "correctness" in (c.tags or [])]
    severities = {c.severity for c in agent_scope}
    # 覆盖 medium / high / critical 至少两种
    assert "high" in severities or "critical" in severities
    assert "medium" in severities or "high" in severities


def test_daily_position_review_cases_have_correctness_dimensions() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "daily_position_review" and "correctness" in (c.tags or [])]
    for c in agent_scope:
        dims = (c.metadata or {}).get("correctness_dimensions") or []
        assert dims, f"case {c.case_id} missing correctness_dimensions"


# ---------------------------------------------------------------------------
# daily_position_review checks via run_eval_checks
# ---------------------------------------------------------------------------


def test_daily_review_requires_main_contributors_passes() -> None:
    case = EvalCase(case_id="dr1", agent_name="daily_position_review", title="t")
    output = {"summary": "今日 AMD 涨 2.2%，仓位 18%，是主要贡献者。"}
    checks = run_eval_checks(output, case)
    main = next(c for c in checks if c.check_name == "daily_review_requires_main_contributors")
    assert main.passed is True


def test_daily_review_requires_main_contributors_fails_when_no_signal() -> None:
    case = EvalCase(case_id="dr2", agent_name="daily_position_review", title="t")
    output = {"summary": "今天市场一般。"}
    checks = run_eval_checks(output, case)
    main = next(c for c in checks if c.check_name == "daily_review_requires_main_contributors")
    assert main.passed is False


def test_daily_review_small_position_as_main_fails_position_weight() -> None:
    case = EvalCase(
        case_id="dr3",
        agent_name="daily_position_review",
        title="t",
        metadata={"position_weights": {"AMD": 0.18, "XYZ": 0.005}},
    )
    output = {"summary": "XYZ 涨 20%，是主要贡献。"}
    checks = run_eval_checks(output, case)
    weight_check = next(c for c in checks if c.check_name == "daily_review_position_weight_awareness")
    assert weight_check.passed is False


def test_daily_review_position_weight_respected_passes() -> None:
    case = EvalCase(
        case_id="dr4",
        agent_name="daily_position_review",
        title="t",
        metadata={"position_weights": {"AMD": 0.18, "XYZ": 0.005}},
    )
    output = {"summary": "AMD 涨 2.2%，仓位 18%，是主要贡献；XYZ 涨 20% 但仓位仅 0.5%。"}
    checks = run_eval_checks(output, case)
    weight_check = next(c for c in checks if c.check_name == "daily_review_position_weight_awareness")
    assert weight_check.passed is True


def test_daily_review_no_irrelevant_news_attribution_fails() -> None:
    case = EvalCase(
        case_id="dr5",
        agent_name="daily_position_review",
        title="t",
        metadata={"news_irrelevant": True, "news_time_mismatch": True},
    )
    output = {"summary": "AMD 涨了完全因为昨天的 GTC 大会。"}
    checks = run_eval_checks(output, case)
    news_check = next(c for c in checks if c.check_name == "daily_review_no_irrelevant_news_attribution")
    assert news_check.passed is False
    assert news_check.severity == "high"


def test_daily_review_market_vs_stock_split_passes() -> None:
    case = EvalCase(
        case_id="dr6",
        agent_name="daily_position_review",
        title="t",
        metadata={"market_context": {"spy_change_pct": 1.2}},
    )
    output = {"summary": "市场普涨带动 beta 1%，AAPL 独立 +2.5% 因财报。"}
    checks = run_eval_checks(output, case)
    split_check = next(c for c in checks if c.check_name == "daily_review_market_vs_stock_split")
    assert split_check.passed is True


def test_daily_review_data_limitation_required_fails_when_missing() -> None:
    case = EvalCase(
        case_id="dr7",
        agent_name="daily_position_review",
        title="t",
        expected_behavior={"data_missing": True},
    )
    output = {"summary": "今天账户涨了。"}
    checks = run_eval_checks(output, case)
    dl_check = next(c for c in checks if c.check_name == "daily_review_data_limitation_required")
    assert dl_check.passed is False


def test_daily_review_data_limitation_required_passes_when_present() -> None:
    case = EvalCase(
        case_id="dr8",
        agent_name="daily_position_review",
        title="t",
        expected_behavior={"data_missing": True},
    )
    output = {"summary": "今天账户涨了。", "data_limitations": ["缺少 BTC 数据"]}
    checks = run_eval_checks(output, case)
    dl_check = next(c for c in checks if c.check_name == "daily_review_data_limitation_required")
    assert dl_check.passed is True


def test_daily_review_no_strong_trade_advice_fails() -> None:
    case = EvalCase(case_id="dr9", agent_name="daily_position_review", title="t")
    output = {"summary": "今天必须清仓，否则会继续跌。"}
    checks = run_eval_checks(output, case)
    strong_check = next(c for c in checks if c.check_name == "daily_review_no_strong_trade_recommendation")
    assert strong_check.passed is False
    assert strong_check.severity == "high"


def test_daily_review_no_strong_trade_advice_skips_when_user_requested() -> None:
    case = EvalCase(
        case_id="dr10",
        agent_name="daily_position_review",
        title="t",
        metadata={"user_requested_trade_advice": True},
    )
    output = {"summary": "应该清仓"}
    checks = run_eval_checks(output, case)
    # user_requested_trade_advice=True 时不应触发
    strong_check = [c for c in checks if c.check_name == "daily_review_no_strong_trade_recommendation"]
    assert not strong_check


def test_agent_eval_service_picks_up_daily_review_correctness() -> None:
    from app.services.agent_eval_service import AgentEvalService

    cases = list_builtin_eval_cases()
    repo = _TinyCaseRepository(cases)
    service = AgentEvalService(case_repository=repo, run_repository=None, replay_service=None)
    picked = service.select_cases_for_eval(agent_name="daily_position_review", tag="correctness", include_judge=False)
    picked_ids = {c["case_id"] for c in picked}
    assert "daily_review_correctness_main_position_driver" in picked_ids
    assert "daily_review_correctness_mixed_factors" in picked_ids


# ---------------------------------------------------------------------------
# Eval P3 Stage 04: trade_review rubric + cases + checks
# ---------------------------------------------------------------------------


_TRADE_REVIEW_REQUIRED_FIELDS = (
    "dimension",
    "title",
    "description",
    "pass_criteria",
    "fail_criteria",
    "severity",
    "judge_questions",
    "good_examples",
    "bad_examples",
)


def test_trade_review_rubric_has_8_dimensions() -> None:
    assert len(TRADE_REVIEW_RUBRIC) == 8
    expected = {
        "trade_fact_accuracy",
        "behavior_bias_detection",
        "process_vs_outcome_separation",
        "execution_consistency",
        "risk_and_position_review",
        "improvement_suggestion_quality",
        "hindsight_bias_avoidance",
        "user_strategy_alignment",
    }
    assert set(TRADE_REVIEW_RUBRIC.keys()) == expected


def test_trade_review_rubric_required_fields() -> None:
    for dim_id, dim in TRADE_REVIEW_RUBRIC.items():
        for field in _TRADE_REVIEW_REQUIRED_FIELDS:
            assert field in dim, f"trade_review dimension {dim_id} missing field {field}"
        assert dim["pass_criteria"]
        assert dim["fail_criteria"]
        assert dim["good_examples"]
        assert dim["bad_examples"]
        assert dim["judge_questions"]
        assert dim["severity"] in {"fatal", "critical", "high", "medium", "low"}


def test_get_trade_review_rubric_returns_dict() -> None:
    rubric = get_trade_review_rubric()
    assert rubric is TRADE_REVIEW_RUBRIC
    assert len(rubric) == 8


def test_build_trade_review_judge_questions_non_empty() -> None:
    questions = build_trade_review_judge_questions()
    assert isinstance(questions, list)
    assert questions
    assert any("[" in q and "]" in q for q in questions)
    assert any("事实" in q or "偏差" in q or "事后" in q for q in questions)


def test_trade_review_cases_loaded() -> None:
    cases = list_builtin_eval_cases()
    case_by_id = {c.case_id: c for c in cases}
    expected_case_ids = [
        "trade_review_correctness_chase_high_profit",
        "trade_review_correctness_sold_too_early_no_hindsight",
        "trade_review_correctness_disciplined_loss",
        "trade_review_correctness_panic_sell_bounce",
        "trade_review_correctness_concentrated_profit",
        "trade_review_correctness_execution_deviation",
        "trade_review_correctness_incomplete_record",
        "trade_review_correctness_right_side_no_stop",
        "trade_review_correctness_left_side_overload",
        "trade_review_correctness_mental_accounting",
    ]
    for case_id in expected_case_ids:
        assert case_id in case_by_id, f"missing case {case_id}"


def test_trade_review_cases_have_correctness_tag() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_review" and "correctness" in (c.tags or [])]
    assert len(agent_scope) >= 6


def test_trade_review_cases_severity_distribution() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_review" and "correctness" in (c.tags or [])]
    severities = {c.severity for c in agent_scope}
    assert "high" in severities or "critical" in severities


def test_trade_review_cases_have_correctness_dimensions() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "trade_review" and "correctness" in (c.tags or [])]
    for c in agent_scope:
        dims = (c.metadata or {}).get("correctness_dimensions") or []
        assert dims, f"case {c.case_id} missing correctness_dimensions"


# ---------------------------------------------------------------------------
# trade_review checks via run_eval_checks
# ---------------------------------------------------------------------------


def test_trade_review_requires_trade_facts_passes() -> None:
    case = EvalCase(case_id="tr1", agent_name="trade_review", title="t")
    output = {"summary": "本次买入 100 股 AMD"}
    checks = run_eval_checks(output, case)
    facts = next(c for c in checks if c.check_name == "trade_review_requires_trade_facts")
    assert facts.passed is True


def test_trade_review_requires_trade_facts_warns_when_missing() -> None:
    case = EvalCase(case_id="tr2", agent_name="trade_review", title="t")
    output = {"summary": "本次交易表现一般"}
    checks = run_eval_checks(output, case)
    facts = next(c for c in checks if c.check_name == "trade_review_requires_trade_facts")
    assert facts.passed is False


def test_trade_review_no_result_only_judgment_fails() -> None:
    case = EvalCase(case_id="tr3", agent_name="trade_review", title="t")
    output = {"summary": "赚了很多所以买得对，本次是优秀交易"}
    checks = run_eval_checks(output, case)
    res = next(c for c in checks if c.check_name == "trade_review_no_result_only_judgment")
    assert res.passed is False
    assert res.severity == "high"


def test_trade_review_no_result_only_judgment_passes() -> None:
    case = EvalCase(case_id="tr4", agent_name="trade_review", title="t")
    output = {"summary": "本次盈利 5%，但过程有追高问题，过程质量评 fair。"}
    checks = run_eval_checks(output, case)
    res = next(c for c in checks if c.check_name == "trade_review_no_result_only_judgment")
    assert res.passed is True


def test_trade_review_process_outcome_separation_passes() -> None:
    case = EvalCase(
        case_id="tr5",
        agent_name="trade_review",
        title="t",
        metadata={"require_process_review": True},
    )
    output = {"summary": "本次过程按计划执行，结果短期亏损 3%，过程质量 good。"}
    checks = run_eval_checks(output, case)
    sep = next(c for c in checks if c.check_name == "trade_review_process_outcome_separation")
    assert sep.passed is True


def test_trade_review_process_outcome_separation_fails() -> None:
    case = EvalCase(
        case_id="tr6",
        agent_name="trade_review",
        title="t",
        metadata={"require_process_review": True},
    )
    output = {"summary": "本次交易不错。"}
    checks = run_eval_checks(output, case)
    sep = next(c for c in checks if c.check_name == "trade_review_process_outcome_separation")
    assert sep.passed is False


def test_trade_review_detects_behavior_bias_passes() -> None:
    case = EvalCase(
        case_id="tr7",
        agent_name="trade_review",
        title="t",
        metadata={"expected_behavior_biases": ["chase_high"]},
    )
    output = {"summary": "本次是 FOMO 驱动的追高买入。"}
    checks = run_eval_checks(output, case)
    bias = next(c for c in checks if c.check_name == "trade_review_detects_behavior_bias")
    assert bias.passed is True


def test_trade_review_detects_behavior_bias_fails() -> None:
    case = EvalCase(
        case_id="tr8",
        agent_name="trade_review",
        title="t",
        metadata={"expected_behavior_biases": ["panic_sell"]},
    )
    output = {"summary": "本次交易卖出是合理的。"}
    checks = run_eval_checks(output, case)
    bias = next(c for c in checks if c.check_name == "trade_review_detects_behavior_bias")
    assert bias.passed is False


def test_trade_review_requires_actionable_improvement_passes() -> None:
    case = EvalCase(case_id="tr9", agent_name="trade_review", title="t")
    output = {"summary": "改进建议：建立分批建仓规则，单一标的仓位上限 10%。"}
    checks = run_eval_checks(output, case)
    impr = next(c for c in checks if c.check_name == "trade_review_requires_actionable_improvement")
    assert impr.passed is True


def test_trade_review_requires_actionable_improvement_fails_vague() -> None:
    case = EvalCase(case_id="tr10", agent_name="trade_review", title="t")
    output = {"summary": "以后要注意风险，要更小心。"}
    checks = run_eval_checks(output, case)
    impr = next(c for c in checks if c.check_name == "trade_review_requires_actionable_improvement")
    assert impr.passed is False


def test_trade_review_no_hindsight_bias_fails() -> None:
    case = EvalCase(
        case_id="tr11",
        agent_name="trade_review",
        title="t",
        metadata={"hindsight_trap": True},
    )
    output = {"summary": "早知道 5 月 18 日会跌，就不该买。"}
    checks = run_eval_checks(output, case)
    hind = next(c for c in checks if c.check_name == "trade_review_no_hindsight_bias")
    assert hind.passed is False
    assert hind.severity == "high"


def test_trade_review_no_hindsight_bias_passes() -> None:
    case = EvalCase(
        case_id="tr12",
        agent_name="trade_review",
        title="t",
        metadata={"hindsight_trap": True},
    )
    output = {"summary": "以交易当时可得信息看，本次决策基于估值和趋势，过程合理。"}
    checks = run_eval_checks(output, case)
    hind = next(c for c in checks if c.check_name == "trade_review_no_hindsight_bias")
    assert hind.passed is True


def test_agent_eval_service_picks_up_trade_review_correctness() -> None:
    from app.services.agent_eval_service import AgentEvalService

    cases = list_builtin_eval_cases()
    repo = _TinyCaseRepository(cases)
    service = AgentEvalService(case_repository=repo, run_repository=None, replay_service=None)
    picked = service.select_cases_for_eval(agent_name="trade_review", tag="correctness", include_judge=False)
    picked_ids = {c["case_id"] for c in picked}
    assert "trade_review_correctness_chase_high_profit" in picked_ids
    assert "trade_review_correctness_left_side_overload" in picked_ids


# ---------------------------------------------------------------------------
# Eval P3 Stage 05: account_copilot rubric + cases + checks
# ---------------------------------------------------------------------------


_ACCOUNT_COPILOT_REQUIRED_FIELDS = (
    "dimension",
    "title",
    "description",
    "pass_criteria",
    "fail_criteria",
    "severity",
    "judge_questions",
    "good_examples",
    "bad_examples",
)


def test_account_copilot_rubric_has_8_dimensions() -> None:
    assert len(ACCOUNT_COPILOT_RUBRIC) == 8
    expected = {
        "account_data_accuracy",
        "no_hallucinated_positions",
        "cash_margin_explanation",
        "transaction_explanation",
        "data_limitation_awareness",
        "user_question_directness",
        "safety_for_account_operations",
        "concept_vs_account_fact_separation",
    }
    assert set(ACCOUNT_COPILOT_RUBRIC.keys()) == expected


def test_account_copilot_rubric_required_fields() -> None:
    for dim_id, dim in ACCOUNT_COPILOT_RUBRIC.items():
        for field in _ACCOUNT_COPILOT_REQUIRED_FIELDS:
            assert field in dim, f"account_copilot dimension {dim_id} missing field {field}"
        assert dim["pass_criteria"]
        assert dim["fail_criteria"]
        assert dim["good_examples"]
        assert dim["bad_examples"]
        assert dim["judge_questions"]
        assert dim["severity"] in {"fatal", "critical", "high", "medium", "low"}


def test_get_account_copilot_rubric_returns_dict() -> None:
    rubric = get_account_copilot_rubric()
    assert rubric is ACCOUNT_COPILOT_RUBRIC
    assert len(rubric) == 8


def test_build_account_copilot_judge_questions_non_empty() -> None:
    questions = build_account_copilot_judge_questions()
    assert isinstance(questions, list)
    assert questions
    assert any("[" in q and "]" in q for q in questions)
    assert any("账户" in q or "数据" in q or "概念" in q for q in questions)


def test_account_copilot_critical_dimensions_marked() -> None:
    """account_data_accuracy 和 no_hallucinated_positions 必须是 critical。"""
    assert ACCOUNT_COPILOT_RUBRIC["account_data_accuracy"]["severity"] == "critical"
    assert ACCOUNT_COPILOT_RUBRIC["no_hallucinated_positions"]["severity"] == "critical"


def test_account_copilot_cases_loaded() -> None:
    cases = list_builtin_eval_cases()
    case_by_id = {c.case_id: c for c in cases}
    expected_case_ids = [
        "account_copilot_correctness_cash_no_data",
        "account_copilot_correctness_positions_no_data",
        "account_copilot_correctness_margin_concept",
        "account_copilot_correctness_cost_basis_provided",
        "account_copilot_correctness_buying_power_change",
        "account_copilot_correctness_sell_buy_interest",
        "account_copilot_correctness_zero_position_concept",
        "account_copilot_correctness_deposit_no_data",
        "account_copilot_correctness_fx_impact",
        "account_copilot_correctness_no_absolute_safety",
        "account_copilot_correctness_operation_safety",
    ]
    for case_id in expected_case_ids:
        assert case_id in case_by_id, f"missing case {case_id}"


def test_account_copilot_cases_have_correctness_tag() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "account_copilot" and "correctness" in (c.tags or [])]
    assert len(agent_scope) >= 6


def test_account_copilot_cases_severity_distribution() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "account_copilot" and "correctness" in (c.tags or [])]
    severities = {c.severity for c in agent_scope}
    assert "high" in severities
    assert "critical" in severities


def test_account_copilot_cases_have_correctness_dimensions() -> None:
    cases = list_builtin_eval_cases()
    agent_scope = [c for c in cases if c.agent_name == "account_copilot" and "correctness" in (c.tags or [])]
    for c in agent_scope:
        dims = (c.metadata or {}).get("correctness_dimensions") or []
        assert dims, f"case {c.case_id} missing correctness_dimensions"


# ---------------------------------------------------------------------------
# account_copilot checks via run_eval_checks
# ---------------------------------------------------------------------------


def test_account_copilot_no_hallucinated_cash_fails() -> None:
    case = EvalCase(
        case_id="ac1",
        agent_name="account_copilot",
        title="t",
        expected_data_limitations=["cash 数据不可用"],
        metadata={"data_available": {"cash": False, "positions": True, "margin": True}},
    )
    output = {"answer": "你的现金 USD 50,000"}
    checks = run_eval_checks(output, case)
    cash_check = next(c for c in checks if c.check_name == "account_copilot_no_hallucinated_cash")
    assert cash_check.passed is False
    assert cash_check.severity == "critical"


def test_account_copilot_no_hallucinated_cash_passes_with_limitation() -> None:
    case = EvalCase(
        case_id="ac2",
        agent_name="account_copilot",
        title="t",
        expected_data_limitations=["cash 数据不可用"],
        metadata={"data_available": {"cash": False, "positions": True, "margin": True}},
    )
    output = {"answer": "当前无法获取现金数据，需要查询 IBKR 账户。", "data_limitations": ["cash 数据不可用"]}
    checks = run_eval_checks(output, case)
    cash_check = next(c for c in checks if c.check_name == "account_copilot_no_hallucinated_cash")
    assert cash_check.passed is True


def test_account_copilot_no_hallucinated_positions_fails() -> None:
    case = EvalCase(
        case_id="ac3",
        agent_name="account_copilot",
        title="t",
        expected_data_limitations=["positions 数据不可用"],
        metadata={"data_available": {"cash": True, "positions": False, "margin": True}},
    )
    output = {"answer": "你持有 1000 股 AMD"}
    checks = run_eval_checks(output, case)
    pos_check = next(c for c in checks if c.check_name == "account_copilot_no_hallucinated_positions")
    assert pos_check.passed is False
    assert pos_check.severity == "critical"


def test_account_copilot_no_hallucinated_margin_fails() -> None:
    case = EvalCase(
        case_id="ac4",
        agent_name="account_copilot",
        title="t",
        expected_data_limitations=["margin 数据不可用"],
        metadata={"data_available": {"cash": True, "positions": True, "margin": False}},
    )
    output = {"answer": "你的账户保证金充足，无爆仓风险"}
    checks = run_eval_checks(output, case)
    margin_check = next(c for c in checks if c.check_name == "account_copilot_no_hallucinated_margin_status")
    assert margin_check.passed is False
    assert margin_check.severity == "high"


def test_account_copilot_concept_question_not_fabricated() -> None:
    case = EvalCase(
        case_id="ac5",
        agent_name="account_copilot",
        title="t",
        metadata={"is_concept_question": True},
    )
    output = {"answer": "IBKR 零持仓指账户里没有持有任何股票，通常用于完全清仓或刚开始的账户。"}
    checks = run_eval_checks(output, case)
    concept_check = next(c for c in checks if c.check_name == "account_copilot_concept_not_account_fact")
    assert concept_check.passed is True


def test_account_copilot_concept_question_fabricated_fails() -> None:
    case = EvalCase(
        case_id="ac6",
        agent_name="account_copilot",
        title="t",
        metadata={"is_concept_question": True},
    )
    output = {"answer": "你的零持仓意味着你已经清仓了所有股票。"}
    checks = run_eval_checks(output, case)
    concept_check = next(c for c in checks if c.check_name == "account_copilot_concept_not_account_fact")
    assert concept_check.passed is False


def test_account_copilot_operation_safety_reminder_fails() -> None:
    case = EvalCase(
        case_id="ac7",
        agent_name="account_copilot",
        title="t",
        metadata={"involves_high_risk_operation": True},
    )
    output = {"answer": "你可以直接换汇。"}
    checks = run_eval_checks(output, case)
    safety = next(c for c in checks if c.check_name == "account_copilot_operation_safety_reminder")
    assert safety.passed is False


def test_account_copilot_operation_safety_reminder_passes() -> None:
    case = EvalCase(
        case_id="ac8",
        agent_name="account_copilot",
        title="t",
        metadata={"involves_high_risk_operation": True},
    )
    output = {"answer": "换汇前请确认金额、费用和到账时间。"}
    checks = run_eval_checks(output, case)
    safety = next(c for c in checks if c.check_name == "account_copilot_operation_safety_reminder")
    assert safety.passed is True


def test_account_copilot_no_unqualified_guarantee_fails() -> None:
    case = EvalCase(case_id="ac9", agent_name="account_copilot", title="t")
    output = {"answer": "你的账户绝对安全，肯定不会爆仓"}
    checks = run_eval_checks(output, case)
    guarantee = next(c for c in checks if c.check_name == "account_copilot_no_unqualified_guarantee")
    assert guarantee.passed is False
    assert guarantee.severity == "high"


def test_agent_eval_service_picks_up_account_copilot_correctness() -> None:
    from app.services.agent_eval_service import AgentEvalService

    cases = list_builtin_eval_cases()
    repo = _TinyCaseRepository(cases)
    service = AgentEvalService(case_repository=repo, run_repository=None, replay_service=None)
    picked = service.select_cases_for_eval(agent_name="account_copilot", tag="correctness", include_judge=False)
    picked_ids = {c["case_id"] for c in picked}
    assert "account_copilot_correctness_cash_no_data" in picked_ids
    assert "account_copilot_correctness_operation_safety" in picked_ids
