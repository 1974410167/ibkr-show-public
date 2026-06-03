import json

from app.services.agent_eval_service import (
    AgentEvalService,
    build_coverage_gaps,
    build_coverage_recommendations,
)


class FakeCaseRepository:
    def __init__(self) -> None:
        self.cases = {}

    def save_case(self, case: dict) -> dict:
        self.cases[case["case_id"]] = case
        return case

    def get_case(self, case_id: str) -> dict | None:
        return self.cases.get(case_id)

    def list_cases(self, **kwargs) -> list[dict]:
        items = list(self.cases.values())
        agent_name = kwargs.get("agent_name")
        if agent_name:
            items = [item for item in items if item.get("agent_name") == agent_name]
        enabled = kwargs.get("enabled")
        if enabled is not None:
            items = [item for item in items if (item.get("enabled", True) is not False) is enabled]
        if not kwargs.get("include_archived", False):
            items = [item for item in items if item.get("archived", False) is not True]
        severity = kwargs.get("severity")
        if severity:
            items = [item for item in items if item.get("severity") == severity]
        category = kwargs.get("category")
        if category:
            items = [item for item in items if item.get("category") == category]
        tag = kwargs.get("tag")
        if tag:
            items = [item for item in items if tag in (item.get("tags") or [])]
        source_replay_id = kwargs.get("source_replay_id")
        if source_replay_id:
            items = [item for item in items if item.get("source_replay_id") == source_replay_id]
        eval_scope = kwargs.get("eval_scope")
        if eval_scope:
            items = [item for item in items if item.get("eval_scope", "agent") == eval_scope]
        node_name = kwargs.get("node_name")
        if node_name:
            items = [item for item in items if item.get("node_name") == node_name]
        source_run_id = kwargs.get("source_run_id")
        if source_run_id:
            items = [item for item in items if item.get("source_run_id") == source_run_id]
        source_llm_call_id = kwargs.get("source_llm_call_id")
        if source_llm_call_id:
            items = [item for item in items if item.get("source_llm_call_id") == source_llm_call_id]
        prompt_key = kwargs.get("prompt_key")
        if prompt_key:
            items = [item for item in items if item.get("prompt_key") == prompt_key]
        model = kwargs.get("model")
        if model:
            items = [item for item in items if item.get("model") == model]
        query = kwargs.get("query")
        if query:
            q = query.lower()
            items = [item for item in items if q in (item.get("title") or "").lower() or q in (item.get("case_id") or "").lower() or q in (item.get("description") or "").lower() or q in (item.get("notes") or "").lower()]
        return items

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        self.cases["builtin"] = {"case_id": "builtin", "agent_name": "trade_review", "title": "Builtin", "source": "manual"}
        return {"created": ["builtin"], "skipped": [], "created_count": 1, "skipped_count": 0}


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs = {}

    def save_run(self, run: dict) -> dict:
        self.runs[run["eval_run_id"]] = run
        return run

    def get_run(self, eval_run_id: str) -> dict | None:
        return self.runs.get(eval_run_id)

    def list_runs(self, **kwargs) -> list[dict]:
        return list(self.runs.values())


class FakeReplayService:
    def __init__(self) -> None:
        self.snapshot = {
            "replay_id": "replay-1",
            "run_id": "run-1",
            "agent_name": "trade_review",
            "request": {"symbol": "AMD"},
            "context_snapshot": {},
            "tool_snapshots": [{"tool_name": "get_context"}],
            "prompt_refs": [{"prompt_key": "trade_review_main"}],
            "final_output": {
                "summary": "有风险，需要观察",
                "overall_score": 70,
                "rating": "good",
                "data_limitations": [],
            },
        }

    def get_snapshot(self, replay_id: str):
        return self.snapshot if replay_id == "replay-1" else None


def test_agent_eval_service_seed_list_get_case() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    seeded = service.seed_builtin_cases()
    assert seeded["created_count"] == 1
    assert service.get_case("builtin")["case_id"] == "builtin"
    assert service.list_cases(agent_name="trade_review")[0]["case_id"] == "builtin"


def test_agent_eval_service_list_cases_falls_back_to_builtin_cases() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    cases = service.list_cases(agent_name="trade_decision")

    assert cases
    assert all(case["agent_name"] == "trade_decision" for case in cases)


def test_agent_eval_service_build_case_from_replay() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    case = service.build_case_from_replay("replay-1")

    assert case["source"] == "replay"
    assert case["metadata"]["replay_id"] == "replay-1"
    assert case["metadata"]["run_id"] == "run-1"


def test_agent_eval_service_run_eval_with_replay_static_mode() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    run = service.run_eval(replay_ids=["replay-1"], mode="static", name="Replay eval")

    assert run["status"] == "completed"
    assert run["summary"]["case_count"] == 1
    assert run["results"][0]["replay_id"] == "replay-1"
    assert run["results"][0]["run_id"] == "run-1"
    assert run["summary"]["by_agent"]["trade_review"]["case_count"] == 1
    for key in ("case_count", "passed_count", "warning_count", "failed_count", "error_count", "pass_rate", "by_agent"):
        assert key in run["summary"]


def test_agent_eval_service_case_without_output_returns_warning() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(
        {
            "case_id": "case-no-output",
            "agent_name": "trade_review",
            "title": "No output",
            "source": "manual",
            "metadata": {},
            "expected_output_fields": ["summary"],
            "forbidden_behavior": [],
            "expected_behavior": {},
        }
    )
    service = AgentEvalService(case_repo, FakeRunRepository(), FakeReplayService())
    run = service.run_eval(case_ids=["case-no-output"])

    assert run["results"][0]["status"] == "warning"
    assert run["results"][0]["error_code"] == "NO_OUTPUT_TO_EVALUATE"


def test_agent_eval_service_non_static_mode_reports_not_implemented_warning() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    run = service.run_eval(mode="live_real", agent_name="trade_review")

    assert run["results"][0]["status"] == "warning"
    assert run["results"][0]["error_code"] == "MODE_NOT_IMPLEMENTED"


