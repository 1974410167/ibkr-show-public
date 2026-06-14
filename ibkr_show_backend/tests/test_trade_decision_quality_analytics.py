from fastapi.testclient import TestClient

from app.api.deps import get_trade_decision_repository, require_authenticated_session
from app.main import app
from app.services.trade_decision_quality_analytics import TradeDecisionQualityAnalyticsService


def _doc(
    decision_id: str,
    *,
    symbol: str = "AAPL.US",
    score: int | None = 80,
    level: str = "good",
    passed: bool = True,
    action: str = "hold_no_add",
    trade_plan_action: str = "hold_no_add",
    draft_action: str | None = None,
    final_action: str | None = None,
    ai_policy_assessment: dict | None = None,
    quality_extra: dict | None = None,
    risk_gate: dict | None = None,
    run_trace: list[dict] | None = None,
    created_at: str = "2026-05-20T00:00:00+00:00",
) -> dict:
    doc = {
        "id": decision_id,
        "symbol": symbol,
        "created_at": created_at,
        "action": action,
        "draft_action": draft_action or trade_plan_action,
        "final_action": final_action or action,
        "risk_adjusted_action": final_action or action,
        "trade_plan": {"portfolio_action": trade_plan_action},
        "risk_gate": risk_gate or {"downgraded": False, "blocked": False, "risk_flags": []},
        "run_trace": run_trace or [],
        "metadata": {},
    }
    if ai_policy_assessment is not None:
        doc["ai_policy_assessment"] = ai_policy_assessment
    if score is not None:
        quality = {
            "score": score,
            "level": level,
            "passed": passed,
            "hard_failures": [],
            "warnings": [],
            "flags": [],
            "checks": {},
        }
        quality.update(quality_extra or {})
        doc["decision_quality"] = quality
    return doc


def test_summarize_aggregates_quality_counts_and_legacy_gap() -> None:
    docs = [
        _doc("d1", score=90, level="excellent", passed=True),
        _doc("d2", score=70, level="warning", passed=False),
        _doc("d3", score=None),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)

    assert summary["total_count"] == 3
    assert summary["evaluated_count"] == 2
    assert summary["unevaluated_count"] == 1
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["average_score"] == 80
    assert summary["level_distribution"]["excellent"] == 1
    assert summary["level_distribution"]["warning"] == 1
    assert "some_legacy_decisions_missing_quality" in summary["data_limitations"]


def test_summarize_top_failures_warnings_and_flags_are_count_sorted() -> None:
    docs = [
        _doc("d1", quality_extra={"hard_failures": ["missing_risk_gate"], "warnings": ["repair"], "flags": ["a", "b"]}),
        _doc("d2", quality_extra={"hard_failures": ["missing_risk_gate"], "warnings": ["repair"], "flags": ["a"]}),
        _doc("d3", quality_extra={"hard_failures": ["action_mismatch"], "warnings": ["fallback"], "flags": ["b"]}),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)

    assert summary["top_hard_failures"][0] == {"key": "missing_risk_gate", "count": 2}
    assert summary["top_warnings"][0] == {"key": "repair", "count": 2}
    assert summary["top_flags"][0] == {"key": "a", "count": 2}


def test_summarize_risk_gate_counts_and_flags() -> None:
    docs = [
        _doc("d1", risk_gate={"downgraded": True, "blocked": False, "risk_flags": ["position_limit"]}),
        _doc("d2", risk_gate={"downgraded": False, "blocked": True, "risk_flags": ["position_limit", "event_risk"]}),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)

    assert summary["risk_gate"]["downgraded_count"] == 1
    assert summary["risk_gate"]["blocked_count"] == 1
    assert summary["risk_gate"]["downgrade_rate"] == 0.5
    assert summary["risk_gate"]["top_flags"][0] == {"key": "position_limit", "count": 2}


