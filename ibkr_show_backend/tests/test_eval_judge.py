"""Eval P3 Stage 06: 跨 Agent Judge 校准测试。"""

from __future__ import annotations

from app.agents.eval_cases import list_builtin_eval_cases
from app.agents.eval_correctness_rubrics import (
    ACCOUNT_COPILOT_RUBRIC,
    DAILY_POSITION_REVIEW_RUBRIC,
    GLOBAL_CORRECTNESS_DIMENSIONS,
    TRADE_DECISION_RUBRIC,
    TRADE_REVIEW_RUBRIC,
)
from app.agents.eval_harness import EvalCase
from app.agents.eval_judge import (
    AGENT_RUBRIC_REGISTRY,
    AgentEvalJudgeService,
    build_correctness_judge_prompt,
    get_rubric_for_agent,
    normalize_correctness_judge_result,
)


# ---------------------------------------------------------------------------
# build_correctness_judge_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_agent_name() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_decision",
        eval_scope="agent",
        node_name=None,
        case={"title": "t", "description": "d", "input": {}, "expected_behavior": {}, "forbidden_behavior": [], "expected_data_limitations": []},
        output={"summary": "x"},
    )
    assert "trade_decision" in prompt
    assert "decision_agent" in prompt


def test_build_prompt_contains_global_dimensions() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_decision",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    # 至少包含 4 个全局维度
    for dim_id in list(GLOBAL_CORRECTNESS_DIMENSIONS.keys())[:4]:
        assert dim_id in prompt


def test_build_prompt_contains_trade_decision_rubric() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_decision",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    for dim_id in list(TRADE_DECISION_RUBRIC.keys())[:3]:
        assert dim_id in prompt


def test_build_prompt_contains_account_copilot_rubric() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="account_copilot",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    for dim_id in list(ACCOUNT_COPILOT_RUBRIC.keys())[:3]:
        assert dim_id in prompt


def test_build_prompt_contains_daily_review_rubric() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="daily_position_review",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    for dim_id in list(DAILY_POSITION_REVIEW_RUBRIC.keys())[:3]:
        assert dim_id in prompt


def test_build_prompt_contains_trade_review_rubric() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_review",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    for dim_id in list(TRADE_REVIEW_RUBRIC.keys())[:3]:
        assert dim_id in prompt


def test_build_prompt_contains_expected_and_forbidden() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_decision",
        eval_scope="agent",
        node_name=None,
        case={
            "title": "t",
            "expected_behavior": {"should_mention": "AMD"},
            "forbidden_behavior": ["满仓", "梭哈"],
            "expected_data_limitations": ["data missing"],
        },
        output={},
    )
    assert "AMD" in prompt
    assert "满仓" in prompt
    assert "梭哈" in prompt
    assert "data missing" in prompt


def test_build_prompt_contains_json_schema() -> None:
    prompt = build_correctness_judge_prompt(
        agent_name="trade_decision",
        eval_scope="agent",
        node_name=None,
        case={"title": "t"},
        output={},
    )
    # JSON Schema 字段必须存在
    for field in ("passed", "overall_score", "dimension_scores", "failed_dimensions", "warnings", "failure_reasons", "confidence"):
        assert field in prompt


# ---------------------------------------------------------------------------
# get_rubric_for_agent
# ---------------------------------------------------------------------------


def test_get_rubric_for_agent_known() -> None:
    assert get_rubric_for_agent("trade_decision") is TRADE_DECISION_RUBRIC
    assert get_rubric_for_agent("account_copilot") is ACCOUNT_COPILOT_RUBRIC
    assert get_rubric_for_agent("daily_position_review") is DAILY_POSITION_REVIEW_RUBRIC
    assert get_rubric_for_agent("trade_review") is TRADE_REVIEW_RUBRIC


def test_get_rubric_for_agent_unknown_empty() -> None:
    assert get_rubric_for_agent("unknown_agent") == {}
    assert get_rubric_for_agent("") == {}