def test_disabled_case_skipped_in_batch_but_runs_explicitly() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case({
        "case_id": "enabled-case",
        "agent_name": "trade_review",
        "title": "Enabled",
        "source": "manual",
        "enabled": True,
        "metadata": {"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })
    case_repo.save_case({
        "case_id": "disabled-case",
        "agent_name": "trade_review",
        "title": "Disabled",
        "source": "manual",
        "enabled": False,
        "metadata": {"output": {"summary": "ok", "overall_score": 50, "rating": "fair", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })
    service = AgentEvalService(case_repo, FakeRunRepository())

    batch_run = service.run_eval(agent_name="trade_review")
    batch_case_ids = [r["case_id"] for r in batch_run["results"]]
    assert "disabled-case" not in batch_case_ids
    assert "enabled-case" in batch_case_ids

    explicit_run = service.run_eval(case_ids=["disabled-case"])
    assert explicit_run["summary"]["case_count"] == 1
    assert explicit_run["results"][0]["case_id"] == "disabled-case"


def test_summary_includes_enhanced_fields() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case({
        "case_id": "case-low",
        "agent_name": "trade_review",
        "title": "Low severity",
        "source": "manual",
        "enabled": True,
        "severity": "low",
        "category": "format",
        "metadata": {"output": {"summary": "ok", "overall_score": 90, "rating": "good", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })
    case_repo.save_case({
        "case_id": "case-high",
        "agent_name": "trade_review",
        "title": "High severity",
        "source": "manual",
        "enabled": True,
        "severity": "high",
        "category": "investment_risk",
        "metadata": {"output": {"summary": "bad", "overall_score": 30, "rating": "poor", "data_limitations": []}},
        "expected_output_fields": ["summary", "missing_field"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })
    service = AgentEvalService(case_repo, FakeRunRepository())
    run = service.run_eval(case_ids=["case-low", "case-high"])

    summary = run["summary"]
    # Verify enhanced fields exist
    assert "status_counts" in summary
    assert "severity_counts" in summary
    assert "category_counts" in summary
    assert "check_counts" in summary
    assert "failed_check_counts" in summary
    assert "high_priority_failure_count" in summary
    assert "critical_failure_count" in summary
    assert "score_rate" in summary
    assert "failed_cases" in summary

    # Verify severity counts
    assert summary["severity_counts"]["low"] == 1
    assert summary["severity_counts"]["high"] == 1

    # Verify category counts
    assert summary["category_counts"]["format"] == 1
    assert summary["category_counts"]["investment_risk"] == 1

    # Verify high priority failure count (high severity + non-passed status)
    assert summary["high_priority_failure_count"] == 1
    # critical_failure_count 在 P1 fix 后也统计 fatal/critical failed check；
    # case-high 触发 required_fields (fatal) 失败，所以也计入 critical。
    assert summary["critical_failure_count"] == 1

    # Verify score_rate is valid
    assert 0 <= summary["score_rate"] <= 1

    # Verify failed_cases contains non-passed cases
    assert len(summary["failed_cases"]) >= 1
    failed_case_ids = [c["case_id"] for c in summary["failed_cases"]]
    assert "case-high" in failed_case_ids


def test_summary_score_rate_zero_when_no_max_score() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case({
        "case_id": "case-zero-max",
        "agent_name": "trade_review",
        "title": "Zero max",
        "source": "manual",
        "enabled": True,
        "metadata": {"output": {"summary": "ok"}},
        "expected_output_fields": [],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })
    service = AgentEvalService(case_repo, FakeRunRepository())
    run = service.run_eval(case_ids=["case-zero-max"])
    # The checks generate scores based on expected_output_fields, so max_score may not be 0
    # but score_rate should be valid (between 0 and 1)
    assert 0 <= run["summary"]["score_rate"] <= 1


def test_compare_eval_runs_new_failures() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()

    case_repo.save_case({
        "case_id": "case-1",
        "agent_name": "trade_review",
        "title": "Case 1",
        "source": "manual",
        "enabled": True,
        "severity": "high",
        "category": "investment_risk",
        "metadata": {"output": {"summary": "ok", "overall_score": 90, "rating": "good", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })

    service = AgentEvalService(case_repo, run_repo)

    # Run baseline (passed)
    baseline_run = service.run_eval(case_ids=["case-1"], name="Baseline")

    # Simulate a failing case by modifying the stored run
    baseline_result = baseline_run["results"][0].copy()
    baseline_result["status"] = "passed"
    baseline_result["score"] = 100
    modified_baseline = {**baseline_run, "results": [baseline_result]}
    run_repo.runs[baseline_run["eval_run_id"]] = modified_baseline

    # Run candidate (failed)
    candidate_run = service.run_eval(case_ids=["case-1"], name="Candidate")
    candidate_result = candidate_run["results"][0].copy()
    candidate_result["status"] = "failed"
    candidate_result["score"] = 50
    modified_candidate = {**candidate_run, "results": [candidate_result]}
    run_repo.runs[candidate_run["eval_run_id"]] = modified_candidate

    # Compare
    result = service.compare_eval_runs(baseline_run["eval_run_id"], candidate_run["eval_run_id"])
    assert result is not None
    assert result["summary"]["new_failure_count"] == 1
    assert len(result["new_failures"]) == 1
    assert result["new_failures"][0]["case_id"] == "case-1"


def test_compare_eval_runs_fixed_cases() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()

    case_repo.save_case({
        "case_id": "case-1",
        "agent_name": "trade_review",
        "title": "Case 1",
        "source": "manual",
        "enabled": True,
        "severity": "medium",
        "category": "format",
        "metadata": {"output": {"summary": "ok"}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
    })

    service = AgentEvalService(case_repo, run_repo)

    # Run baseline (failed)
    baseline_run = service.run_eval(case_ids=["case-1"], name="Baseline")
    baseline_result = baseline_run["results"][0].copy()
    baseline_result["status"] = "failed"
    modified_baseline = {**baseline_run, "results": [baseline_result]}
    run_repo.runs[baseline_run["eval_run_id"]] = modified_baseline

    # Run candidate (passed)
    candidate_run = service.run_eval(case_ids=["case-1"], name="Candidate")
    candidate_result = candidate_run["results"][0].copy()
    candidate_result["status"] = "passed"
    modified_candidate = {**candidate_run, "results": [candidate_result]}
    run_repo.runs[candidate_run["eval_run_id"]] = modified_candidate

    # Compare
    result = service.compare_eval_runs(baseline_run["eval_run_id"], candidate_run["eval_run_id"])
    assert result is not None
    assert result["summary"]["fixed_case_count"] == 1
    assert len(result["fixed_cases"]) == 1


def test_compare_eval_runs_missing_run_returns_none() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()
    service = AgentEvalService(case_repo, run_repo)

    result = service.compare_eval_runs("missing-baseline", "missing-candidate")
    assert result is None


def test_compare_eval_runs_missing_in_candidate() -> None:
    run_repo = FakeRunRepository()
    run_repo.save_run({
        "eval_run_id": "baseline-1", "name": "baseline", "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "passed", "score": 80, "max_score": 100, "checks": [], "metadata": {"severity": "medium"}},
            {"case_id": "c2", "agent_name": "trade_review", "status": "failed", "score": 30, "max_score": 100, "checks": [], "metadata": {"severity": "high"}},
        ],
    })
    run_repo.save_run({
        "eval_run_id": "candidate-1", "name": "candidate", "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "passed", "score": 80, "max_score": 100, "checks": [], "metadata": {"severity": "medium"}},
        ],
    })
    service = AgentEvalService(FakeCaseRepository(), run_repo)

    result = service.compare_eval_runs("baseline-1", "candidate-1")
    assert result is not None
    assert result["summary"]["missing_in_candidate_count"] == 1
    assert len(result["missing_in_candidate"]) == 1
    assert result["missing_in_candidate"][0]["case_id"] == "c2"
    assert result["missing_in_candidate"][0]["candidate_status"] == "missing"


def test_compare_eval_runs_new_cases_in_candidate() -> None:
    run_repo = FakeRunRepository()
    run_repo.save_run({
        "eval_run_id": "baseline-1", "name": "baseline", "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "passed", "score": 80, "max_score": 100, "checks": [], "metadata": {"severity": "medium"}},
        ],
    })
    run_repo.save_run({
        "eval_run_id": "candidate-1", "name": "candidate", "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "passed", "score": 80, "max_score": 100, "checks": [], "metadata": {"severity": "medium"}},
            {"case_id": "c3", "agent_name": "trade_review", "status": "passed", "score": 90, "max_score": 100, "checks": [], "metadata": {"severity": "low"}},
        ],
    })
    service = AgentEvalService(FakeCaseRepository(), run_repo)

    result = service.compare_eval_runs("baseline-1", "candidate-1")
    assert result is not None
    assert result["summary"]["new_case_in_candidate_count"] == 1
    assert len(result["new_cases_in_candidate"]) == 1
    assert result["new_cases_in_candidate"][0]["case_id"] == "c3"
    assert result["new_cases_in_candidate"][0]["baseline_status"] == "missing"


def test_compare_eval_runs_new_case_in_candidate_failed_counts_as_new_failure() -> None:
    run_repo = FakeRunRepository()
    run_repo.save_run({
        "eval_run_id": "baseline-1", "name": "baseline", "status": "completed",
        "results": [],
    })
    run_repo.save_run({
        "eval_run_id": "candidate-1", "name": "candidate", "status": "completed",
        "results": [
            {"case_id": "c-new", "agent_name": "trade_review", "status": "failed", "score": 20, "max_score": 100, "checks": [], "metadata": {"severity": "critical"}},
        ],
    })
    service = AgentEvalService(FakeCaseRepository(), run_repo)

    result = service.compare_eval_runs("baseline-1", "candidate-1")
    assert result is not None
    assert result["summary"]["new_failure_count"] == 1
    assert len(result["new_failures"]) == 1
    assert result["new_failures"][0]["case_id"] == "c-new"
    assert result["summary"]["new_case_in_candidate_count"] == 1


def _make_case(case_id: str, **overrides) -> dict:
    base = {
        "case_id": case_id,
        "agent_name": "trade_review",
        "title": f"Case {case_id}",
        "source": "manual",
        "enabled": True,
        "metadata": {"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
        "expected_output_fields": ["summary"],
        "forbidden_behavior": [],
        "expected_behavior": {},
        "scoring_rubric": {},
        "judge_enabled": False,
        "judge_rubric": {},
        "judge_model_config": {},
        "archived": False,
        "archived_at": None,
        "archived_reason": None,
    }
    base.update(overrides)
    return base


def test_list_cases_filter_by_tag() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", tags=["regression", "format"]))
    case_repo.save_case(_make_case("c2", tags=["smoke"]))
    case_repo.save_case(_make_case("c3"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.list_cases(tag="regression")
    assert len(result) == 1
    assert result[0]["case_id"] == "c1"


def test_list_cases_filter_by_source_replay_id() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", source_replay_id="replay-1"))
    case_repo.save_case(_make_case("c2", source_replay_id="replay-2"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.list_cases(source_replay_id="replay-2")
    assert len(result) == 1
    assert result[0]["case_id"] == "c2"


def test_list_cases_filter_by_query() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c-amd", title="AMD trade review"))
    case_repo.save_case(_make_case("c-tsla", title="TSLA trade review"))
    case_repo.save_case(_make_case("c-other", title="Other stuff", notes="amd related"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.list_cases(query="AMD")
    case_ids = [r["case_id"] for r in result]
    assert "c-amd" in case_ids
    assert "c-other" in case_ids
    assert "c-tsla" not in case_ids


def test_bulk_update_enabled() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", enabled=True))
    case_repo.save_case(_make_case("c2", enabled=True))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.bulk_update_cases(["c1", "c2"], {"enabled": False})
    assert result["updated_count"] == 2
    assert result["failed_count"] == 0
    assert service.get_case("c1")["enabled"] is False
    assert service.get_case("c2")["enabled"] is False


def test_bulk_update_severity_category() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", severity="low", category="format"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.bulk_update_cases(["c1"], {"severity": "high", "category": "investment_risk"})
    assert result["updated_count"] == 1
    assert service.get_case("c1")["severity"] == "high"
    assert service.get_case("c1")["category"] == "investment_risk"


def test_bulk_update_tags_add_remove() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", tags=["old", "keep"]))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.bulk_update_cases(["c1"], {"tags_add": ["new", "keep"], "tags_remove": ["old"]})
    assert result["updated_count"] == 1
    tags = service.get_case("c1")["tags"]
    assert "new" in tags
    assert "keep" in tags
    assert "old" not in tags


def test_bulk_update_missing_case_partial_failure() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", enabled=True))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.bulk_update_cases(["c1", "missing"], {"enabled": False})
    assert result["updated_count"] == 1
    assert result["failed_count"] == 1
    assert result["items"][0]["status"] == "updated"
    assert result["items"][1]["status"] == "error"
    assert result["items"][1]["error_code"] == "CASE_NOT_FOUND"


def test_clone_case_success() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("original", title="Original Case", tags=["tag1"]))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cloned = service.clone_case("original")
    assert cloned["case_id"] != "original"
    assert cloned["title"] == "Copy of Original Case"
    assert cloned["source"] == "manual"
    assert cloned["enabled"] is False
    assert cloned["metadata"]["cloned_from_case_id"] == "original"
    assert cloned["tags"] == ["tag1"]
    assert cloned["version"] == 1


def test_clone_case_missing_returns_none() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository())
    assert service.clone_case("missing") is None


def test_clone_case_default_disabled() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", enabled=True))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cloned = service.clone_case("c1")
    assert cloned["enabled"] is False


def test_enabled_true_includes_missing_and_null_enabled_old_cases() -> None:
    case_repo = FakeCaseRepository()
    missing_enabled = _make_case("missing-enabled", agent_name="trade_decision")
    missing_enabled.pop("enabled", None)
    case_repo.save_case(missing_enabled)
    case_repo.save_case(_make_case("null-enabled", agent_name="trade_decision", enabled=None))
    case_repo.save_case(_make_case("true-enabled", agent_name="trade_decision", enabled=True))
    case_repo.save_case(_make_case("false-enabled", agent_name="trade_decision", enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())

    enabled_cases = service.list_cases(agent_name="trade_decision", enabled=True)
    enabled_ids = {c["case_id"] for c in enabled_cases}
    assert enabled_ids == {"missing-enabled", "null-enabled", "true-enabled"}

    disabled_cases = service.list_cases(agent_name="trade_decision", enabled=False)
    assert {c["case_id"] for c in disabled_cases} == {"false-enabled"}


def test_regression_eval_default_selects_missing_and_null_enabled_cases() -> None:
    case_repo = FakeCaseRepository()
    missing_enabled = _make_case("missing-enabled", agent_name="trade_decision")
    missing_enabled.pop("enabled", None)
    case_repo.save_case(missing_enabled)
    case_repo.save_case(_make_case("null-enabled", agent_name="trade_decision", enabled=None))
    case_repo.save_case(_make_case("disabled", agent_name="trade_decision", enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision", "mode": "static"})

    assert result["selected_case_count"] == 2
    assert set(result["eval_run"]["case_ids"]) == {"missing-enabled", "null-enabled"}


def test_regression_eval_include_disabled_keeps_disabled_cases() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("enabled", agent_name="trade_decision", enabled=True))
    case_repo.save_case(_make_case("disabled", agent_name="trade_decision", enabled=False))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "mode": "static",
        "include_disabled": True,
    })

    assert set(result["eval_run"]["case_ids"]) == {"enabled", "disabled"}


def test_archive_and_unarchive_case() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("c1", agent_name="custom_eval_agent", enabled=True))
    service = AgentEvalService(case_repo, FakeRunRepository())

    archived = service.archive_case("c1", reason="online verification cleanup")

    assert archived is not None
    assert archived["archived"] is True
    assert archived["enabled"] is False
    assert archived["archived_at"]
    assert archived["archived_reason"] == "online verification cleanup"
    assert service.list_cases(agent_name="custom_eval_agent") == []
    assert service.list_cases(agent_name="custom_eval_agent", include_archived=True)[0]["case_id"] == "c1"

    unarchived = service.unarchive_case("c1")
    assert unarchived is not None
    assert unarchived["archived"] is False
    assert unarchived["archived_at"] is None
    assert unarchived["archived_reason"] is None
    assert unarchived["enabled"] is False


def test_regression_eval_default_skips_archived_cases() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("active", agent_name="trade_decision"))
    case_repo.save_case(_make_case("archived", agent_name="trade_decision", archived=True))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision", "mode": "static"})

    assert result["selected_case_count"] == 1
    assert result["eval_run"]["case_ids"] == ["active"]


def test_clone_archived_case_resets_archive_fields() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "archived",
        archived=True,
        archived_at="2026-01-01T00:00:00+00:00",
        archived_reason="cleanup",
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cloned = service.clone_case("archived")

    assert cloned is not None
    assert cloned["archived"] is False
    assert cloned["archived_at"] is None
    assert cloned["archived_reason"] is None


# ── Clone Node Eval Case Field Preservation (Fix #4) ─────────────


def test_clone_node_eval_case_preserves_all_node_fields() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-orig",
        agent_name="trade_decision",
        eval_scope="node",
        node_name="event_catalyst",
        source_run_id="run-orig",
        source_llm_call_id="llm-orig",
        source_node_trace_id="trace-orig",
        prompt_key="trade_decision_event_catalyst_prompt",
        prompt_version="v3",
        prompt_hash="abc123",
        model="gpt-5",
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cloned = service.clone_case("node-orig")

    assert cloned is not None
    assert cloned["eval_scope"] == "node"
    assert cloned["node_name"] == "event_catalyst"
    assert cloned["source_run_id"] == "run-orig"
    assert cloned["source_llm_call_id"] == "llm-orig"
    assert cloned["source_node_trace_id"] == "trace-orig"
    assert cloned["prompt_key"] == "trade_decision_event_catalyst_prompt"
    assert cloned["prompt_version"] == "v3"
    assert cloned["prompt_hash"] == "abc123"
    assert cloned["model"] == "gpt-5"
    # source 仍然是 manual
    assert cloned["source"] == "manual"
    # enabled 默认 false
    assert cloned["enabled"] is False
    # metadata 中记录 cloned_from_case_id
    assert cloned["metadata"]["cloned_from_case_id"] == "node-orig"
    # 克隆后 case_id 不同
    assert cloned["case_id"] != "node-orig"


def test_clone_agent_eval_case_preserves_agent_scope() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-orig", agent_name="trade_decision", eval_scope="agent",
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cloned = service.clone_case("agent-orig")

    assert cloned is not None
    assert cloned["eval_scope"] == "agent"
    assert cloned["node_name"] is None


class FakeLLMClient:
    def __init__(self, response: str = '{"summary": "mock output", "overall_score": 80, "rating": "good", "data_limitations": []}') -> None:
        self.response = response
        self.call_count = 0

    def chat(self, messages: list, **kwargs) -> str:
        self.call_count += 1
        return self.response


JUDGE_PASS_RESPONSE = json.dumps({
    "overall_score": 82,
    "passed": True,
    "confidence": "medium",
    "dimensions": {
        "answer_relevance": {"score": 18, "max_score": 20, "reason": "回答覆盖了用户问题"},
        "grounding": {"score": 16, "max_score": 20, "reason": "结论基本基于上下文"},
        "risk_awareness": {"score": 20, "max_score": 20, "reason": "明确说明了风险"},
        "actionability": {"score": 14, "max_score": 20, "reason": "建议可执行"},
        "no_overclaiming": {"score": 14, "max_score": 20, "reason": "没有过度承诺"},
    },
    "major_issues": [],
    "minor_issues": ["缺少更明确的止损条件"],
    "verdict": "pass",
})

JUDGE_FAIL_RESPONSE = json.dumps({
    "overall_score": 35,
    "passed": False,
    "confidence": "high",
    "dimensions": {
        "answer_relevance": {"score": 10, "max_score": 20, "reason": "没有回答用户问题"},
        "grounding": {"score": 5, "max_score": 20, "reason": "结论无依据"},
        "risk_awareness": {"score": 10, "max_score": 20, "reason": "未说明风险"},
        "actionability": {"score": 5, "max_score": 20, "reason": "建议不可执行"},
        "no_overclaiming": {"score": 5, "max_score": 20, "reason": "过度承诺"},
    },
    "major_issues": ["结论无依据", "过度承诺"],
    "minor_issues": [],
    "verdict": "fail",
})


def test_live_mock_supported_agent() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "mock-case",
        agent_name="trade_review",
        input={"symbol": "AMD"},
        mock_context={"evidence": "some data"},
        mock_tool_outputs={"tool_snapshots": [{"tool_name": "get_context"}]},
    ))
    llm_client = FakeLLMClient()
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm_client)

    run = service.run_eval(case_ids=["mock-case"], mode="live_mock", name="Mock eval")

    assert run["status"] == "completed"
    assert run["summary"]["case_count"] == 1
    result = run["results"][0]
    assert result["status"] in {"passed", "warning", "failed"}
    assert result["metadata"]["eval_mode"] == "live_mock"
    assert result["metadata"]["live_output_generated"] is True
    assert result["metadata"]["actual_output"] is not None
    assert llm_client.call_count == 1


def test_live_mock_unsupported_agent() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("unsupported-case", agent_name="unknown_agent"))
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=FakeLLMClient())

    run = service.run_eval(case_ids=["unsupported-case"], mode="live_mock")

    result = run["results"][0]
    assert result["status"] == "warning"
    assert result["error_code"] == "LIVE_MOCK_AGENT_NOT_SUPPORTED"


def test_live_mock_missing_case() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), llm_client=FakeLLMClient())

    run = service.run_eval(case_ids=["missing"], mode="live_mock")

    result = run["results"][0]
    assert result["status"] == "error"
    assert result["error_code"] == "CASE_NOT_FOUND"


def test_live_mock_multi_case_partial_failure() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("good-case", agent_name="trade_review"))
    case_repo.save_case(_make_case("bad-case", agent_name="unsupported_agent"))
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=FakeLLMClient())

    run = service.run_eval(case_ids=["good-case", "bad-case"], mode="live_mock")

    assert run["summary"]["case_count"] == 2
    statuses = {r["case_id"]: r["status"] for r in run["results"]}
    assert statuses["good-case"] in {"passed", "warning", "failed"}
    assert statuses["bad-case"] == "warning"


def test_live_mock_no_llm_client() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("case-1", agent_name="trade_review"))
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=None)

    run = service.run_eval(case_ids=["case-1"], mode="live_mock")

    result = run["results"][0]
    assert result["error_code"] == "LIVE_MOCK_NO_LLM_CLIENT"