def test_summarize_structured_output_from_quality_checks_and_run_trace_fallback() -> None:
    docs = [
        _doc(
            "d1",
            quality_extra={
                "checks": {
                    "structured_output_health": {
                        "fallback_count": 2,
                        "repaired_count": 1,
                        "structured_output_failed_count": 1,
                    }
                }
            },
            run_trace=[{"node_name": "debate_judge", "fallback_used": True}],
        ),
        _doc(
            "d2",
            quality_extra={"checks": {}},
            run_trace=[
                {"node_name": "trade_plan", "fallback_used": True, "structured_output": {"ok": True, "repaired": True}},
                {"node_name": "bull_thesis", "structured_output": {"ok": False, "fallback_used": True}},
            ],
        ),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)

    assert summary["structured_output"]["fallback_count"] == 4
    assert summary["structured_output"]["repair_count"] == 2
    assert summary["structured_output"]["failed_count"] == 2
    assert summary["structured_output"]["fallback_nodes"][0]["key"] in {"trade_plan", "bull_thesis", "debate_judge"}


def test_summarize_trade_plan_final_action_mismatch() -> None:
    docs = [
        _doc("d1", trade_plan_action="add_on_pullback", action="hold_no_add"),
        _doc("d2", trade_plan_action="hold_no_add", action="hold_no_add"),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)

    assert summary["action_consistency"]["trade_plan_final_mismatch_count"] == 1
    assert summary["action_consistency"]["trade_plan_final_mismatch_rate"] == 0.5
    assert summary["action_consistency"]["top_mismatch_pairs"] == [{"key": "add_on_pullback -> hold_no_add", "count": 1}]


def test_summarize_action_calibration_metrics() -> None:
    docs = [
        _doc(
            "d1",
            action="add_on_pullback",
            trade_plan_action="add_small",
            draft_action="add_small",
            final_action="add_on_pullback",
            risk_gate={
                "downgraded": True,
                "blocked": False,
                "risk_flags": ["trend_break_warning_downgrade"],
                "gate_reasons": ["技术面 warning"],
                "action_constraints": {"snapshot": {"public_fallback_count": 0}},
            },
            ai_policy_assessment={
                "status": "evaluated",
                "ai_position_stance": "underweight",
                "recommended_action_bias": "prefer_pullback_add",
            },
        ),
        _doc(
            "d2",
            action="hold_no_add",
            trade_plan_action="add_on_pullback",
            draft_action="add_on_pullback",
            final_action="hold_no_add",
            risk_gate={
                "downgraded": True,
                "blocked": False,
                "risk_flags": ["weak_catalyst_downgrade"],
                "gate_reasons": ["催化偏弱"],
                "action_constraints": {"snapshot": {"public_fallback_count": 2}},
            },
            ai_policy_assessment={
                "status": "evaluated",
                "ai_position_stance": "underweight",
                "recommended_action_bias": "allow_add",
            },
        ),
    ]

    summary = TradeDecisionQualityAnalyticsService().summarize(docs)
    calibration = summary["action_calibration"]

    assert calibration["add_like_rate"] == 0.5
    assert calibration["hold_like_rate"] == 0.5
    assert calibration["draft_to_final_downgrade_rate"] == 1.0
    assert calibration["ai_underweight_but_hold_count"] == 1
    assert calibration["ai_allow_add_but_hold_count"] == 1
    assert calibration["public_fallback_to_hold_rate"] == 1.0
    assert calibration["final_action_distribution"][0]["key"] in {"add_on_pullback", "hold_no_add"}


def test_summarize_empty_documents_returns_usable_summary() -> None:
    summary = TradeDecisionQualityAnalyticsService().summarize([])

    assert summary["total_count"] == 0
    assert summary["evaluated_count"] == 0
    assert summary["average_score"] is None
    assert "no_trade_decision_documents" in summary["data_limitations"]


def test_quality_summary_route_uses_repository_limit_and_days() -> None:
    class FakeRepository:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def list_recent_decisions_for_quality(self, *, limit: int = 200, days: int | None = None) -> list[dict]:
            self.calls.append({"limit": limit, "days": days})
            return [_doc("route-d1", score=88, level="good", passed=True)]

    repo = FakeRepository()
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    app.dependency_overrides[get_trade_decision_repository] = lambda: repo
    try:
        client = TestClient(app)
        response = client.get("/api/agent/trade-decision/quality/summary?limit=7&days=30")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["evaluated_count"] == 1
    assert repo.calls == [{"limit": 7, "days": 30}]