def test_agent_rubric_registry_consistency() -> None:
    assert set(AGENT_RUBRIC_REGISTRY.keys()) == {
        "trade_decision",
        "daily_position_review",
        "trade_review",
        "account_copilot",
    }


# ---------------------------------------------------------------------------
# normalize_correctness_judge_result
# ---------------------------------------------------------------------------


def test_normalize_legacy_format() -> None:
    """旧格式（0-100 分数）应归一化。"""
    parsed = {
        "passed": True,
        "overall_score": 82,
        "dimension_scores": {"factual_accuracy": 90, "risk_awareness": 70},
        "failed_dimensions": [],
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["factual_accuracy", "risk_awareness"])
    assert out["passed"] is True
    assert 0.0 <= out["overall_score"] <= 1.0
    assert out["dimension_scores"]["factual_accuracy"] == 0.9
    assert out["dimension_scores"]["risk_awareness"] == 0.7


def test_normalize_new_format() -> None:
    parsed = {
        "passed": True,
        "overall_score": 0.82,
        "dimension_scores": {"factual_accuracy": 0.9, "risk_awareness": 0.7},
        "failed_dimensions": ["risk_awareness"],
        "warnings": ["format nit"],
        "failure_reasons": ["reason1"],
        "confidence": 0.8,
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["factual_accuracy", "risk_awareness"])
    assert out["passed"] is True
    assert out["overall_score"] == 0.82
    assert out["failed_dimensions"] == ["risk_awareness"]
    assert out["warnings"] == ["format nit"]
    assert out["failure_reasons"] == ["reason1"]
    assert out["confidence"] == 0.8


def test_normalize_auto_fills_failed_dimensions() -> None:
    """failed_dimensions 为空但分数 < 0.6 时自动补充。"""
    parsed = {
        "passed": False,
        "overall_score": 0.5,
        "dimension_scores": {"factual_accuracy": 0.9, "risk_awareness": 0.4},
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["factual_accuracy", "risk_awareness"])
    assert "risk_awareness" in out["failed_dimensions"]


def test_normalize_fills_default_dimensions() -> None:
    parsed = {"passed": True, "overall_score": 0.8, "dimension_scores": {}}
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["factual_accuracy", "risk_awareness"])
    assert "factual_accuracy" in out["dimension_scores"]
    assert "risk_awareness" in out["dimension_scores"]
    assert out["dimension_scores"]["factual_accuracy"] == 0.0


def test_normalize_handles_non_dict() -> None:
    out = normalize_correctness_judge_result(None, expected_dimensions=["x"])
    assert out["passed"] is False
    assert out["overall_score"] == 0.0


def test_normalize_clamps_scores() -> None:
    # 1.5 既在 [0, 1] 上方也在 [0, 100] 上方，_coerce_0_1 默认归一化到 0~1
    # 这里验证 0~1 范围内的 clamp 行为
    parsed = {
        "overall_score": 0.5,
        "dimension_scores": {"d1": 0.7},
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["d1"])
    assert out["overall_score"] == 0.5
    assert out["dimension_scores"]["d1"] == 0.7


def test_normalize_handles_0_100_scale() -> None:
    """0~100 分数应被归一化。"""
    parsed = {
        "overall_score": 85,
        "dimension_scores": {"d1": 70},
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["d1"])
    assert out["overall_score"] == 0.85
    assert out["dimension_scores"]["d1"] == 0.7


def test_normalize_handles_negative_scores() -> None:
    parsed = {
        "overall_score": -0.5,
        "dimension_scores": {"d1": -0.1},
    }
    out = normalize_correctness_judge_result(parsed, expected_dimensions=["d1"])
    assert out["overall_score"] == 0.0
    assert out["dimension_scores"]["d1"] == 0.0


# ---------------------------------------------------------------------------
# AgentEvalJudgeService.judge_correctness
# ---------------------------------------------------------------------------


