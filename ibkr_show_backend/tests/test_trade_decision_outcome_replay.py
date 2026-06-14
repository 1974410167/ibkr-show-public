from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_trade_decision_outcome_replay_service, require_authenticated_session
from app.main import app
from app.schemas.trade_decision import TradeDecisionOutcomeItem
from app.services.trade_decision_outcome_replay import (
    TradeDecisionOutcomePriceProvider,
    TradeDecisionOutcomeReplayService,
    action_group_for,
    label_outcome,
    summarize_outcomes,
)


class DummySettings:
    es_price_history_index = "price-history"


class FakeES:
    def __init__(self, bars_by_symbol: dict[str, list[dict]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.calls: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        filters = body["query"]["bool"]["filter"]
        symbol = next(item["term"]["symbol"] for item in filters if "term" in item)
        date_range = next(item["range"]["report_date"] for item in filters if "range" in item)
        bars = [
            bar
            for bar in self.bars_by_symbol.get(symbol, [])
            if str(bar["report_date"]) >= date_range["gte"] and str(bar["report_date"]) <= date_range["lte"]
        ]
        return {"hits": {"hits": [{"_source": bar} for bar in bars]}}


class FakeRepository:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        self.calls: list[dict] = []

    def list_recent_decisions_for_outcome(self, **kwargs) -> list[dict]:
        self.calls.append(kwargs)
        docs = self.docs
        if kwargs.get("symbol"):
            docs = [doc for doc in docs if doc.get("symbol") == kwargs["symbol"]]
        if kwargs.get("decision_type"):
            docs = [doc for doc in docs if doc.get("decision_type") == kwargs["decision_type"]]
        return docs[: kwargs.get("limit", 500)]

    def get_decision(self, decision_id: str) -> dict | None:
        return next((doc for doc in self.docs if doc.get("id") == decision_id), None)


def _bars(prices: list[float], *, start_day: int = 1) -> list[dict]:
    bars = []
    for index, close in enumerate(prices, start=start_day):
        bars.append({
            "symbol": "AMD.US",
            "report_date": f"2026-01-{index:02d}",
            "open_price": close,
            "high_price": close * 1.02,
            "low_price": close * 0.98,
            "close_price": close,
        })
    return bars


def _doc(
    decision_id: str,
    *,
    action: str,
    draft_action: str | None = None,
    symbol: str = "AMD.US",
    created_at: str = "2026-01-01T10:00:00+00:00",
    ai_stance: str = "underweight",
    ai_bias: str = "allow_add",
) -> dict:
    return {
        "id": decision_id,
        "symbol": symbol,
        "decision_type": "trade_decision",
        "created_at": created_at,
        "action": action,
        "final_action": action,
        "draft_action": draft_action or action,
        "risk_adjusted_action": action,
        "user_investment_policy_summary": {"user_preferred_target_position_pct": 0.2},
        "ai_policy_assessment": {
            "ai_position_stance": ai_stance,
            "recommended_action_bias": ai_bias,
            "ai_recommended_target_position_pct": 0.18,
            "ai_recommended_max_position_pct": 0.25,
        },
    }


def test_price_provider_uses_same_day_close_and_trading_day_horizon() -> None:
    provider = TradeDecisionOutcomePriceProvider(FakeES({"AMD.US": _bars([100, 101, 102, 103, 104, 105])}), DummySettings())

    result = provider.evaluate("AMD", __import__("datetime").date(2026, 1, 1), [1, 5])

    assert result.decision_price == 100
    assert result.prices_after[1] == 101
    assert result.prices_after[5] == 105
    assert result.returns[1] == 0.01
    assert result.returns[5] == 0.05
    assert result.price_data_status == "ok"


def test_price_provider_shifts_to_next_trading_day_when_decision_date_missing() -> None:
    provider = TradeDecisionOutcomePriceProvider(FakeES({"AMD.US": _bars([100, 104], start_day=2)}), DummySettings())

    result = provider.evaluate("AMD.US", __import__("datetime").date(2026, 1, 1), [1])

    assert result.decision_price == 100
    assert result.prices_after[1] == 104
    assert result.price_data_status == "shifted"
    assert any(item.startswith("decision_date_price_shifted") for item in result.data_limitations)


def test_price_provider_returns_pending_nulls_when_horizon_is_insufficient() -> None:
    provider = TradeDecisionOutcomePriceProvider(FakeES({"AMD.US": _bars([100, 101])}), DummySettings())

    result = provider.evaluate("AMD.US", __import__("datetime").date(2026, 1, 1), [1, 5])

    assert result.prices_after[1] == 101
    assert result.prices_after[5] is None
    assert result.returns[5] is None
    assert "insufficient_price_history:5d" in result.data_limitations


def test_price_provider_missing_symbol_does_not_raise() -> None:
    provider = TradeDecisionOutcomePriceProvider(FakeES({}), DummySettings())

    result = provider.evaluate("MISSING.US", __import__("datetime").date(2026, 1, 1), [1])

    assert result.price_data_status == "missing"
    assert result.decision_price is None


def test_outcome_label_rules() -> None:
    assert label_outcome("add_like", 0.02, 0.03, -0.02)[0] == "good_action"
    assert label_outcome("add_like", -0.01, -0.06, -0.03)[0] == "bad_add"
    assert label_outcome("add_like", -0.01, -0.01, -0.09)[0] == "bad_add"
    assert label_outcome("hold_like", 0.01, 0.09, -0.02)[0] == "missed_upside"
    assert label_outcome("hold_like", -0.01, -0.06, -0.08)[0] == "avoided_loss"
    assert label_outcome("reduce_like", -0.01, -0.06, -0.08)[0] == "avoided_loss"
    assert label_outcome("reduce_like", 0.01, 0.09, -0.02)[0] == "sold_too_early"
    assert label_outcome("hold_like", None, None, None)[0] == "pending"


def test_service_evaluates_document_and_extracts_policy_fields() -> None:
    service = TradeDecisionOutcomeReplayService(
        FakeRepository([_doc("d1", action="add_small")]),
        TradeDecisionOutcomePriceProvider(FakeES({"AMD.US": _bars([100, 101, 102, 103, 104, 110] + [111] * 16)}), DummySettings()),
    )

    result = service.get_outcome("d1")

    assert result is not None
    assert result.action_group == "add_like"
    assert result.outcome_label == "good_action"
    assert result.ai_position_stance == "underweight"
    assert result.ai_recommended_action_bias == "allow_add"
    assert result.user_preferred_target_position_pct == 0.2


def test_summary_distributions_and_pr4_metrics() -> None:
    items = [
        TradeDecisionOutcomeItem(
            decision_id="good",
            symbol="AMD.US",
            decision_type="trade_decision",
            created_at="2026-01-01T00:00:00+00:00",
            draft_action="add_small",
            final_action="add_small",
            action_group="add_like",
            ai_position_stance="underweight",
            ai_recommended_action_bias="allow_add",
            return_1d=0.01,
            return_5d=0.03,
            return_20d=0.1,
            outcome_label="good_action",
            outcome_reason="",
        ),
        TradeDecisionOutcomeItem(
            decision_id="missed",
            symbol="AMD.US",
            decision_type="trade_decision",
            created_at="2026-01-02T00:00:00+00:00",
            draft_action="add_on_pullback",
            final_action="hold_no_add",
            action_group="hold_like",
            ai_position_stance="underweight",
            ai_recommended_action_bias="prefer_pullback_add",
            return_1d=0.01,
            return_5d=0.04,
            return_20d=0.12,
            outcome_label="missed_upside",
            outcome_reason="",
        ),
        TradeDecisionOutcomeItem(
            decision_id="saved",
            symbol="MSFT.US",
            decision_type="trade_decision",
            created_at="2026-01-03T00:00:00+00:00",
            draft_action="add_small",
            final_action="hold_no_add",
            action_group="hold_like",
            ai_position_stance="near_target",
            ai_recommended_action_bias="hold_no_add",
            return_1d=-0.01,
            return_5d=-0.02,
            return_20d=-0.03,
            outcome_label="neutral_hold",
            outcome_reason="",
        ),
    ]

    summary = summarize_outcomes(items)

    assert summary.total_count == 3
    assert summary.add_like_count == 1
    assert summary.hold_like_count == 2
    assert summary.add_like_avg_return_20d == 0.1
    assert summary.add_like_win_rate_5d == 1.0
    assert summary.missed_upside_count == 1
    assert summary.missed_ai_add_opportunity_count == 1
    assert summary.calibrated_action_success_count == 2
    assert summary.risk_gate_avoided_loss_count == 1
    assert summary.risk_gate_missed_upside_count == 1
    assert {"key": "hold_like", "count": 2} in summary.action_group_distribution


def test_action_group_for_pr4_actions() -> None:
    assert action_group_for("add_right_side") == "add_like"
    assert action_group_for("trim_on_rebound") == "reduce_like"
    assert action_group_for("panic_blocked") == "hold_like"


def test_outcome_list_api_filters_symbol_action_group_and_label() -> None:
    docs = [
        _doc("amd", action="hold_no_add", draft_action="add_small"),
        _doc("msft", action="add_small", symbol="MSFT.US"),
    ]
    service = TradeDecisionOutcomeReplayService(
        FakeRepository(docs),
        TradeDecisionOutcomePriceProvider(FakeES({
            "AMD.US": _bars([100, 101, 102, 103, 104, 112] + [112] * 16),
            "MSFT.US": [],
        }), DummySettings()),
    )
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    app.dependency_overrides[get_trade_decision_outcome_replay_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/api/agent/trade-decision/outcome/list?symbol=AMD&action_group=hold_like&outcome_label=missed_upside")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert [item["decision_id"] for item in payload["items"]] == ["amd"]
    assert payload["summary"]["missed_upside_count"] == 1
    assert service.repository.calls[0]["symbol"] == "AMD.US"


def test_outcome_summary_api_handles_missing_price() -> None:
    service = TradeDecisionOutcomeReplayService(
        FakeRepository([_doc("missing", action="add_small")]),
        TradeDecisionOutcomePriceProvider(FakeES({}), DummySettings()),
    )
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    app.dependency_overrides[get_trade_decision_outcome_replay_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/api/agent/trade-decision/outcome/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["missing_price_count"] == 1