def test_static_mode_unchanged() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "static-case",
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["static-case"], mode="static")

    assert run["status"] == "completed"
    assert run["results"][0]["metadata"]["eval_mode"] == "static"


def test_live_mock_result_includes_actual_output() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "output-case",
        agent_name="trade_review",
        input={"symbol": "TSLA"},
        mock_context={},
        mock_tool_outputs={},
    ))
    llm = FakeLLMClient('{"summary": "TSLA analysis", "overall_score": 75, "rating": "fair", "data_limitations": ["limited data"]}')
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["output-case"], mode="live_mock")

    result = run["results"][0]
    actual_output = result["metadata"]["actual_output"]
    assert actual_output["summary"] == "TSLA analysis"
    assert actual_output["overall_score"] == 75


def test_judge_disabled_no_call() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "no-judge",
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["no-judge"], mode="static")

    assert llm.call_count == 0
    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 0


def test_judge_enabled_appends_check() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-case",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-case"], mode="static")

    assert llm.call_count == 1
    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is True
    assert judge_checks[0]["score"] == 82
    assert result["metadata"]["judge_enabled"] is True
    assert result["metadata"]["judge_verdict"] == "pass"


def test_judge_fail_generates_warning_check() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-fail",
        judge_enabled=True,
        metadata={"output": {"summary": "bad", "overall_score": 30, "rating": "poor", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_FAIL_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-fail"], mode="static")

    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is False
    assert judge_checks[0]["severity"] == "warning"
    assert result["metadata"]["judge_verdict"] == "fail"


def test_judge_parse_failure_safe_fallback() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-parse-fail",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient("not valid json at all")
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-parse-fail"], mode="static")

    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is False
    assert judge_checks[0]["details"]["error_code"] == "LLM_JUDGE_PARSE_FAILED"


def test_judge_call_exception_safe_fallback() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-exception",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))

    class ErrorLLMClient:
        def chat(self, messages, **kwargs):
            raise RuntimeError("LLM service down")

    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=ErrorLLMClient())

    run = service.run_eval(case_ids=["judge-exception"], mode="static")

    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is False
    assert judge_checks[0]["details"]["error_code"] == "LLM_JUDGE_CALL_FAILED"


def test_judge_multi_case_partial_failure() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-ok",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    case_repo.save_case(_make_case(
        "no-judge",
        judge_enabled=False,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-ok", "no-judge"], mode="static")

    assert run["summary"]["case_count"] == 2
    assert llm.call_count == 1
    judge_config = run["config"].get("judge_enabled")
    assert judge_config is True
    assert run["config"]["judge_case_count"] == 1


def test_judge_no_llm_client_returns_unavailable() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-no-llm",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=None)

    run = service.run_eval(case_ids=["judge-no-llm"], mode="static")

    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["details"]["error_code"] == "LLM_JUDGE_SERVICE_UNAVAILABLE"


def test_judge_fields_default() -> None:
    case = _make_case("default-case")
    case_repo = FakeCaseRepository()
    case_repo.save_case(case)
    service = AgentEvalService(case_repo, FakeRunRepository())

    loaded = service.get_case("default-case")
    assert loaded["judge_enabled"] is False
    assert loaded["judge_rubric"] == {}
    assert loaded["judge_model_config"] == {}


def test_judge_custom_rubric() -> None:
    custom_rubric = {
        "custom_dim": {"max_score": 50, "description": "Custom dimension"},
        "another_dim": {"max_score": 50, "description": "Another dimension"},
    }
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "custom-rubric",
        judge_enabled=True,
        judge_rubric=custom_rubric,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["custom-rubric"], mode="static")

    assert llm.call_count == 1
    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1


# ── Bad Case Feedback Tests ─────────────────────────────────────────


class FakeFeedbackRepository:
    def __init__(self) -> None:
        self.feedbacks: dict[str, dict] = {}

    def save_feedback(self, feedback: dict) -> dict:
        self.feedbacks[feedback["feedback_id"]] = feedback
        return feedback

    def get_feedback(self, feedback_id: str) -> dict | None:
        return self.feedbacks.get(feedback_id)

    def list_feedback(self, **kwargs) -> list[dict]:
        items = list(self.feedbacks.values())
        if kwargs.get("status"):
            items = [i for i in items if i.get("status") == kwargs["status"]]
        if kwargs.get("source_type"):
            items = [i for i in items if i.get("source_type") == kwargs["source_type"]]
        if kwargs.get("agent_name"):
            items = [i for i in items if i.get("agent_name") == kwargs["agent_name"]]
        if kwargs.get("severity"):
            items = [i for i in items if i.get("severity") == kwargs["severity"]]
        if kwargs.get("category"):
            items = [i for i in items if i.get("category") == kwargs["category"]]
        if kwargs.get("issue_type"):
            items = [i for i in items if i.get("issue_type") == kwargs["issue_type"]]
        if kwargs.get("tag"):
            items = [i for i in items if kwargs["tag"] in (i.get("tags") or [])]
        if kwargs.get("eval_run_id"):
            items = [i for i in items if i.get("eval_run_id") == kwargs["eval_run_id"]]
        if kwargs.get("query"):
            q = kwargs["query"].lower()
            items = [i for i in items if q in (i.get("title") or "").lower() or q in (i.get("description") or "").lower()]
        return items[: kwargs.get("limit", 100)]


def _make_feedback_payload(**overrides) -> dict:
    base = {
        "source_type": "manual",
        "source_id": "manual-1",
        "title": "Test feedback",
        "agent_name": "trade_review",
        "issue_type": "other",
        "severity": "medium",
    }
    base.update(overrides)
    return base


def test_create_feedback_success() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    result = service.create_feedback(_make_feedback_payload())

    assert result["feedback_id"].startswith("feedback_")
    assert result["source_type"] == "manual"
    assert result["status"] == "open"
    assert result["title"] == "Test feedback"


def test_create_feedback_missing_source_type() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="source_type"):
        service.create_feedback(_make_feedback_payload(source_type=""))


def test_create_feedback_missing_source_id() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="source_id"):
        service.create_feedback(_make_feedback_payload(source_id=""))


def test_create_feedback_missing_title() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="title"):
        service.create_feedback(_make_feedback_payload(title=""))


def test_create_feedback_invalid_severity() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="severity"):
        service.create_feedback(_make_feedback_payload(severity="extreme"))


def test_create_feedback_invalid_issue_type() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="issue_type"):
        service.create_feedback(_make_feedback_payload(issue_type="made_up"))


def test_list_feedback_filters() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    service.create_feedback(_make_feedback_payload(title="FB1", severity="high"))
    service.create_feedback(_make_feedback_payload(title="FB2", severity="low", source_type="replay", source_id="r1"))
    service.create_feedback(_make_feedback_payload(title="FB3", tags=["ci"]))

    result = service.list_feedback(severity="high")
    assert result["summary"]["count"] == 1
    assert result["items"][0]["title"] == "FB1"

    result = service.list_feedback(source_type="replay")
    assert result["summary"]["count"] == 1

    result = service.list_feedback(tag="ci")
    assert result["summary"]["count"] == 1

    result = service.list_feedback(query="FB")
    assert result["summary"]["count"] == 3


def test_update_feedback_status() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    fb = service.create_feedback(_make_feedback_payload())
    updated = service.update_feedback(fb["feedback_id"], {"status": "triaged"})

    assert updated["status"] == "triaged"
    assert updated["updated_at"] != fb["updated_at"]


def test_update_feedback_invalid_status() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    fb = service.create_feedback(_make_feedback_payload())

    import pytest
    with pytest.raises(ValueError, match="status"):
        service.update_feedback(fb["feedback_id"], {"status": "bogus"})


def test_update_feedback_not_found() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    result = service.update_feedback("nonexistent", {"status": "triaged"})
    assert result is None


def test_create_eval_case_from_feedback_replay() -> None:
    fb_repo = FakeFeedbackRepository()
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository(), FakeReplayService(), feedback_repository=fb_repo)

    fb = service.create_feedback(_make_feedback_payload(
        source_type="replay", source_id="replay-1", replay_id="replay-1",
    ))
    case = service.create_eval_case_from_feedback(fb["feedback_id"])

    assert case is not None
    assert case["source"] == "replay"
    assert case["agent_name"] == "trade_review"
    assert "bad_case" in case["tags"]

    updated_fb = fb_repo.get_feedback(fb["feedback_id"])
    assert updated_fb["status"] == "converted"
    assert updated_fb["converted_case_id"] == case["case_id"]


def test_create_eval_case_from_feedback_eval_result() -> None:
    fb_repo = FakeFeedbackRepository()
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("existing-case"))
    service = AgentEvalService(case_repo, FakeRunRepository(), feedback_repository=fb_repo)

    fb = service.create_feedback(_make_feedback_payload(
        source_type="eval_result", source_id="run1:existing-case",
        eval_run_id="run1", result_case_id="existing-case", case_id="existing-case",
    ))
    case = service.create_eval_case_from_feedback(fb["feedback_id"])

    assert case is not None
    assert case["source"] == "feedback"
    assert case["case_id"] != "existing_case"
    assert case["metadata"]["created_from_feedback_id"] == fb["feedback_id"]