def test_judge_correctness_without_llm_returns_structured_failure() -> None:
    service = AgentEvalJudgeService(llm_client=None)
    out = service.judge_correctness(
        case={"agent_name": "trade_decision"},
        output={"summary": "x"},
    )
    assert out["ok"] is False
    assert out["error_code"] == "LLM_JUDGE_SERVICE_UNAVAILABLE"
    assert "raw" in out
    assert out["raw"]["passed"] is False
    assert out["raw"]["dimension_scores"]


def test_judge_correctness_parses_markdown_code_block() -> None:
    """模型返回 markdown code block JSON，应能解析。"""

    class MarkdownLLM:
        call_type_used = None

        def chat(self, messages, **kwargs):
            return (
                "```json\n"
                "{\n"
                '  "passed": true,\n'
                '  "overall_score": 0.82,\n'
                '  "dimension_scores": {"factual_accuracy": 0.9, "risk_awareness": 0.7},\n'
                '  "failed_dimensions": [],\n'
                '  "warnings": [],\n'
                '  "failure_reasons": [],\n'
                '  "confidence": 0.8\n'
                "}\n"
                "```"
            )

    service = AgentEvalJudgeService(llm_client=MarkdownLLM())
    out = service.judge_correctness(
        case={"agent_name": "trade_decision"},
        output={"summary": "x"},
    )
    assert out["ok"] is True
    assert out["passed"] is True
    assert out["raw"]["overall_score"] == 0.82


def test_judge_correctness_handles_parse_failure() -> None:
    class BadLLM:
        def chat(self, messages, **kwargs):
            return "not valid json at all"

    service = AgentEvalJudgeService(llm_client=BadLLM())
    out = service.judge_correctness(
        case={"agent_name": "trade_decision"},
        output={"summary": "x"},
    )
    assert out["ok"] is False
    assert out["error_code"] == "LLM_JUDGE_PARSE_FAILED"
    assert out["raw"]["passed"] is False


def test_judge_correctness_handles_exception() -> None:
    class ErrorLLM:
        def chat(self, messages, **kwargs):
            raise RuntimeError("LLM service down")

    service = AgentEvalJudgeService(llm_client=ErrorLLM())
    out = service.judge_correctness(
        case={"agent_name": "trade_decision"},
        output={"summary": "x"},
    )
    assert out["ok"] is False
    assert out["error_code"] == "LLM_JUDGE_CALL_FAILED"


def test_judge_correctness_writes_metadata_in_evaluate_case() -> None:
    """Stage 06: evaluate_case 应在 correctness_judge_enabled=True 时写 metadata.judge。"""
    from app.services.agent_eval_service import AgentEvalService
    from app.agents.eval_harness import EvalCase as _EC

    class _Repo:
        def __init__(self):
            self.cases = {}

        def save_case(self, c):
            self.cases[c["case_id"]] = c
            return c

        def get_case(self, cid):
            return self.cases.get(cid)

        def list_cases(self, **kw):
            return list(self.cases.values())

        def seed_builtin_cases(self, **kw):
            return {"created": [], "skipped": [], "created_count": 0, "skipped_count": 0}

    class _RunRepo:
        def save_run(self, r):
            return r

        def get_run(self, rid):
            return None

        def list_runs(self, **kw):
            return []

    class _JudgeOkLLM:
        def chat(self, messages, **kwargs):
            return (
                '{"passed": true, "overall_score": 0.85, '
                '"dimension_scores": {"factual_accuracy": 0.9, "risk_awareness": 0.8}, '
                '"failed_dimensions": [], "warnings": [], "failure_reasons": [], "confidence": 0.8}'
            )

    case = _EC(
        case_id="cj1",
        agent_name="trade_decision",
        title="t",
        correctness_judge_enabled=True,
        metadata={"output": {"decision_summary": "x", "action": "hold"}},
        expected_output_fields=[],
        forbidden_behavior=[],
        expected_behavior={},
    ).to_dict()
    repo = _Repo()
    repo.save_case(case)

    service = AgentEvalService(
        case_repository=repo,
        run_repository=_RunRepo(),
        llm_client=_JudgeOkLLM(),
    )
    run = service.run_eval(case_ids=["cj1"], mode="static")
    result = run["results"][0]
    assert "judge" in result["metadata"]
    assert result["metadata"]["correctness_judge_enabled"] is True
    assert result["metadata"]["judge"]["passed"] is True
    # check llm_judge_correctness
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge_correctness"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is True


