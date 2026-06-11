"""Tests for trade decision market-event context cards."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.agents.trade_decision_cards import build_fallback_market_event_context_card
from app.agents.trade_decision_graph.nodes import make_market_event_context_node, _count_public_data_fallbacks
from app.schemas.market_event import MarketEventListItem
from app.services.trade_decision_market_event_context import (
    MARKET_EVENT_TOOL_NAME,
    TradeDecisionMarketEventContextBuilder,
)
from tests.test_trade_decision_langgraph import _make_fallback_card


def _event(
    event_id: str,
    title: str,
    *,
    category: str,
    event_type: str,
    importance: str,
    symbols: list[str] | None = None,
    asset_classes: list[str] | None = None,
) -> MarketEventListItem:
    return MarketEventListItem(
        id=event_id,
        title=title,
        summary="summary",
        category=category,
        event_type=event_type,
        status="SCHEDULED",
        importance=importance,
        source_code="MANUAL",
        country="US",
        market="US",
        symbols=symbols or [],
        asset_classes=asset_classes or [],
        scheduled_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        scheduled_timezone="UTC",
    )


class FakeMarketEventQueryService:
    def __init__(self, items_by_symbol: dict[str, list[MarketEventListItem]] | None = None, exc: Exception | None = None) -> None:
        self.items_by_symbol = items_by_symbol or {}
        self.exc = exc
        self.calls: list[dict] = []

    def get_symbol_events(self, symbol: str, days: int = 30, include_macro: bool = True):
        self.calls.append({"symbol": symbol, "days": days, "include_macro": include_macro})
        if self.exc:
            raise self.exc
        return SimpleNamespace(items=list(self.items_by_symbol.get(symbol, [])), total=0, limit=50, offset=0)


def test_builder_generates_card_with_symbol_and_macro_events():
    symbol_event = _event(
        "evt-symbol",
        "AAPL Earnings",
        category="COMPANY",
        event_type="EARNINGS",
        importance="HIGH",
        symbols=["AAPL"],
    )
    macro_event = _event(
        "evt-macro",
        "FOMC Rate Decision",
        category="MACRO",
        event_type="FOMC_RATE_DECISION",
        importance="HIGH",
        asset_classes=["equity", "rates"],
    )
    service = FakeMarketEventQueryService({"AAPL.US": [macro_event], "AAPL": [symbol_event, macro_event]})

    card, metadata = TradeDecisionMarketEventContextBuilder(service).build("AAPL.US", "entry_decision")

    assert card.risk_level == "high"
    assert card.symbol_events
    assert card.macro_events
    assert card.upcoming_events
    assert card.evidence_quality == "high"
    assert MARKET_EVENT_TOOL_NAME in card.source_tools
    assert not any("market_event_query_failed" in item for item in card.data_limitations)
    assert metadata["event_count"] == 2
    assert metadata["query_count"] == 2


def test_builder_no_events_is_not_fallback():
    service = FakeMarketEventQueryService({"AAPL.US": [], "AAPL": []})

    card, metadata = TradeDecisionMarketEventContextBuilder(service).build("AAPL.US", "entry_decision")

    assert card.risk_level == "low"
    assert card.evidence_quality == "medium"
    assert not any("market_event_query_failed" in item for item in card.data_limitations)
    assert "未来 30 天未发现明确重点事件" in card.summary
    assert metadata["fallback_used"] is False
    assert metadata["event_count"] == 0


def test_builder_service_exception_returns_fallback_card():
    service = FakeMarketEventQueryService(exc=RuntimeError("ES unavailable"))

    card, metadata = TradeDecisionMarketEventContextBuilder(service).build("AAPL.US", "entry_decision")

    assert card.evidence_quality == "low"
    assert card.risk_level == "unknown"
    assert any("market_event_query_failed" in item for item in card.data_limitations)
    assert metadata["fallback_used"] is True
    assert "market_event_query_failed" in metadata["fallback_reason"]


def test_market_event_context_node_success_path():
    event = _event(
        "evt-macro",
        "CPI",
        category="MACRO",
        event_type="CPI",
        importance="CRITICAL",
        asset_classes=["equity"],
    )
    deps = SimpleNamespace(market_event_query_service=FakeMarketEventQueryService({"AAPL.US": [event], "AAPL": [event]}))

    result = make_market_event_context_node(deps)({"symbol": "AAPL.US", "decision_type": "entry_decision"})

    assert result["market_event_context_card"].risk_level == "critical"
    trace = result["node_traces"][0]
    assert trace["status"] == "success"
    assert MARKET_EVENT_TOOL_NAME in trace["tools_called"]
    assert trace["fallback_used"] is False


def test_market_event_context_node_without_service_fallback():
    deps = SimpleNamespace(market_event_query_service=None)

    result = make_market_event_context_node(deps)({"symbol": "AAPL.US", "decision_type": "entry_decision"})

    trace = result["node_traces"][0]
    assert trace["status"] == "fallback"
    assert trace["fallback_used"] is True
    assert trace["fallback_reason"] == "market_event_query_service_unavailable"
    assert result["market_event_context_card"].risk_level == "unknown"


def test_market_event_context_does_not_affect_public_data_fallback_count():
    state = {
        "market_trend_card": _make_fallback_card("market_trend"),
        "fundamental_valuation_card": _make_fallback_card("fundamental_valuation"),
        "event_catalyst_card": _make_fallback_card("event_catalyst"),
    }
    baseline = _count_public_data_fallbacks(state)
    state["market_event_context_card"] = build_fallback_market_event_context_card(
        "AAPL.US",
        "entry_decision",
        "market_event_query_service_unavailable",
    )

    assert _count_public_data_fallbacks(state) == baseline