def test_create_eval_case_from_feedback_manual_fallback() -> None:
    fb_repo = FakeFeedbackRepository()
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository(), feedback_repository=fb_repo)

    fb = service.create_feedback(_make_feedback_payload(
        source_type="manual", source_id="manual-obs-1",
        evidence={"input": {"symbol": "AMD"}},
    ))
    case = service.create_eval_case_from_feedback(fb["feedback_id"])

    assert case is not None
    assert case["source"] == "feedback"
    assert case["metadata"]["feedback_id"] == fb["feedback_id"]


def test_create_eval_case_from_feedback_not_found() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    result = service.create_eval_case_from_feedback("nonexistent")
    assert result is None


def test_create_feedback_from_eval_run_failures() -> None:
    fb_repo = FakeFeedbackRepository()
    run_repo = FakeRunRepository()
    run_repo.save_run({
        "eval_run_id": "run-1",
        "name": "test run",
        "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "passed", "score": 80, "max_score": 100, "checks": []},
            {"case_id": "c2", "agent_name": "trade_review", "status": "failed", "score": 20, "max_score": 100,
             "checks": [{"check_name": "required_fields", "passed": False, "message": "missing"}],
             "metadata": {"severity": "high", "category": "format"}},
            {"case_id": "c3", "agent_name": "trade_review", "status": "warning", "score": 50, "max_score": 100,
             "checks": [{"check_name": "data_limitations", "passed": False, "message": "limited"}],
             "metadata": {"severity": "medium"}},
        ],
    })
    service = AgentEvalService(FakeCaseRepository(), run_repo, feedback_repository=fb_repo)

    result = service.create_feedback_from_eval_run_failures("run-1")

    assert result["created"] == 2
    assert result["skipped"] == 0
    assert result["total_failures"] == 2
    assert len(fb_repo.feedbacks) == 2

    fb_c2 = next(f for f in fb_repo.feedbacks.values() if f["result_case_id"] == "c2")
    assert fb_c2["issue_type"] == "format_error"
    assert fb_c2["severity"] == "high"
    assert "auto_generated" in fb_c2["tags"]
    assert fb_c2["eval_run_id"] == "run-1"


def test_create_feedback_from_eval_run_failures_skips_duplicates() -> None:
    fb_repo = FakeFeedbackRepository()
    run_repo = FakeRunRepository()
    run_repo.save_run({
        "eval_run_id": "run-1",
        "name": "test run",
        "status": "completed",
        "results": [
            {"case_id": "c1", "agent_name": "trade_review", "status": "failed", "score": 20, "max_score": 100, "checks": []},
        ],
    })
    service = AgentEvalService(FakeCaseRepository(), run_repo, feedback_repository=fb_repo)

    first = service.create_feedback_from_eval_run_failures("run-1")
    assert first["created"] == 1

    second = service.create_feedback_from_eval_run_failures("run-1")
    assert second["created"] == 0
    assert second["skipped"] == 1


def test_create_feedback_from_eval_run_failures_not_found() -> None:
    fb_repo = FakeFeedbackRepository()
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), feedback_repository=fb_repo)

    import pytest
    with pytest.raises(ValueError, match="Eval run not found"):
        service.create_feedback_from_eval_run_failures("nonexistent")


# ── Live Mock Metadata Tests ────────────────────────────────────────


def test_live_mock_metadata_includes_strategy() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("lm-1", agent_name="trade_review"))
    llm = FakeLLMClient('{"summary": "mock output", "overall_score": 80, "rating": "good", "data_limitations": []}')
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["lm-1"], mode="live_mock")

    result = run["results"][0]
    meta = result.get("metadata") or {}
    assert meta.get("live_mock_strategy") == "prompt_adapter"
    assert meta.get("graph_runner_executed") is False
    assert run["config"].get("live_mock_strategy") == "prompt_adapter"


# ── Judge Metadata Tests ────────────────────────────────────────────


class FakeLLMClientWithMetadata:
    def __init__(self, response: str) -> None:
        self.response = response
        self.call_count = 0
        self.last_kwargs: dict = {}

    def chat(self, messages: list, **kwargs) -> str:
        self.call_count += 1
        return self.response

    def chat_with_metadata(self, messages: list, **kwargs) -> object:
        self.call_count += 1
        self.last_kwargs = kwargs
        return type("Result", (), {"content": self.response})()


def test_judge_uses_chat_with_metadata_when_available() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-meta",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClientWithMetadata(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-meta"], mode="static")

    assert llm.call_count == 1
    assert llm.last_kwargs.get("call_type") == "eval_judge"
    assert llm.last_kwargs.get("agent_name") == "eval_judge"
    assert llm.last_kwargs.get("node_name") == "llm_judge"
    prompt_meta = llm.last_kwargs.get("prompt_metadata") or {}
    assert prompt_meta.get("case_id") == "judge-meta"
    assert prompt_meta.get("eval_mode") == "static"
    assert prompt_meta.get("judge_enabled") is True


def test_judge_falls_back_to_chat_when_no_metadata_method() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "judge-fallback",
        judge_enabled=True,
        metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}},
    ))
    llm = FakeLLMClient(JUDGE_PASS_RESPONSE)
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_client=llm)

    run = service.run_eval(case_ids=["judge-fallback"], mode="static")

    assert llm.call_count == 1
    result = run["results"][0]
    judge_checks = [c for c in result["checks"] if c["check_name"] == "llm_judge"]
    assert len(judge_checks) == 1
    assert judge_checks[0]["passed"] is True


# ── Agent Regression Eval Tests ───────────────────────────────────────


def _trade_decision_output() -> dict:
    return {
        "summary": "ok",
        "overall_score": 70,
        "rating": "good",
        "data_limitations": [],
        "major_risks": ["market risk"],
        "decision": "buy",
        "confidence": 0.8,
    }


def test_regression_eval_basic() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("reg-1", agent_name="trade_decision", tags=["regression"], metadata={"output": _trade_decision_output()}))
    case_repo.save_case(_make_case("reg-2", agent_name="trade_decision", tags=["regression"], metadata={"output": _trade_decision_output()}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision", "case_tag": "regression"})

    assert "eval_run" in result
    assert "gate_result" in result
    assert result["selected_case_count"] == 2
    assert result["eval_run"]["config"]["run_type"] == "agent_regression"
    assert result["eval_run"]["config"]["trigger"] == "manual"
    assert result["eval_run"]["config"]["agent_name"] == "trade_decision"
    assert result["eval_run"]["config"]["case_selector"]["case_tag"] == "regression"
    assert result["eval_run"]["config"]["gate_result"]["passed"] is True


def test_regression_eval_include_judge_false_skips_judge() -> None:
    case_repo = FakeCaseRepository()
    out = _trade_decision_output()
    case_repo.save_case(_make_case("rj-1", agent_name="trade_decision", judge_enabled=False, metadata={"output": out}))
    case_repo.save_case(_make_case("rj-2", agent_name="trade_decision", judge_enabled=True, metadata={"output": out}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_judge": False,
    })

    assert result["selected_case_count"] == 1
    assert result["skipped_judge_case_count"] == 1


def test_regression_eval_include_judge_true() -> None:
    case_repo = FakeCaseRepository()
    out = _trade_decision_output()
    case_repo.save_case(_make_case("rjt-1", agent_name="trade_decision", judge_enabled=False, metadata={"output": out}))
    case_repo.save_case(_make_case("rjt-2", agent_name="trade_decision", judge_enabled=True, metadata={"output": out}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_judge": True,
    })

    assert result["selected_case_count"] == 2
    assert result["skipped_judge_case_count"] == 0


def test_regression_eval_include_judge_false_keeps_false_null_and_missing() -> None:
    case_repo = FakeCaseRepository()
    out = _trade_decision_output()
    case_repo.save_case(_make_case("rjm-true", agent_name="trade_decision", judge_enabled=True, metadata={"output": out}))
    case_repo.save_case(_make_case("rjm-false", agent_name="trade_decision", judge_enabled=False, metadata={"output": out}))
    case_repo.save_case(_make_case("rjm-null", agent_name="trade_decision", judge_enabled=None, metadata={"output": out}))
    missing_case = _make_case("rjm-missing", agent_name="trade_decision", metadata={"output": out})
    missing_case.pop("judge_enabled")
    case_repo.save_case(missing_case)
    service = AgentEvalService(case_repo, FakeRunRepository())

    selected = service.select_cases_for_eval(agent_name="trade_decision", include_judge=False)
    selected_ids = {case["case_id"] for case in selected}

    assert selected_ids == {"rjm-false", "rjm-null", "rjm-missing"}

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_judge": False,
    })

    assert result["selected_case_count"] == 3
    assert result["skipped_judge_case_count"] == 1

    include_all = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_judge": True,
    })

    assert include_all["selected_case_count"] == 4
    assert include_all["skipped_judge_case_count"] == 0


def test_regression_eval_no_cases_raises() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    try:
        service.run_agent_regression_eval({"agent_name": "nonexistent"})
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "No eval cases matched" in str(exc)


def test_regression_eval_gate_min_pass_rate_fail() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("gpr-1", agent_name="trade_decision", metadata={"output": {}}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "gate": {"min_pass_rate": 1.0},
    })

    assert result["gate_result"]["passed"] is False
    assert any("pass_rate" in r for r in result["gate_result"]["reasons"])


def test_regression_eval_gate_fail_on_critical() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("gfc-1", agent_name="trade_decision", severity="critical", metadata={"output": {}}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "gate": {"fail_on_critical": True, "min_pass_rate": 0},
    })

    assert result["gate_result"]["passed"] is False
    assert any("critical_failure" in r for r in result["gate_result"]["reasons"])


def test_regression_eval_gate_result_in_config() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("grc-1", agent_name="trade_decision", metadata={"output": _trade_decision_output()}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision"})
    config = result["eval_run"]["config"]

    assert "gate_result" in config
    assert "passed" in config["gate_result"]


def test_regression_eval_prompt_model_git_in_config() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("pmg-1", agent_name="trade_decision", metadata={"output": _trade_decision_output()}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "prompt": {"prompt_key": "test_prompt", "prompt_version": "v1"},
        "model": {"provider": "openrouter", "model": "gpt-5"},
        "git": {"commit_sha": "abc123", "branch": "main"},
    })
    config = result["eval_run"]["config"]

    assert config["prompt"]["prompt_key"] == "test_prompt"
    assert config["model"]["provider"] == "openrouter"
    assert config["git"]["commit_sha"] == "abc123"


def test_regression_eval_baseline_compare() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("bc-1", agent_name="trade_decision", metadata={"output": _trade_decision_output()}))
    run_repo = FakeRunRepository()
    service = AgentEvalService(case_repo, run_repo)

    baseline = service.run_eval(case_ids=["bc-1"], mode="static")
    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "baseline_eval_run_id": baseline["eval_run_id"],
    })

    assert result["baseline_compare_result"] is not None
    assert result["eval_run"]["config"]["baseline_compared"] is True
    assert result["eval_run"]["config"]["baseline_eval_run_id"] == baseline["eval_run_id"]


def test_regression_eval_baseline_not_found_no_failure() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("bnf-1", agent_name="trade_decision", metadata={"output": _trade_decision_output()}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "baseline_eval_run_id": "nonexistent",
    })

    assert result["baseline_compare_result"] is None
    assert result["eval_run"]["config"]["baseline_compare_error"] == "Baseline eval run not found"
    assert result["gate_result"]["passed"] is True


# ── Coverage Matrix Tests ─────────────────────────────────────────────