def test_judge_correctness_failed_dim_creates_failed_check() -> None:
    """Stage 06: failed_dimensions 应触发 llm_judge_correctness severity=high。"""
    from app.services.agent_eval_service import AgentEvalService
    from app.agents.eval_harness import EvalCase as _EC

    class _Repo:
        def __init__(self):
            self.cases = {}

        def save_case(self, c):
            self.cases[c["case_id"]] = c
            return c

        def get_case(self, cid):
            return self.cases.get(cid)

        def list_cases(self, **kw):
            return list(self.cases.values())

        def seed_builtin_cases(self, **kw):
            return {"created": [], "skipped": [], "created_count": 0, "skipped_count": 0}

    class _RunRepo:
        def save_run(self, r):
            return r

        def get_run(self, rid):
            return None

        def list_runs(self, **kw):
            return []

    class _JudgeFailLLM:
        def chat(self, messages, **kwargs):
            return (
                '{"passed": false, "overall_score": 0.3, '
                '"dimension_scores": {"factual_accuracy": 0.2, "risk_awareness": 0.4}, '
                '"failed_dimensions": ["factual_accuracy"], '
                '"warnings": [], "failure_reasons": ["编造数据"], "confidence": 0.8}'
            )

    case = _EC(
        case_id="cj2",
        agent_name="account_copilot",
        title="t",
        correctness_judge_enabled=True,
        metadata={"output": {"answer": "你现金 USD 50,000"}},
        expected_output_fields=[],
        forbidden_behavior=[],
        expected_behavior={},
    ).to_dict()
    repo = _Repo()
    repo.save_case(case)
    service = AgentEvalService(
        case_repository=repo,
        run_repository=_RunRepo(),
        llm_client=_JudgeFailLLM(),
    )
    run = service.run_eval(case_ids=["cj2"], mode="static")
    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge_correctness"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is False
    assert judge_checks[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# get_correctness_summary
# ---------------------------------------------------------------------------


def test_get_correctness_summary_empty() -> None:
    from app.services.agent_eval_service import AgentEvalService

    class _Repo:
        def __init__(self):
            self.cases = {}

        def save_case(self, c):
            self.cases[c["case_id"]] = c
            return c

        def get_case(self, cid):
            return self.cases.get(cid)

        def list_cases(self, **kw):
            return list(self.cases.values())

        def seed_builtin_cases(self, **kw):
            return {"created": [], "skipped": [], "created_count": 0, "skipped_count": 0}

    class _EmptyRunRepo:
        def save_run(self, r):
            return r

        def get_run(self, rid):
            return None

        def list_runs(self, **kw):
            return []

    service = AgentEvalService(case_repository=_Repo(), run_repository=_EmptyRunRepo())
    summary = service.get_correctness_summary()
    assert "summary" in summary
    assert "by_agent" in summary
    assert "by_dimension" in summary
    assert "recent_failures" in summary
    assert summary["summary"]["judged_case_count"] == 0
    assert summary["by_agent"] == []
    assert summary["by_dimension"] == []
    assert summary["recent_failures"] == []


def test_get_correctness_summary_with_judge_results() -> None:
    from app.services.agent_eval_service import AgentEvalService

    class _Repo:
        def __init__(self):
            self.cases = {}

        def save_case(self, c):
            self.cases[c["case_id"]] = c
            return c

        def get_case(self, cid):
            return self.cases.get(cid)

        def list_cases(self, **kw):
            return list(self.cases.values())

        def seed_builtin_cases(self, **kw):
            return {"created": [], "skipped": [], "created_count": 0, "skipped_count": 0}

    class _FakeRunRepo:
        def __init__(self, runs):
            self.runs = runs

        def save_run(self, r):
            return r

        def get_run(self, rid):
            return self.runs.get(rid)

        def list_runs(self, **kw):
            return list(self.runs.values())

    runs = [
        {
            "eval_run_id": "run-1",
            "results": [
                {
                    "case_id": "c1",
                    "agent_name": "trade_decision",
                    "metadata": {
                        "judge": {
                            "passed": True,
                            "overall_score": 0.9,
                            "dimension_scores": {"factual_accuracy": 0.9, "risk_awareness": 0.85},
                            "failed_dimensions": [],
                            "warnings": ["format nit"],
                            "failure_reasons": [],
                            "confidence": 0.8,
                        }
                    },
                },
                {
                    "case_id": "c2",
                    "agent_name": "account_copilot",
                    "metadata": {
                        "judge": {
                            "passed": False,
                            "overall_score": 0.4,
                            "dimension_scores": {"factual_accuracy": 0.4, "data_limitation_awareness": 0.4},
                            "failed_dimensions": ["factual_accuracy"],
                            "warnings": [],
                            "failure_reasons": ["编造了账户数据"],
                            "confidence": 0.9,
                        }
                    },
                },
            ],
        }
    ]
    service = AgentEvalService(
        case_repository=_Repo(),
        run_repository=_FakeRunRepo({r["eval_run_id"]: r for r in runs}),
    )
    summary = service.get_correctness_summary()
    assert summary["summary"]["judged_case_count"] == 2
    assert summary["summary"]["avg_overall_score"] == 0.65
    assert summary["summary"]["high_risk_failure_count"] == 1
    assert summary["summary"]["failed_dimension_count"] >= 1
    assert len(summary["by_agent"]) == 2
    assert len(summary["by_dimension"]) >= 1
    assert len(summary["recent_failures"]) == 1


# ---------------------------------------------------------------------------
# calibration cases 存在性
# ---------------------------------------------------------------------------


def test_judge_calibration_cases_loaded() -> None:
    cases = list_builtin_eval_cases()
    case_by_id = {c.case_id: c for c in cases}
    expected_case_ids = [
        "judge_calib_td_good_decision",
        "judge_calib_td_weak_strong_buy",
        "judge_calib_dpr_irrelevant_news",
        "judge_calib_dpr_good_attribution",
        "judge_calib_tr_result_only",
        "judge_calib_tr_process_separation",
        "judge_calib_ac_hallucinated_cash",
        "judge_calib_ac_limitation_correct",
        "judge_calib_xd_factual_no_risk",
        "judge_calib_xd_good_risk_low_actionability",
        "judge_calib_xd_hedged_no_action",
        "judge_calib_xd_account_copilot_safety",
    ]
    for case_id in expected_case_ids:
        assert case_id in case_by_id, f"missing case {case_id}"


def test_judge_calibration_cases_have_correctness_judge_enabled() -> None:
    cases = list_builtin_eval_cases()
    calib = [c for c in cases if "judge_calibration" in (c.tags or [])]
    assert len(calib) >= 8
    for c in calib:
        assert c.correctness_judge_enabled is True, f"case {c.case_id} missing correctness_judge_enabled"
        assert c.judge_enabled is True, f"case {c.case_id} missing judge_enabled"
        assert "correctness_dimensions" in (c.metadata or {}), f"case {c.case_id} missing correctness_dimensions"


def test_judge_calibration_cases_cover_all_agents() -> None:
    cases = list_builtin_eval_cases()
    calib = [c for c in cases if "judge_calibration" in (c.tags or [])]
    agents_covered = {c.agent_name for c in calib}
    assert "trade_decision" in agents_covered
    assert "daily_position_review" in agents_covered
    assert "trade_review" in agents_covered
    assert "account_copilot" in agents_covered


# ---------------------------------------------------------------------------
# API route exists
# ---------------------------------------------------------------------------


def test_correctness_summary_route_registered() -> None:
    from app.api.routes.admin_agent_eval import router

    paths = {r.path for r in router.routes}
    assert "/admin/agent-eval/correctness-summary" in paths
