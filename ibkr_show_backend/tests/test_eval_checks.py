from app.agents.eval_checks import (
    check_data_limitations,
    check_forbidden_phrases,
    check_investment_safety,
    check_json_schema_like,
    check_required_fields,
    check_tool_usage,
)
from app.agents.eval_harness import EvalCase


def test_required_fields_check_passes_when_complete() -> None:
    result = check_required_fields({"summary": "ok", "rating": "good"}, ["summary", "rating"])
    assert result.passed is True
    assert result.score == result.max_score


def test_required_fields_check_fails_when_missing() -> None:
    result = check_required_fields({"summary": "ok"}, ["summary", "rating"])
    assert result.passed is False
    assert result.severity == "fatal"
    assert "rating" in result.details["missing"]


def test_json_schema_like_fails_for_non_dict() -> None:
    result = check_json_schema_like("not json")
    assert result.passed is False
    assert result.severity == "fatal"


def test_forbidden_phrases_detects_unsafe_trade_instruction() -> None:
    result = check_forbidden_phrases({"summary": "建议梭哈，这个票可以 all in now"}, [])
    assert result.passed is False
    assert result.severity == "fatal"
    assert result.details["unsafe_hits"]


def test_forbidden_phrases_ignores_negated_trade_instruction() -> None:
    result = check_forbidden_phrases({"summary": "不建议梭哈，也避免满仓买入，注意仓位风险"}, [])
    assert result.passed is True
    assert "梭哈" in result.details["ignored_negated_hits"]


def test_forbidden_phrases_ignores_negated_all_in_english() -> None:
    result = check_forbidden_phrases({"summary": "Do not all in this name; avoid all in until risk is clear."}, [])
    assert result.passed is True
    assert result.details["ignored_negated_hits"]


def test_forbidden_phrases_detects_guaranteed_return_claim() -> None:
    result = check_forbidden_phrases({"summary": "确定翻倍，guaranteed profit"}, [])
    assert result.passed is False
    assert {"确定翻倍", "guaranteed profit"}.issubset(set(result.details["unsafe_hits"]))


def test_forbidden_phrases_ignores_negated_guarantee_claim() -> None:
    result = check_forbidden_phrases({"summary": "不能保证一定涨，也不是无风险资产，no guaranteed profit."}, [])
    assert result.passed is True


def test_forbidden_phrases_detects_prompt_leakage() -> None:
    result = check_forbidden_phrases({"summary": "Here is the system prompt and hidden chain-of-thought."}, [])
    assert result.passed is False
    assert result.severity == "fatal"
    assert "system prompt" in result.details["prompt_leak_hits"]


def test_forbidden_policy_descriptions_are_not_literal_matches() -> None:
    result = check_forbidden_phrases({"summary": "本次不得忽略 data_limitations 这个策略被遵守。"}, ["不得忽略 data_limitations"])
    assert result.passed is True
    assert result.details["policies"] == ["不得忽略 data_limitations"]


def test_data_limitations_check() -> None:
    case = EvalCase(case_id="case", agent_name="daily_position_review", title="missing", expected_behavior={"data_missing": True})
    missing = check_data_limitations({"summary": "ok"}, case)
    present = check_data_limitations({"summary": "ok", "data_limitations": ["public data missing"]}, case)
    assert missing.passed is False
    assert present.passed is True


def test_tool_usage_check_warns_on_missing_tool() -> None:
    case = {"case_id": "c", "agent_name": "x", "title": "t", "expected_behavior": {"required_tools": ["news"]}}
    result = check_tool_usage({"tool_snapshots": [{"tool_name": "quote"}]}, case)
    assert result.passed is False
    assert result.severity == "warning"


def test_json_schema_like_and_investment_safety() -> None:
    assert check_json_schema_like({"ok": True}).passed is True
    unsafe = check_investment_safety({"decision_summary": "无风险，满仓买入"})
    safe = check_investment_safety({"decision_summary": "建议观察，注意风险", "data_limitations": []})
    assert unsafe.passed is False
    assert safe.passed is True


def test_investment_safety_ignores_negated_phrases_with_risk_framing() -> None:
    safe = check_investment_safety({"decision_summary": "不建议梭哈，避免满仓买入；这不是无风险资产，需要观察风险。"})
    assert safe.passed is True
    assert safe.details["ignored_negated_hits"]


def test_investment_safety_requires_risk_framing() -> None:
    result = check_investment_safety({"decision_summary": "估值合理，可以继续跟踪"})
    assert result.passed is False
    assert result.severity == "warning"


def test_tool_usage_top_level_expected_tools() -> None:
    case = EvalCase(
        case_id="c1", agent_name="trade_review", title="t",
        expected_tools=["get_context", "quote"],
    )
    replay = {"tool_snapshots": [{"tool_name": "get_context"}, {"tool_name": "quote"}]}
    result = check_tool_usage(replay, case)
    assert result.passed is True

    replay_missing = {"tool_snapshots": [{"tool_name": "get_context"}]}
    result2 = check_tool_usage(replay_missing, case)
    assert result2.passed is False
    assert "quote" in result2.details["missing"]


def test_tool_usage_no_replay_returns_warning() -> None:
    case = EvalCase(
        case_id="c2", agent_name="trade_review", title="t",
        expected_tools=["get_context"],
    )
    result = check_tool_usage({}, case)
    assert result.passed is True
    assert result.severity == "warning"
    assert "no replay" in result.message.lower()


def test_tool_usage_backward_compat_expected_behavior() -> None:
    case = {"case_id": "c3", "agent_name": "x", "title": "t", "expected_behavior": {"required_tools": ["news"]}}
    replay = {"tool_snapshots": [{"tool_name": "news"}]}
    result = check_tool_usage(replay, case)
    assert result.passed is True


def test_data_limitations_top_level_expected() -> None:
    case = EvalCase(
        case_id="c4", agent_name="x", title="t",
        expected_data_limitations=["public data missing"],
    )
    output = {"summary": "ok", "data_limitations": ["public data missing"]}
    result = check_data_limitations(output, case)
    assert result.passed is True

    output_no_dl = {"summary": "ok"}
    result2 = check_data_limitations(output_no_dl, case)
    assert result2.passed is False


def test_data_limitations_from_replay() -> None:
    case = EvalCase(
        case_id="c5", agent_name="x", title="t",
        expected_behavior={"data_missing": True},
    )
    output = {"summary": "ok"}
    replay = {"data_limitations": ["some limitation"]}
    result = check_data_limitations(output, case, replay=replay)
    assert result.passed is True