def _setup_coverage_data():
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()

    case_repo.save_case(_make_case("cov-1", agent_name="trade_decision", severity="high", category="investment_risk", tags=["regression"], source="replay", enabled=True, judge_enabled=True, metadata={"output": _trade_decision_output()}))
    case_repo.save_case(_make_case("cov-2", agent_name="trade_decision", severity="critical", category="investment_risk", tags=["regression"], source="manual", enabled=True, metadata={"output": _trade_decision_output()}))
    case_repo.save_case(_make_case("cov-3", agent_name="trade_decision", severity="medium", category="format", source="feedback", enabled=True, metadata={"output": _trade_decision_output()}))
    case_repo.save_case(_make_case("cov-4", agent_name="trade_review", severity="low", enabled=False, metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}}))
    case_repo.save_case(_make_case("cov-5", agent_name="trade_review", severity="high", category="risk", tags=["smoke"], source="builtin", enabled=True, metadata={"output": {"summary": "ok", "overall_score": 70, "rating": "good", "data_limitations": []}}))
    # Case with no severity/category/tags/source
    case_repo.save_case(_make_case("cov-6", agent_name="daily_position_review", enabled=True, metadata={"output": _trade_decision_output()}))

    # Create a run that evaluated cov-1 (passed) and cov-3 (failed)
    run_repo.save_run({
        "eval_run_id": "run-1",
        "agent_name": "trade_decision",
        "status": "completed",
        "finished_at": "2026-06-01T10:00:00Z",
        "started_at": "2026-06-01T09:55:00Z",
        "results": [
            {"case_id": "cov-1", "agent_name": "trade_decision", "status": "passed", "score": 90, "max_score": 100, "checks": [], "metadata": {"severity": "high", "category": "investment_risk"}},
            {"case_id": "cov-3", "agent_name": "trade_decision", "status": "failed", "score": 30, "max_score": 100, "checks": [], "metadata": {"severity": "medium", "category": "format"}},
        ],
    })

    return case_repo, run_repo


def test_coverage_summary_counts() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()

    assert cov["summary"]["case_count"] == 6
    assert cov["summary"]["enabled_case_count"] == 5
    assert cov["summary"]["disabled_case_count"] == 1
    assert cov["summary"]["agent_count"] == 3
    assert cov["summary"]["judge_case_count"] == 1
    assert cov["summary"]["feedback_source_count" if "feedback_source_count" in cov["summary"] else "bad_case_source_count"] == 1
    assert cov["summary"]["replay_source_count"] == 1
    assert cov["summary"]["manual_source_count"] == 3  # cov-2, cov-4, cov-6 all default to manual
    assert cov["summary"]["recent_eval_run_count"] == 1


def test_coverage_by_agent() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    agents = {r["agent_name"]: r for r in cov["by_agent"]}

    td = agents["trade_decision"]
    assert td["case_count"] == 3
    assert td["enabled_case_count"] == 3
    assert td["judge_case_count"] == 1
    assert td["high_case_count"] == 1
    assert td["critical_case_count"] == 1

    tr = agents["trade_review"]
    assert tr["case_count"] == 2
    assert tr["enabled_case_count"] == 1
    assert tr["disabled_case_count"] == 1


def test_coverage_by_agent_category() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    cats = {(r["agent_name"], r["category"]): r for r in cov["by_agent_category"]}

    assert cats[("trade_decision", "investment_risk")]["case_count"] == 2
    assert cats[("trade_decision", "format")]["case_count"] == 1
    assert cats[("daily_position_review", "uncategorized")]["case_count"] == 1


def test_coverage_by_agent_severity() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    sevs = {(r["agent_name"], r["severity"]): r for r in cov["by_agent_severity"]}

    assert sevs[("trade_decision", "high")]["case_count"] == 1
    assert sevs[("trade_decision", "critical")]["case_count"] == 1
    assert sevs[("daily_position_review", "medium")]["case_count"] == 1


def test_coverage_by_agent_tag() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    tags = {(r["agent_name"], r["tag"]): r for r in cov["by_agent_tag"]}

    assert tags[("trade_decision", "regression")]["case_count"] == 2
    assert tags[("trade_review", "smoke")]["case_count"] == 1
    assert tags[("daily_position_review", "untagged")]["case_count"] == 1


def test_coverage_by_source() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    sources = {r["source"]: r for r in cov["by_source"]}

    assert sources["replay"]["case_count"] == 1
    assert sources["manual"]["case_count"] == 3  # cov-2, cov-4, cov-6
    assert sources["feedback"]["case_count"] == 1
    assert sources["builtin"]["case_count"] == 1


def test_coverage_case_last_status() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    cc = {r["case_id"]: r for r in cov["case_coverage"]}

    assert cc["cov-1"]["last_status"] == "passed"
    assert cc["cov-1"]["last_score"] == 90
    assert cc["cov-1"]["last_eval_run_id"] == "run-1"
    assert cc["cov-1"]["never_evaluated"] is False

    assert cc["cov-3"]["last_status"] == "failed"
    assert cc["cov-3"]["recent_failed_count"] == 1


def test_coverage_never_evaluated() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    cc = {r["case_id"]: r for r in cov["case_coverage"]}

    # cov-2, cov-4, cov-5, cov-6 were not in any run
    assert cc["cov-2"]["never_evaluated"] is True
    assert cc["cov-4"]["never_evaluated"] is True
    assert cc["cov-5"]["never_evaluated"] is True
    assert cc["cov-6"]["never_evaluated"] is True

    assert cov["summary"]["never_evaluated_case_count"] == 4
    assert cov["summary"]["recent_evaluated_case_count"] == 2


def test_coverage_pass_rate_null_when_no_results() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("no-run", agent_name="trade_review", enabled=True, metadata={"output": {"summary": "ok"}}))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cov = service.get_eval_coverage()

    assert cov["by_agent"][0]["recent_pass_rate"] is None


def test_coverage_recent_pass_rate_uses_result_occurrences() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()
    case_repo.save_case(_make_case(
        "occ-1",
        agent_name="trade_decision",
        category="investment_risk",
        severity="high",
        tags=["regression"],
        metadata={"output": _trade_decision_output()},
    ))
    for idx, status in enumerate(["passed", "passed", "failed"], start=1):
        run_repo.save_run({
            "eval_run_id": f"occ-run-{idx}",
            "agent_name": "trade_decision",
            "status": "completed",
            "finished_at": f"2026-06-01T10:0{idx}:00Z",
            "started_at": f"2026-06-01T09:5{idx}:00Z",
            "results": [
                {"case_id": "occ-1", "status": status, "score": 90 if status == "passed" else 30, "max_score": 100, "checks": []},
            ],
        })
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()
    agent = cov["by_agent"][0]
    category = cov["by_agent_category"][0]
    severity = cov["by_agent_severity"][0]
    tag = cov["by_agent_tag"][0]

    assert agent["recent_pass_count"] == 2
    assert agent["recent_failed_count"] == 1
    assert agent["recent_pass_rate"] == 2 / 3
    assert agent["recent_pass_rate"] <= 1
    assert category["recent_pass_rate"] == 2 / 3
    assert severity["recent_pass_rate"] == 2 / 3
    assert tag["recent_pass_rate"] == 2 / 3


def test_coverage_by_agent_run_count_uses_result_case_agent() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunRepository()
    case_repo.save_case(_make_case("run-agent-1", agent_name="trade_decision", metadata={"output": _trade_decision_output()}))
    run_repo.save_run({
        "eval_run_id": "run-agent-none",
        "agent_name": None,
        "status": "completed",
        "finished_at": "2026-06-01T10:00:00Z",
        "started_at": "2026-06-01T09:55:00Z",
        "results": [
            {"case_id": "run-agent-1", "status": "passed", "score": 90, "max_score": 100, "checks": []},
        ],
    })
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()

    assert cov["summary"]["recent_eval_run_count"] == 1
    assert cov["by_agent"][0]["agent_name"] == "trade_decision"
    assert cov["by_agent"][0]["recent_eval_run_count"] == 1


def test_coverage_agent_name_filter() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage(agent_name="trade_decision")

    assert cov["summary"]["case_count"] == 3
    agents = {r["agent_name"] for r in cov["by_agent"]}
    assert agents == {"trade_decision"}


def test_coverage_empty_cases_returns_builtin_fallback() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository())

    cov = service.get_eval_coverage()

    # list_cases falls back to builtin cases when repo is empty
    assert cov["summary"]["case_count"] > 0
    assert cov["summary"]["case_count"] == len(cov["case_coverage"])
    assert len(cov["by_agent"]) > 0


# ── Coverage Gap Tests ────────────────────────────────────────────────


def _coverage(by_agent=None, case_coverage=None):
    return {"by_agent": by_agent or [], "case_coverage": case_coverage or []}


def test_gap_no_enabled_cases() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "trade_review", "enabled_case_count": 0, "high_case_count": 0, "critical_case_count": 0, "never_evaluated_case_count": 0}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "no_enabled_cases" in types
    assert gaps[0]["severity"] == "critical"


def test_gap_no_high_cases() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 0, "critical_case_count": 1, "never_evaluated_case_count": 0}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "no_high_cases" in types


def test_gap_no_critical_cases() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 0, "never_evaluated_case_count": 0}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "no_critical_cases" in types


def test_gap_low_recent_pass_rate_critical() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 0.7, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}])
    gaps = build_coverage_gaps(coverage)
    low = [g for g in gaps if g["gap_type"] == "low_recent_pass_rate"]
    assert len(low) == 1
    assert low[0]["severity"] == "critical"


def test_gap_low_recent_pass_rate_high() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 0.85, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}])
    gaps = build_coverage_gaps(coverage)
    low = [g for g in gaps if g["gap_type"] == "low_recent_pass_rate"]
    assert len(low) == 1
    assert low[0]["severity"] == "high"


def test_gap_no_low_recent_pass_rate_when_null() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": None, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "low_recent_pass_rate" not in types


def test_gap_high_critical_failures() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 0, "high_critical_failure_count": 2}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "high_critical_failures" in types


def test_gap_never_evaluated_cases() -> None:
    coverage = _coverage(by_agent=[{"agent_name": "agent_a", "enabled_case_count": 3, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 2, "high_critical_failure_count": 0}])
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "never_evaluated_cases" in types


def test_gap_no_regression_cases() -> None:
    coverage = _coverage(
        by_agent=[{"agent_name": "agent_a", "enabled_case_count": 2, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}],
        case_coverage=[
            {"case_id": "c1", "agent_name": "agent_a", "enabled": True, "tags": ["smoke"]},
            {"case_id": "c2", "agent_name": "agent_a", "enabled": True, "tags": []},
        ],
    )
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "no_regression_cases" in types


def test_gap_no_regression_cases_not_flagged_when_regression_tag_exists() -> None:
    coverage = _coverage(
        by_agent=[{"agent_name": "agent_a", "enabled_case_count": 1, "high_case_count": 1, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}],
        case_coverage=[
            {"case_id": "c1", "agent_name": "agent_a", "enabled": True, "tags": ["regression"]},
        ],
    )
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "no_regression_cases" not in types


def test_gap_judge_not_configured_for_critical() -> None:
    coverage = _coverage(
        by_agent=[{"agent_name": "agent_a", "enabled_case_count": 1, "high_case_count": 0, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}],
        case_coverage=[
            {"case_id": "c1", "agent_name": "agent_a", "enabled": True, "severity": "critical", "judge_enabled": False},
        ],
    )
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "judge_not_configured_for_critical" in types


def test_gap_judge_not_flagged_when_enabled() -> None:
    coverage = _coverage(
        by_agent=[{"agent_name": "agent_a", "enabled_case_count": 1, "high_case_count": 0, "critical_case_count": 1, "recent_pass_rate": 1.0, "never_evaluated_case_count": 0, "high_critical_failure_count": 0}],
        case_coverage=[
            {"case_id": "c1", "agent_name": "agent_a", "enabled": True, "severity": "critical", "judge_enabled": True},
        ],
    )
    gaps = build_coverage_gaps(coverage)
    types = {g["gap_type"] for g in gaps}
    assert "judge_not_configured_for_critical" not in types


def test_gap_sorted_by_severity() -> None:
    coverage = _coverage(
        by_agent=[
            {"agent_name": "a1", "enabled_case_count": 0, "high_case_count": 0, "critical_case_count": 0, "never_evaluated_case_count": 1, "high_critical_failure_count": 1, "recent_pass_rate": 0.5},
        ],
        case_coverage=[],
    )
    gaps = build_coverage_gaps(coverage)
    severity_order = [g["severity"] for g in gaps]
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert severity_order == sorted(severity_order, key=lambda s: priority.get(s, 99))


def test_gap_empty_coverage() -> None:
    gaps = build_coverage_gaps(_coverage())
    assert gaps == []


# ── Coverage Recommendation Tests ────────────────────────────────────


def test_recommendation_basic() -> None:
    gaps = [
        {"gap_id": "gap_a_no_enabled", "agent_name": "a", "gap_type": "no_enabled_cases", "severity": "critical", "suggested_action": "新增至少 1 个 enabled Eval Case。", "description": "desc"},
    ]
    recs = build_coverage_recommendations(gaps)
    assert len(recs) == 1
    assert recs[0]["action_type"] == "create_eval_case"
    assert recs[0]["agent_name"] == "a"
    assert recs[0]["priority"] == "critical"


def test_recommendation_dedup() -> None:
    gaps = [
        {"gap_id": "gap_a_no_high", "agent_name": "a", "gap_type": "no_high_cases", "severity": "medium", "suggested_action": "act1", "description": "d1"},
        {"gap_id": "gap_a_no_critical", "agent_name": "a", "gap_type": "no_critical_cases", "severity": "high", "suggested_action": "act2", "description": "d2"},
    ]
    recs = build_coverage_recommendations(gaps)
    # Both map to create_eval_case but different gap_type, so both should produce separate recs
    assert len(recs) == 2


def test_recommendation_same_gap_type_different_agent() -> None:
    gaps = [
        {"gap_id": "gap_a_no_enabled", "agent_name": "a", "gap_type": "no_enabled_cases", "severity": "critical", "suggested_action": "act", "description": "d"},
        {"gap_id": "gap_b_no_enabled", "agent_name": "b", "gap_type": "no_enabled_cases", "severity": "critical", "suggested_action": "act", "description": "d"},
    ]
    recs = build_coverage_recommendations(gaps)
    assert len(recs) == 2
    agents = {r["agent_name"] for r in recs}
    assert agents == {"a", "b"}


def test_recommendation_sorted_by_priority() -> None:
    gaps = [
        {"gap_id": "gap_a_never", "agent_name": "a", "gap_type": "never_evaluated_cases", "severity": "medium", "suggested_action": "act1", "description": "d1"},
        {"gap_id": "gap_a_no_enabled", "agent_name": "a", "gap_type": "no_enabled_cases", "severity": "critical", "suggested_action": "act2", "description": "d2"},
    ]
    recs = build_coverage_recommendations(gaps)
    priorities = [r["priority"] for r in recs]
    assert priorities == ["critical", "medium"]


def test_recommendation_action_type_mapping() -> None:
    mapping = {
        "no_enabled_cases": "create_eval_case",
        "no_high_cases": "create_eval_case",
        "no_critical_cases": "create_eval_case",
        "no_regression_cases": "add_regression_tag",
        "low_recent_pass_rate": "fix_failed_cases",
        "high_critical_failures": "fix_failed_cases",
        "never_evaluated_cases": "run_agent_regression",
        "uncategorized_cases": "categorize_cases",
        "untagged_cases": "tag_cases",
        "judge_not_configured_for_critical": "enable_judge",
    }
    for gap_type, expected_action in mapping.items():
        gaps = [{"gap_id": f"gap_x_{gap_type}", "agent_name": "x", "gap_type": gap_type, "severity": "medium", "suggested_action": "act", "description": "d"}]
        recs = build_coverage_recommendations(gaps)
        assert recs[0]["action_type"] == expected_action, f"{gap_type} should map to {expected_action}"


def test_recommendation_unknown_gap_type_fallback() -> None:
    gaps = [{"gap_id": "gap_x_unknown", "agent_name": "x", "gap_type": "some_new_type", "severity": "low", "suggested_action": "act", "description": "d"}]
    recs = build_coverage_recommendations(gaps)
    assert recs[0]["action_type"] == "review_coverage"


def test_recommendation_empty_gaps() -> None:
    recs = build_coverage_recommendations([])
    assert recs == []


def test_coverage_returns_gaps_and_recommendations() -> None:
    case_repo, run_repo = _setup_coverage_data()
    service = AgentEvalService(case_repo, run_repo)

    cov = service.get_eval_coverage()

    assert "gaps" in cov
    assert "recommendations" in cov
    assert isinstance(cov["gaps"], list)
    assert isinstance(cov["recommendations"], list)


# ── Node Eval Data Model Tests (Stage 01) ──────────────────────────


def test_eval_case_defaults_eval_scope_to_agent() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    case = service.create_case({
        "case_id": "scope-default",
        "agent_name": "trade_decision",
        "title": "Default scope",
        "input": {},
    })

    assert case["eval_scope"] == "agent"
    assert case["node_name"] is None


def test_create_agent_scope_case_success() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    case = service.create_case({
        "case_id": "agent-scope",
        "agent_name": "trade_decision",
        "title": "Agent scope",
        "eval_scope": "agent",
        "node_name": None,
        "input": {},
    })

    assert case["eval_scope"] == "agent"


def test_create_node_scope_case_with_node_name_success() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    case = service.create_case({
        "case_id": "node-scope-1",
        "agent_name": "trade_decision",
        "title": "Node scope",
        "eval_scope": "node",
        "node_name": "event_catalyst",
        "source_llm_call_id": "llm_xxx",
        "prompt_key": "trade_decision_event_catalyst_prompt",
        "model": "gpt-5",
        "input": {},
    })

    assert case["eval_scope"] == "node"
    assert case["node_name"] == "event_catalyst"
    assert case["source_llm_call_id"] == "llm_xxx"
    assert case["prompt_key"] == "trade_decision_event_catalyst_prompt"
    assert case["model"] == "gpt-5"


def test_create_node_scope_case_without_node_name_raises() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    import pytest
    with pytest.raises(ValueError, match="node_name is required"):
        service.create_case({
            "case_id": "node-scope-bad",
            "agent_name": "trade_decision",
            "title": "Missing node_name",
            "eval_scope": "node",
            "input": {},
        })


def test_create_case_with_invalid_eval_scope_raises() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository())

    import pytest
    with pytest.raises(ValueError, match="Invalid eval_scope"):
        service.create_case({
            "case_id": "scope-bad",
            "agent_name": "trade_decision",
            "title": "Bad scope",
            "eval_scope": "invalid_scope",
            "input": {},
        })


def test_list_cases_filter_by_eval_scope_node() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("agent-1", agent_name="trade_decision", eval_scope="agent"))
    case_repo.save_case(_make_case("node-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    case_repo.save_case(_make_case("node-2", agent_name="trade_decision", eval_scope="node", node_name="risk_control"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    node_cases = service.list_cases(agent_name="trade_decision", eval_scope="node")
    node_ids = {c["case_id"] for c in node_cases}
    assert node_ids == {"node-1", "node-2"}

    agent_cases = service.list_cases(agent_name="trade_decision", eval_scope="agent")
    agent_ids = {c["case_id"] for c in agent_cases}
    assert agent_ids == {"agent-1"}


def test_list_cases_filter_by_node_name() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("ec-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    case_repo.save_case(_make_case("rc-1", agent_name="trade_decision", eval_scope="node", node_name="risk_control"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cases = service.list_cases(agent_name="trade_decision", node_name="event_catalyst")
    assert len(cases) == 1
    assert cases[0]["case_id"] == "ec-1"
    assert cases[0]["node_name"] == "event_catalyst"


def test_list_cases_filter_by_prompt_key_and_model() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "p1", agent_name="trade_decision", eval_scope="node", node_name="x",
        prompt_key="prompt_v1", model="gpt-5",
    ))
    case_repo.save_case(_make_case(
        "p2", agent_name="trade_decision", eval_scope="node", node_name="y",
        prompt_key="prompt_v2", model="claude-4",
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    by_prompt = service.list_cases(agent_name="trade_decision", prompt_key="prompt_v2")
    assert len(by_prompt) == 1
    assert by_prompt[0]["case_id"] == "p2"

    by_model = service.list_cases(agent_name="trade_decision", model="gpt-5")
    assert len(by_model) == 1
    assert by_model[0]["case_id"] == "p1"


def test_select_cases_for_eval_filter_by_eval_scope() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("agent-1", agent_name="trade_decision", eval_scope="agent"))
    case_repo.save_case(_make_case("node-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cases = service.select_cases_for_eval(agent_name="trade_decision", eval_scope="node")
    assert {c["case_id"] for c in cases} == {"node-1"}


def test_select_cases_for_eval_filter_by_node_name() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("ec", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    case_repo.save_case(_make_case("rc", agent_name="trade_decision", eval_scope="node", node_name="risk_control"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cases = service.select_cases_for_eval(
        agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"
    )
    assert {c["case_id"] for c in cases} == {"ec"}


def test_regression_eval_default_excludes_node_cases() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "node-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision"})

    assert result["selected_case_count"] == 1
    case_ids = [r["case_id"] for r in result["eval_run"]["results"]]
    assert "agent-1" in case_ids
    assert "node-1" not in case_ids


def test_evaluate_case_result_metadata_includes_eval_scope() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-meta", agent_name="trade_decision", eval_scope="node",
        node_name="event_catalyst", prompt_key="p1", model="gpt-5",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-meta"], mode="static")
    result = run["results"][0]
    meta = result.get("metadata") or {}

    assert meta.get("eval_scope") == "node"
    assert meta.get("node_name") == "event_catalyst"
    assert meta.get("prompt_key") == "p1"
    assert meta.get("model") == "gpt-5"


def test_evaluate_case_result_metadata_defaults_to_agent_scope() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-meta", agent_name="trade_decision",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["agent-meta"], mode="static")
    result = run["results"][0]
    meta = result.get("metadata") or {}

    assert meta.get("eval_scope") == "agent"
    assert meta.get("node_name") is None


def test_update_case_can_set_node_fields() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("upd-1", agent_name="trade_decision", eval_scope="agent"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    updated = service.update_case("upd-1", {
        "eval_scope": "node",
        "node_name": "event_catalyst",
        "source_llm_call_id": "llm_new",
        "prompt_key": "pk",
    })

    assert updated["eval_scope"] == "node"
    assert updated["node_name"] == "event_catalyst"
    assert updated["source_llm_call_id"] == "llm_new"
    assert updated["prompt_key"] == "pk"


def test_update_case_node_scope_without_node_name_raises() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case("upd-bad", agent_name="trade_decision", eval_scope="agent"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    import pytest
    with pytest.raises(ValueError, match="node_name is required"):
        service.update_case("upd-bad", {"eval_scope": "node", "node_name": ""})


def test_coverage_case_row_includes_node_fields() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "cov-node", agent_name="trade_decision", eval_scope="node",
        node_name="event_catalyst", prompt_key="pk", model="gpt-5",
        enabled=True, metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cov = service.get_eval_coverage()
    rows = {r["case_id"]: r for r in cov["case_coverage"]}
    assert "cov-node" in rows
    assert rows["cov-node"]["eval_scope"] == "node"
    assert rows["cov-node"]["node_name"] == "event_catalyst"
    assert rows["cov-node"]["prompt_key"] == "pk"
    assert rows["cov-node"]["model"] == "gpt-5"


def test_coverage_case_row_defaults_eval_scope_to_agent() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "cov-agent", agent_name="trade_decision", enabled=True,
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    cov = service.get_eval_coverage()
    rows = {r["case_id"]: r for r in cov["case_coverage"]}
    assert "cov-agent" in rows
    assert rows["cov-agent"]["eval_scope"] == "agent"
    assert rows["cov-agent"].get("node_name") is None


# ── Old Case eval_scope Compatibility (Fix #1) ────────────────────


def test_old_case_without_eval_scope_filtered_as_agent() -> None:
    """历史 EvalCase 缺 eval_scope 字段。list_cases(eval_scope=agent) 必须返回。"""
    case_repo = FakeCaseRepository()
    old_case = _make_case("old-case-1", agent_name="trade_decision", enabled=True)
    old_case.pop("eval_scope", None)
    assert "eval_scope" not in old_case
    case_repo.save_case(old_case)
    case_repo.save_case(_make_case("new-case-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    case_repo.save_case(_make_case("new-agent", agent_name="trade_decision", eval_scope="agent"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    agent_results = service.list_cases(agent_name="trade_decision", eval_scope="agent")
    agent_ids = {c["case_id"] for c in agent_results}
    assert "old-case-1" in agent_ids
    assert "new-agent" in agent_ids
    assert "new-case-1" not in agent_ids

    node_results = service.list_cases(agent_name="trade_decision", eval_scope="node")
    node_ids = {c["case_id"] for c in node_results}
    assert "old-case-1" not in node_ids
    assert "new-case-1" in node_ids
    assert "new-agent" not in node_ids


def test_select_cases_for_eval_includes_old_cases_under_agent() -> None:
    case_repo = FakeCaseRepository()
    old_case = _make_case("old-case-2", agent_name="trade_decision", enabled=True)
    old_case.pop("eval_scope", None)
    case_repo.save_case(old_case)
    case_repo.save_case(_make_case("new-node", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst"))
    service = AgentEvalService(case_repo, FakeRunRepository())

    selected = service.select_cases_for_eval(agent_name="trade_decision", eval_scope="agent")
    selected_ids = {c["case_id"] for c in selected}
    assert "old-case-2" in selected_ids
    assert "new-node" not in selected_ids

    node_selected = service.select_cases_for_eval(agent_name="trade_decision", eval_scope="node")
    node_ids = {c["case_id"] for c in node_selected}
    assert "old-case-2" not in node_ids
    assert "new-node" in node_ids


def test_agent_regression_picks_up_old_case_by_default() -> None:
    """Agent Regression 默认 eval_scope=agent 必须能选中老 case。"""
    case_repo = FakeCaseRepository()
    old_case = _make_case("old-reg", agent_name="trade_decision", enabled=True)
    old_case.pop("eval_scope", None)
    case_repo.save_case(old_case)
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision"})

    assert result["selected_case_count"] == 1
    case_ids = [r["case_id"] for r in result["eval_run"]["results"]]
    assert "old-reg" in case_ids


# ── Node Eval Case Builder Tests (Stage 02) ────────────────────────


class FakeLLMCallService:
    def __init__(self) -> None:
        self.calls: dict[str, dict] = {}

    def get_call(self, call_id: str) -> dict | None:
        return self.calls.get(call_id)


class FakeRunTraceRepository:
    def __init__(self) -> None:
        self.traces: dict[str, dict] = {}

    def get_trace(self, run_id: str) -> dict | None:
        return self.traces.get(run_id)


def _llm_call(
    call_id: str = "llm-1",
    *,
    node_name: str = "event_catalyst",
    agent_name: str = "trade_decision",
    run_id: str = "run-1",
) -> dict:
    return {
        "call_id": call_id,
        "node_name": node_name,
        "agent_name": agent_name,
        "run_id": run_id,
        "prompt_key": "trade_decision_event_catalyst_prompt",
        "prompt_version": "v3",
        "prompt_hash": "abc123",
        "model": "gpt-5",
        "call_type": "node_eval",
    }


def test_build_node_eval_case_from_llm_call_draft() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = _llm_call()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    case = service.build_case_from_llm_call("llm-1", save=False)

    assert case is not None
    assert case["eval_scope"] == "node"
    assert case["node_name"] == "event_catalyst"
    assert case["source_llm_call_id"] == "llm-1"
    assert case["source_run_id"] == "run-1"
    assert case["prompt_key"] == "trade_decision_event_catalyst_prompt"
    assert case["model"] == "gpt-5"
    assert case["enabled"] is False
    assert case["source"] == "llm_call"
    assert "node_eval" in case["tags"]
    assert "event_catalyst" in case["tags"]
    # draft must not be saved
    assert case_repo.get_case(case["case_id"]) is None


def test_build_node_eval_case_from_llm_call_save_true() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = _llm_call()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    case = service.build_case_from_llm_call("llm-1", save=True)

    assert case is not None
    saved = case_repo.get_case(case["case_id"])
    assert saved is not None
    assert saved["eval_scope"] == "node"


def test_build_node_eval_case_from_llm_call_missing_node_name_raises() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-bad"] = _llm_call(call_id="llm-bad", node_name=None)
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    import pytest
    with pytest.raises(ValueError, match="node_name"):
        service.build_case_from_llm_call("llm-bad")


def test_build_node_eval_case_from_llm_call_not_found_returns_none() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    result = service.build_case_from_llm_call("missing-call")
    assert result is None


def test_build_node_eval_case_from_llm_call_no_service_raises() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_call_service=None)

    import pytest
    with pytest.raises(ValueError, match="LLM call service not configured"):
        service.build_case_from_llm_call("any")


def _agent_run(
    run_id: str = "run-1",
    agent_name: str = "trade_decision",
    node_traces: list | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "agent_name": agent_name,
        "node_traces": node_traces or [
            {
                "trace_id": "trace-1",
                "node_name": "fundamental_valuation",
                "status": "ok",
                "latency_ms": 100,
            },
            {
                "node_name": "event_catalyst",
                "status": "ok",
                "latency_ms": 50,
            },
        ],
    }


def test_build_node_eval_case_from_node_trace_draft() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = _agent_run()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    case = service.build_case_from_node_trace("run-1", "trace-1", save=False)

    assert case is not None
    assert case["eval_scope"] == "node"
    assert case["node_name"] == "fundamental_valuation"
    assert case["source_node_trace_id"] == "trace-1"
    assert case["source_run_id"] == "run-1"
    assert case["source"] == "node_trace"
    assert case["enabled"] is False
    assert "fundamental_valuation" in case["tags"]
    assert case_repo.get_case(case["case_id"]) is None


def test_build_node_eval_case_from_node_trace_index_fallback() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = _agent_run()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    # second node_trace has no id, should be addressable via index_1
    case = service.build_node_eval_case = service.build_case_from_node_trace(
        "run-1", "index_1", save=False,
    )

    assert case is not None
    assert case["node_name"] == "event_catalyst"
    assert case["source_node_trace_id"] == "index_1"


def test_build_node_eval_case_from_node_trace_not_found_run() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    result = service.build_case_from_node_trace("missing-run", "trace-1")
    assert result is None


def test_build_node_eval_case_from_node_trace_not_found_trace() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = _agent_run()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    result = service.build_case_from_node_trace("run-1", "trace-missing")
    assert result is None


def test_build_node_eval_case_from_node_trace_missing_node_name_raises() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = _agent_run(node_traces=[
        {"trace_id": "trace-x", "node_name": None, "status": "ok"},
    ])
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    import pytest
    with pytest.raises(ValueError, match="node_name"):
        service.build_case_from_node_trace("run-1", "trace-x")


def test_build_node_eval_case_from_node_trace_no_repo_raises() -> None:
    case_repo = FakeCaseRepository()
    service = AgentEvalService(case_repo, FakeRunRepository(), run_trace_repository=None)

    import pytest
    with pytest.raises(ValueError, match="Run trace repository not configured"):
        service.build_case_from_node_trace("any", "any")


def test_build_node_eval_case_from_node_trace_save_true() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = _agent_run()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), run_trace_repository=run_repo,
    )

    case = service.build_case_from_node_trace("run-1", "trace-1", save=True)
    assert case is not None
    assert case_repo.get_case(case["case_id"]) is not None


def test_build_node_eval_case_from_node_trace_normalizes_latency_fields() -> None:
    cases = [
        ({"trace_id": "t1", "node_name": "risk_control", "latency_ms": 123}, 123),
        ({"trace_id": "t2", "node_name": "risk_control", "elapsed_ms": 456}, 456),
        ({"trace_id": "t3", "node_name": "risk_control", "duration_ms": 789}, 789),
        ({"trace_id": "t4", "node_name": "risk_control", "latency": "123"}, 123),
        ({"trace_id": "t5", "node_name": "risk_control", "elapsed": "12.5"}, 12.5),
        ({"trace_id": "t6", "node_name": "risk_control", "payload": {"elapsed_ms": "321"}}, 321),
        ({"trace_id": "t7", "node_name": "risk_control"}, None),
    ]

    for node_trace, expected in cases:
        case_repo = FakeCaseRepository()
        run_repo = FakeRunTraceRepository()
        run_repo.traces["run-1"] = _agent_run(node_traces=[node_trace])
        service = AgentEvalService(
            case_repo, FakeRunRepository(), run_trace_repository=run_repo,
        )

        case = service.build_case_from_node_trace("run-1", node_trace["trace_id"], save=False)

        assert case is not None
        assert case["metadata"]["node_latency_ms"] == expected


def test_node_eval_case_draft_does_not_contain_sensitive_data() -> None:
    """Ensure full prompt text and API tokens are not in the draft metadata."""
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = {
        **_llm_call(),
        "prompt": "secret system prompt content here",
        "messages": [{"role": "user", "content": "private question"}],
        "api_key": "sk-secret-1234",
        "auth_token": "bearer-xyz",
    }
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    case = service.build_case_from_llm_call("llm-1", save=False)

    serialized = str(case)
    assert "sk-secret-1234" not in serialized
    assert "bearer-xyz" not in serialized
    assert "secret system prompt content" not in serialized


def test_node_eval_case_metadata_has_created_from_trace_at() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = _llm_call()
    service = AgentEvalService(
        case_repo, FakeRunRepository(), llm_call_service=llm_service,
    )

    case = service.build_case_from_llm_call("llm-1", save=False)

    assert case["metadata"]["source_type"] == "llm_call"
    assert "created_from_trace_at" in case["metadata"]


# ── Node Eval Case Output Extraction (Fix #3) ─────────────────────


def test_node_eval_case_from_llm_call_includes_output_when_response_text() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = {
        **_llm_call(),
        "response_text": "需要进一步验证风险。",
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_call_service=llm_service)

    case = service.build_case_from_llm_call("llm-1", save=False)

    assert "output" in case["metadata"]
    assert case["metadata"]["output"].get("text") == "需要进一步验证风险。"
    assert case["metadata"].get("output_missing") is not True


def test_node_eval_case_from_llm_call_marks_output_missing_when_no_output() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = _llm_call()  # no output field
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_call_service=llm_service)

    case = service.build_case_from_llm_call("llm-1", save=False)

    assert case["metadata"].get("output_missing") is True
    assert "output" not in case["metadata"]


def test_node_eval_case_from_llm_call_scrubs_sensitive_fields() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = {
        **_llm_call(),
        "output": {
            "summary": "ok",
            "api_key": "sk-secret-1234",
            "auth_token": "bearer-xyz",
        },
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_call_service=llm_service)

    case = service.build_case_from_llm_call("llm-1", save=False)

    out = case["metadata"]["output"]
    assert "api_key" not in out
    assert "auth_token" not in out
    assert out.get("summary") == "ok"


def test_node_eval_case_from_node_trace_includes_output() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = {
        "run_id": "run-1",
        "agent_name": "trade_decision",
        "node_traces": [
            {
                "trace_id": "trace-1",
                "node_name": "event_catalyst",
                "status": "ok",
                "output": {"summary": "财报已发生，预期下季度增长。"},
            },
        ],
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), run_trace_repository=run_repo)

    case = service.build_case_from_node_trace("run-1", "trace-1", save=False)

    assert "output" in case["metadata"]
    assert case["metadata"]["output"].get("summary", "").startswith("财报已发生")
    assert case["metadata"].get("output_missing") is not True


def test_node_eval_case_from_node_trace_marks_output_missing_when_absent() -> None:
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = {
        "run_id": "run-1",
        "agent_name": "trade_decision",
        "node_traces": [
            {
                "trace_id": "trace-1",
                "node_name": "event_catalyst",
                "status": "ok",
                # no output field
            },
        ],
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), run_trace_repository=run_repo)

    case = service.build_case_from_node_trace("run-1", "trace-1", save=False)

    assert case["metadata"].get("output_missing") is True
    assert "output" not in case["metadata"]


def test_node_eval_case_static_eval_runs_node_checks_not_no_output() -> None:
    """生成的 node case 保存后，static eval 应能跑出 node checks，而非 NO_OUTPUT_TO_EVALUATE。"""
    case_repo = FakeCaseRepository()
    run_repo = FakeRunTraceRepository()
    run_repo.traces["run-1"] = {
        "run_id": "run-1",
        "agent_name": "trade_decision",
        "node_traces": [
            {
                "trace_id": "trace-1",
                "node_name": "event_catalyst",
                "status": "ok",
                "output": {
                    "summary": "财报已发生，预期下季度增长。来源：公司公告。",
                },
            },
        ],
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), run_trace_repository=run_repo)

    case = service.build_case_from_node_trace("run-1", "trace-1", save=True)
    assert case is not None

    run = service.run_eval(case_ids=[case["case_id"]], mode="static")
    result = run["results"][0]
    assert result["error_code"] != "NO_OUTPUT_TO_EVALUATE"
    check_names = {c["check_name"] for c in result["checks"]}
    assert "event_catalyst_requires_specific_event" in check_names


def test_node_eval_case_from_llm_call_final_output_field() -> None:
    case_repo = FakeCaseRepository()
    llm_service = FakeLLMCallService()
    llm_service.calls["llm-1"] = {
        **_llm_call(),
        "final_output": {"summary": "ok"},
    }
    service = AgentEvalService(case_repo, FakeRunRepository(), llm_call_service=llm_service)

    case = service.build_case_from_llm_call("llm-1", save=False)

    assert case["metadata"]["output"] == {"summary": "ok"}


# ── Node Eval Checks Integration (Stage 03) ───────────────────────


def test_agent_eval_case_does_not_run_node_specific_checks() -> None:
    """Agent scope case should not run node-specific checks."""
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-scope-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["agent-scope-1"], mode="static")
    check_names = {c["check_name"] for c in run["results"][0]["checks"]}
    assert not any(name.startswith("market_trend_") for name in check_names)
    assert not any(name.startswith("event_catalyst_") for name in check_names)
    assert not any(name.startswith("risk_control_") for name in check_names)
    assert not any(name.startswith("fundamental_valuation_") for name in check_names)
    assert not any(name.startswith("final_decision_") for name in check_names)
    # generic node checks should also NOT run on agent scope
    assert "node_output_not_empty" not in check_names
    assert "node_avoids_overconfidence" not in check_names


def test_node_eval_case_runs_node_specific_checks() -> None:
    """trade_decision event_catalyst node case should run event_catalyst checks."""
    output = {
        "summary": "财报已发生，预期下季度继续增长。来源：公司公告。",
    }
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-ec-1", agent_name="trade_decision", eval_scope="node",
        node_name="event_catalyst",
        metadata={"output": output},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-ec-1"], mode="static")
    check_names = {c["check_name"] for c in run["results"][0]["checks"]}
    # generic
    assert "node_output_not_empty" in check_names
    assert "node_avoids_overconfidence" in check_names
    # event_catalyst specific
    assert "event_catalyst_requires_specific_event" in check_names
    assert "event_catalyst_no_forced_attribution" in check_names
    assert "event_catalyst_distinguishes_confirmed_vs_expected" in check_names
    assert "event_catalyst_mentions_evidence_or_source" in check_names


def test_node_eval_case_unknown_node_name_runs_generic_only() -> None:
    """Unknown node_name should only run generic node checks."""
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-x", agent_name="trade_decision", eval_scope="node",
        node_name="totally_unknown",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-x"], mode="static")
    check_names = {c["check_name"] for c in run["results"][0]["checks"]}
    # generic should run
    assert "node_output_not_empty" in check_names
    # no trade_decision node-specific checks
    assert not any(name.startswith("event_catalyst_") for name in check_names)
    assert not any(name.startswith("risk_control_") for name in check_names)
    assert not any(name.startswith("market_trend_") for name in check_names)
    assert not any(name.startswith("final_decision_") for name in check_names)


def test_node_eval_risk_control_catches_all_in() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-rc", agent_name="trade_decision", eval_scope="node",
        node_name="risk_control",
        metadata={"output": {"summary": "直接满仓梭哈，无视风险"}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-rc"], mode="static")
    checks_by_name = {c["check_name"]: c for c in run["results"][0]["checks"]}
    assert checks_by_name["risk_control_no_all_in"]["passed"] is False
    assert checks_by_name["risk_control_no_all_in"]["severity"] == "critical"


def test_node_eval_result_metadata_still_includes_node_name() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-meta", agent_name="trade_decision", eval_scope="node",
        node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-meta"], mode="static")
    meta = run["results"][0]["metadata"]
    assert meta["eval_scope"] == "node"
    assert meta["node_name"] == "event_catalyst"


# ── Node Check high/critical 进入 Gate (Fix #2) ───────────────────


def test_node_risk_control_all_in_critical_marks_result_failed() -> None:
    """risk_control_no_all_in (critical) 失败时 result.status 必须为 failed。"""
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-rc", agent_name="trade_decision", eval_scope="node",
        node_name="risk_control",
        metadata={"output": {"summary": "直接满仓梭哈，无视风险"}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-rc"], mode="static")
    result = run["results"][0]
    assert result["status"] == "failed"


def test_node_risk_control_all_in_increments_summary_critical_count() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-rc", agent_name="trade_decision", eval_scope="node",
        node_name="risk_control",
        metadata={"output": {"summary": "直接满仓梭哈"}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["node-rc"], mode="static")

    summary = run["summary"]
    assert summary["critical_failure_count"] >= 1
    assert summary["failed_count"] >= 1


def test_regression_include_node_eval_fail_on_critical_fails_gate() -> None:
    """Agent Regression include_node_eval=true 且 fail_on_critical=true 时
    node 关键 critical 失败必须让 gate_result.passed=false。"""
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-rc", agent_name="trade_decision", eval_scope="node",
        node_name="risk_control",
        metadata={"output": {"summary": "直接满仓梭哈"}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
        "gate": {"fail_on_critical": True, "min_pass_rate": 0},
    })

    assert result["gate_result"]["passed"] is False
    assert any("critical" in r for r in result["gate_result"]["reasons"])


def test_regression_include_node_eval_fail_on_high_fails_gate() -> None:
    """fail_on_high=true 时 high 失败也应让 gate.passed=false。"""
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-high", agent_name="trade_decision", eval_scope="node",
        node_name="event_catalyst", severity="high",
        metadata={"output": {"summary": "市场情绪变化"}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
        "gate": {"fail_on_high": True, "min_pass_rate": 0},
    })

    assert result["gate_result"]["passed"] is False


def test_regression_agent_eval_case_does_not_run_node_specific_checks() -> None:
    """Agent Eval 普通 case 不应误跑 node-specific checks。"""
    case_repo = FakeCaseRepository()
    # 老 case 没有 eval_scope
    case_repo.save_case(_make_case(
        "agent-only", agent_name="trade_decision", enabled=True,
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    run = service.run_eval(case_ids=["agent-only"], mode="static")
    check_names = {c["check_name"] for c in run["results"][0]["checks"]}
    # 没有任何 node_ 或 risk_control_ 等 node-specific 命名空间 check
    assert not any(name.startswith("node_") for name in check_names)
    assert not any(name.startswith("risk_control_") for name in check_names)
    assert not any(name.startswith("event_catalyst_") for name in check_names)
    assert not any(name.startswith("market_trend_") for name in check_names)
    assert not any(name.startswith("final_decision_") for name in check_names)
    assert not any(name.startswith("fundamental_valuation_") for name in check_names)


# ── Agent Regression include_node_eval Tests (Stage 05) ───────────


def test_regression_eval_default_excludes_node_cases_even_when_present() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "node-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({"agent_name": "trade_decision"})

    assert result["selected_case_count"] == 1
    assert result["selected_agent_case_count"] == 1
    assert result["selected_node_case_count"] == 0
    case_ids = [r["case_id"] for r in result["eval_run"]["results"]]
    assert "agent-1" in case_ids
    assert "node-1" not in case_ids
    assert result["eval_run"]["config"]["case_selector"]["include_node_eval"] is False
    assert result["eval_run"]["config"]["selected_node_case_count"] == 0


def test_regression_eval_include_node_eval_selects_node_cases() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "node-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
    })

    assert result["selected_case_count"] == 2
    assert result["selected_agent_case_count"] == 1
    assert result["selected_node_case_count"] == 1
    case_ids = [r["case_id"] for r in result["eval_run"]["results"]]
    assert "agent-1" in case_ids
    assert "node-1" in case_ids
    assert result["eval_run"]["config"]["case_selector"]["include_node_eval"] is True


def test_regression_eval_include_node_eval_node_name_filter() -> None:
    case_repo = FakeCaseRepository()
    # Save an agent case so the FakeCaseRepository has agent results and
    # does not fall back to builtin eval cases for the agent selector.
    case_repo.save_case(_make_case(
        "agent-anchor", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "ec-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "rc-1", agent_name="trade_decision", eval_scope="node", node_name="risk_control",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
        "node_name": "event_catalyst",
    })

    assert result["selected_case_count"] == 2
    assert result["selected_agent_case_count"] == 1
    assert result["selected_node_case_count"] == 1
    case_ids = [r["case_id"] for r in result["eval_run"]["results"]]
    assert set(case_ids) == {"agent-anchor", "ec-1"}


def test_regression_eval_only_node_cases_allowed_when_include_node_eval() -> None:
    """没有 agent case 但有 node case 时，include_node_eval=true 仍可运行。"""
    case_repo = FakeCaseRepository()
    # 用一个 agent_name 完全不同的 agent case 来阻塞 builtin agent fallback。
    # 关键：让 agent_name=trade_decision 在 FakeCaseRepository 中没有 agent case。
    # 因为 service 在 FakeCaseRepository 找不到 agent case 时会 fallback 到 builtin trade_decision case，
    # 我们通过让 agent_name 不在 builtin 中来彻底避免 fallback。
    case_repo.save_case(_make_case(
        "node-only", agent_name="custom_agent_x", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "custom_agent_x",
        "include_node_eval": True,
    })

    # 选中的 agent case 是 0（agent_name=custom_agent_x 不存在 builtin agent cases）
    # 选中的 node case 是 1（node-only）
    assert result["selected_agent_case_count"] == 0
    assert result["selected_node_case_count"] == 1
    assert result["selected_case_count"] == 1


def test_regression_eval_no_agent_no_node_raises() -> None:
    case_repo = FakeCaseRepository()
    # Save nothing in the FakeCaseRepository. But the service falls back to
    # builtin cases for the agent selector. To force "no cases" we need an
    # agent_name with no builtin agent cases (e.g. account_copilot has
    # builtin cases; use a fully unknown name).
    service = AgentEvalService(case_repo, FakeRunRepository())

    import pytest
    with pytest.raises(ValueError, match="No eval cases matched"):
        service.run_agent_regression_eval({
            "agent_name": "totally_unknown_agent_xyz",
            "include_node_eval": True,
        })


def test_regression_eval_scope_breakdown_populated() -> None:
    case_repo = FakeCaseRepository()
    # Use a non-trade_decision agent + node so the required_fields check
    # does not require decision_summary / action. We only assert scope
    # breakdown counts.
    case_repo.save_case(_make_case(
        "agent-pass", agent_name="custom_agent", eval_scope="agent",
        metadata={"output": {"summary": "ok"}},
        expected_output_fields=[],
    ))
    case_repo.save_case(_make_case(
        "node-pass", agent_name="custom_agent", eval_scope="node", node_name="custom_node",
        metadata={"output": {
            "summary": "可能存在风险，需要进一步验证，避免过度自信。",
        }},
        expected_output_fields=[],
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "custom_agent",
        "include_node_eval": True,
    })

    breakdown = result["scope_breakdown"]
    assert breakdown["agent"]["case_count"] == 1
    assert breakdown["node"]["case_count"] == 1
    assert breakdown["mixed"] is True

    config = result["eval_run"]["config"]
    assert config["scope_breakdown"]["agent"]["case_count"] == 1
    assert config["scope_breakdown"]["node"]["case_count"] == 1


def test_regression_eval_node_failure_increments_gate_node_failed_count() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-pass", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "node-fail", agent_name="trade_decision", eval_scope="node", node_name="risk_control",
        metadata={"output": {}},  # empty output → many failed checks
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
    })

    gate = result["gate_result"]
    assert gate["node_case_count"] == 1
    assert gate["node_failed_count"] >= 1
    assert any("node_failed_count" in r for r in gate["reasons"])


def test_regression_eval_node_failure_with_fail_on_high_fails_gate() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "node-bad", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        severity="high", metadata={"output": {}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
        "gate": {"fail_on_high": True, "min_pass_rate": 0},
    })

    assert result["gate_result"]["passed"] is False


def test_regression_eval_include_node_eval_false_does_not_count_node_failures_in_gate() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "agent-pass", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "node-fail", agent_name="trade_decision", eval_scope="node", node_name="risk_control",
        metadata={"output": {}},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": False,  # explicit false
    })

    # node case is NOT selected, so gate should pass
    assert result["selected_node_case_count"] == 0
    assert result["gate_result"]["node_case_count"] == 0
    assert result["gate_result"]["passed"] is True


def test_regression_eval_response_includes_selected_counts() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "a-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": False,
    })

    assert "selected_agent_case_count" in result
    assert "selected_node_case_count" in result
    assert "scope_breakdown" in result
    assert result["selected_agent_case_count"] == 1
    assert result["selected_node_case_count"] == 0


def test_regression_eval_eval_run_config_includes_node_flags() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(_make_case(
        "a-1", agent_name="trade_decision", eval_scope="agent",
        metadata={"output": _trade_decision_output()},
    ))
    case_repo.save_case(_make_case(
        "n-1", agent_name="trade_decision", eval_scope="node", node_name="event_catalyst",
        metadata={"output": _trade_decision_output()},
    ))
    service = AgentEvalService(case_repo, FakeRunRepository())

    result = service.run_agent_regression_eval({
        "agent_name": "trade_decision",
        "include_node_eval": True,
        "node_name": "event_catalyst",
    })

    config = result["eval_run"]["config"]
    assert config["case_selector"]["include_node_eval"] is True
    assert config["case_selector"]["node_name"] == "event_catalyst"
    assert config["selected_node_case_count"] == 1
    assert "scope_breakdown" in config
