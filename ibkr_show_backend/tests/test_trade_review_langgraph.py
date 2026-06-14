"""Tests for Trade Review Agent LangGraph migration (P3).

Covers:
1. Graph structure (nodes, edges, fan-out/fan-in)
2. State fields and reducers
3. All node factories with mocked deps
4. Runner _initial_state and fallback
5. Thin façade delegation
6. Defensive branches (None symbol, missing data, LLM errors)
"""

import pytest
from unittest.mock import MagicMock, patch

from app.agents.trade_review_graph.graph import (
    TradeReviewGraphDeps,
    build_trade_review_graph,
)
from app.agents.trade_review_graph.nodes import (
    make_account_node,
    make_behavior_pattern_node,
    make_benchmark_node,
    make_build_trade_review_context_node,
    make_compose_trade_review_node,
    make_event_node,
    make_load_trade_facts_node,
    make_market_node,
    make_opportunity_cost_node,
    make_persist_trade_review_node,
    make_position_node,
)
from app.agents.trade_review_graph.runner import TradeReviewGraphRunner
from app.agents.trade_review_graph.state import TradeReviewGraphState
from app.agents.versions import (
    TRADE_REVIEW_AGENT_MODE_LANGGRAPH,
    TRADE_REVIEW_GRAPH_VERSION,
)


# === Fixtures ===


def _mock_deps():
    deps = MagicMock(spec=TradeReviewGraphDeps)
    deps.evidence_builder = MagicMock()
    deps.llm_service = MagicMock()
    deps.repository = MagicMock()
    return deps


def _mock_provider():
    provider = MagicMock()
    provider.name = "test"
    provider.base_url = "https://test.com"
    provider.default_model = "test-model"
    return provider


def _base_state(**overrides) -> dict:
    state = {
        "review_type": "symbol_level_review",
        "symbol": "AMD.US",
        "trade_id": None,
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "started_at": "2025-01-01T00:00:00Z",
        "errors": [],
        "warnings": [],
        "data_limitations": [],
        "node_traces": [],
        "fallback_used": False,
        "fallback_reason": None,
        "metadata": {},
    }
    state.update(overrides)
    return state


# === Graph Structure Tests ===


class TestTradeReviewGraphStructure:
    """Test graph compilation and structure."""

    def test_graph_compiles(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        assert graph is not None

    def test_graph_uses_explicit_list_fan_in_edges(self, monkeypatch):
        from app.agents.trade_review_graph import graph as graph_module

        class SpyGraph:
            def __init__(self, _state_type):
                self.edges = []

            def add_node(self, *_args, **_kwargs):
                return None

            def add_edge(self, source, target):
                self.edges.append((source, target))

            def compile(self):
                return self

        spy = SpyGraph(None)
        monkeypatch.setattr(graph_module, "StateGraph", lambda _state_type: spy)

        compiled = graph_module.build_trade_review_graph(_mock_deps())

        assert compiled is spy
        assert (
            [
                "position_evidence",
                "account_evidence",
                "market_evidence",
                "benchmark_evidence",
                "event_evidence",
            ],
            "build_trade_review_context",
        ) in spy.edges
        assert (["behavior_pattern", "opportunity_cost"], "compose_trade_review") in spy.edges

    def test_graph_has_all_nodes(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        node_names = set(graph.get_graph().nodes)
        expected = {
            "__start__", "__end__",
            "load_trade_facts",
            "position_evidence", "account_evidence", "market_evidence",
            "benchmark_evidence", "event_evidence",
            "build_trade_review_context",
            "behavior_pattern", "opportunity_cost",
            "compose_trade_review", "persist_trade_review",
        }
        assert expected.issubset(node_names)

    def test_graph_fan_out_from_load_trade_facts(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        edges = graph.get_graph().edges
        source_nodes = {e[0] for e in edges if e[1] in {
            "position_evidence", "account_evidence", "market_evidence",
            "benchmark_evidence", "event_evidence",
        }}
        assert "load_trade_facts" in source_nodes

    def test_graph_fan_in_to_build_context(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        edges = graph.get_graph().edges
        sources = {e[0] for e in edges if e[1] == "build_trade_review_context"}
        expected = {"position_evidence", "account_evidence", "market_evidence", "benchmark_evidence", "event_evidence"}
        assert expected.issubset(sources)

    def test_graph_fan_out_from_build_context(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        edges = graph.get_graph().edges
        targets = {e[1] for e in edges if e[0] == "build_trade_review_context"}
        assert "behavior_pattern" in targets
        assert "opportunity_cost" in targets

    def test_graph_fan_in_to_compose(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        edges = graph.get_graph().edges
        sources = {e[0] for e in edges if e[1] == "compose_trade_review"}
        assert "behavior_pattern" in sources
        assert "opportunity_cost" in sources

    def test_graph_sequential_tail(self):
        deps = _mock_deps()
        graph = build_trade_review_graph(deps)
        edges = graph.get_graph().edges
        edge_pairs = {(e.source, e.target) for e in edges}
        assert ("compose_trade_review", "persist_trade_review") in edge_pairs
        assert ("persist_trade_review", "__end__") in edge_pairs


# === State Tests ===


class TestTradeReviewGraphState:
    """Test state field definitions."""

    def test_state_has_input_fields(self):
        assert "review_type" in TradeReviewGraphState.__annotations__
        assert "symbol" in TradeReviewGraphState.__annotations__
        assert "trade_id" in TradeReviewGraphState.__annotations__
        assert "start_date" in TradeReviewGraphState.__annotations__
        assert "end_date" in TradeReviewGraphState.__annotations__

    def test_state_has_evidence_fields(self):
        assert "position_evidence" in TradeReviewGraphState.__annotations__
        assert "account_evidence" in TradeReviewGraphState.__annotations__
        assert "market_evidence" in TradeReviewGraphState.__annotations__
        assert "benchmark_evidence" in TradeReviewGraphState.__annotations__
        assert "event_evidence" in TradeReviewGraphState.__annotations__

    def test_state_has_analysis_fields(self):
        assert "behavior_pattern_analysis" in TradeReviewGraphState.__annotations__
        assert "opportunity_cost_analysis" in TradeReviewGraphState.__annotations__

    def test_state_has_output_fields(self):
        assert "merged_review_context" in TradeReviewGraphState.__annotations__
        assert "trade_review_output" in TradeReviewGraphState.__annotations__
        assert "saved_document" in TradeReviewGraphState.__annotations__

    def test_state_inherits_base(self):
        assert "errors" in TradeReviewGraphState.__annotations__
        assert "warnings" in TradeReviewGraphState.__annotations__
        assert "node_traces" in TradeReviewGraphState.__annotations__
        assert "fallback_used" in TradeReviewGraphState.__annotations__


# === Node Tests ===


class TestLoadTradeFactsNode:
    def test_symbol_review_loads_trades(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_symbol_trades.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "trades": [{"trade_id": "t1", "side": "BUY"}],
        }
        node = make_load_trade_facts_node(deps)
        state = _base_state()
        result = node(state)
        assert "trade_facts" in result
        assert result["trade_facts"]["trades"][0]["trade_id"] == "t1"
        assert result["trade_facts"]["source"] == "IBKR_ONLY"
        deps.evidence_builder.tool_get_symbol_trades.assert_called_once()

    def test_single_trade_review_uses_ibkr_only(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_single_trade.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "trade": {
                "trade_id": "t1",
                "symbol": "AMD",
                "side": "BUY",
                "date": "2025-06-01",
                "amount": 1000,
            },
        }
        deps.evidence_builder.tool_get_symbol_trades.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "trades": [{"trade_id": "t1"}, {"trade_id": "t2"}],
        }
        node = make_load_trade_facts_node(deps)
        state = _base_state(review_type="single_trade_review", symbol=None, trade_id="t1")
        result = node(state)
        assert result["trade_facts"]["trades"][0]["trade_id"] == "t1"
        assert result["symbol"] == "AMD.US"
        assert result["trade_facts"]["source"] == "IBKR_ONLY"
        assert result["trade_facts"]["reviewed_trade_id"] == "t1"
        assert result["review_context"] == {}
        deps.evidence_builder.tool_get_single_trade.assert_called_once_with("t1")
        deps.evidence_builder.tool_get_symbol_trades.assert_called_once()

    def test_single_trade_does_not_call_longbridge_tools(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_single_trade.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "trade": {"trade_id": "t1", "side": "BUY", "date": "2025-06-01"},
        }
        deps.evidence_builder.tool_get_symbol_trades.return_value = {"trades": []}
        node = make_load_trade_facts_node(deps)
        state = _base_state(review_type="single_trade_review", trade_id="t1")
        node(state)
        deps.evidence_builder.tool_get_single_trade_review_context.assert_not_called()
        deps.evidence_builder.tool_get_price_context.assert_not_called()
        deps.evidence_builder.tool_get_benchmark_context.assert_not_called()
        deps.evidence_builder.tool_get_symbol_news.assert_not_called()

    def test_error_returns_empty_and_trace(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_symbol_trades.side_effect = RuntimeError("ES down")
        node = make_load_trade_facts_node(deps)
        result = node(_base_state())
        assert result["trade_facts"] == {}
        assert "load_trade_facts" in result["errors"][0]


class TestPositionNode:
    def test_fetches_position(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_current_position.return_value = {"position": {"quantity": 100}}
        node = make_position_node(deps)
        result = node(_base_state())
        assert result["position_evidence"]["position"]["quantity"] == 100

    def test_no_symbol_returns_empty(self):
        deps = _mock_deps()
        node = make_position_node(deps)
        result = node(_base_state(symbol=None))
        assert result["position_evidence"] == {}

    def test_error_returns_fallback(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_current_position.side_effect = RuntimeError("fail")
        node = make_position_node(deps)
        result = node(_base_state())
        assert "error" in result["position_evidence"]


class TestAccountNode:
    def test_fetches_account(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_account_context.return_value = {"account_value_at_start": 100000}
        node = make_account_node(deps)
        result = node(_base_state())
        assert result["account_evidence"]["account_value_at_start"] == 100000

    def test_error_returns_fallback(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_account_context.side_effect = RuntimeError("fail")
        node = make_account_node(deps)
        result = node(_base_state())
        assert "error" in result["account_evidence"]


class TestMarketNode:
    def test_fetches_price_context(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_price_context.return_value = {"price_context": {"symbol_candles": []}}
        node = make_market_node(deps)
        result = node(_base_state())
        assert "price_context" in result["market_evidence"]

    def test_no_symbol_returns_empty(self):
        deps = _mock_deps()
        node = make_market_node(deps)
        result = node(_base_state(symbol=None))
        assert result["market_evidence"] == {}


class TestBenchmarkNode:
    def test_fetches_benchmark(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_benchmark_context.return_value = {"benchmark_context": {"SPY.US": {"period_return": 0.1}}}
        node = make_benchmark_node(deps)
        result = node(_base_state())
        assert "SPY.US" in result["benchmark_evidence"]["benchmark_context"]

    def test_error_returns_fallback(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_benchmark_context.side_effect = RuntimeError("fail")
        node = make_benchmark_node(deps)
        result = node(_base_state())
        assert "error" in result["benchmark_evidence"]


class TestEventNode:
    def test_fetches_news(self):
        deps = _mock_deps()
        deps.evidence_builder.tool_get_symbol_news.return_value = {"news": [{"title": "test"}]}
        node = make_event_node(deps)
        result = node(_base_state())
        assert result["event_evidence"]["news"][0]["title"] == "test"

    def test_no_symbol_returns_empty(self):
        deps = _mock_deps()
        node = make_event_node(deps)
        result = node(_base_state(symbol=None))
        assert result["event_evidence"] == {}


class TestBuildTradeReviewContextNode:
    def test_merges_all_evidence(self):
        deps = _mock_deps()
        node = make_build_trade_review_context_node(deps)
        state = _base_state(
            trade_facts={"trades": [{"trade_id": "t1"}]},
            position_evidence={"position": {"quantity": 100}},
            account_evidence={"account_value_at_start": 100000},
            market_evidence={"price_context": {"symbol_candles": []}},
            benchmark_evidence={"benchmark_context": {"SPY.US": {"period_return": 0.1}}},
            event_evidence={"news": [{"title": "test"}]},
        )
        result = node(state)
        ctx = result["merged_review_context"]
        assert ctx["review_type"] == "symbol_level_review"
        assert ctx["trade_facts"]["trades"][0]["trade_id"] == "t1"
        assert ctx["trade_facts"]["current_position"]["quantity"] == 100
        assert ctx["account_context"]["account_value_at_start"] == 100000
        assert ctx["data_sources"]["trade_data"] == "IBKR_ONLY"
        assert ctx["data_sources"]["public_market_data"] == "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"

    def test_single_trade_uses_same_fan_in_logic(self):
        deps = _mock_deps()
        node = make_build_trade_review_context_node(deps)
        state = _base_state(
            review_type="single_trade_review",
            trade_id="t1",
            trade_facts={"trades": [{"trade_id": "t1"}], "source": "IBKR_ONLY"},
            position_evidence={"position": {"quantity": 50}},
            account_evidence={"account_value_at_start": 200000},
            market_evidence={"price_context": {}},
            benchmark_evidence={"benchmark_context": {}},
            event_evidence={},
        )
        result = node(state)
        ctx = result["merged_review_context"]
        assert ctx["review_type"] == "single_trade_review"
        assert ctx["trade_facts"]["source"] == "IBKR_ONLY"
        assert ctx["trade_facts"]["current_position"]["quantity"] == 50
        assert ctx["data_sources"]["trade_data"] == "IBKR_ONLY"


class TestBehaviorPatternNode:
    def test_analyzes_behavior(self):
        deps = _mock_deps()
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {
            "content": '{"behavior_patterns": ["pattern1"], "behavior_score": 75, "behavior_summary": "good"}',
            "trace": [],
        }
        node = make_behavior_pattern_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["behavior_pattern_analysis"]["behavior_score"] == 75

    def test_parse_error_returns_fallback(self):
        deps = _mock_deps()
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {"content": "not json", "trace": []}
        node = make_behavior_pattern_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["behavior_pattern_analysis"]["behavior_score"] == 0

    def test_runtime_error_returns_fallback(self):
        deps = _mock_deps()
        mock_runtime = MagicMock()
        mock_runtime.run.side_effect = RuntimeError("LLM down")
        node = make_behavior_pattern_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["behavior_pattern_analysis"]["behavior_score"] == 0


class TestOpportunityCostNode:
    def test_analyzes_opportunity_cost(self):
        deps = _mock_deps()
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {
            "content": '{"opportunity_cost_score": 60, "benchmark_comparison": {}, "opportunity_cost_summary": "moderate"}',
            "trace": [],
        }
        node = make_opportunity_cost_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["opportunity_cost_analysis"]["opportunity_cost_score"] == 60

    def test_error_returns_fallback(self):
        deps = _mock_deps()
        mock_runtime = MagicMock()
        mock_runtime.run.side_effect = RuntimeError("fail")
        node = make_opportunity_cost_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["opportunity_cost_analysis"]["opportunity_cost_score"] == 0


class TestComposeTradeReviewNode:
    def test_composes_valid_output(self):
        deps = _mock_deps()
        deps.llm_service.get_active_provider.return_value = _mock_provider()
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {
            "content": '{"symbol": "AMD.US", "overall_score": 75, "rating": "good", "score_detail": {"return_result_score": {"score": 15, "max_score": 20, "reason": "ok"}, "relative_performance_score": {"score": 10, "max_score": 15, "reason": "ok"}, "entry_quality_score": {"score": 10, "max_score": 15, "reason": "ok"}, "exit_quality_score": {"score": 10, "max_score": 15, "reason": "ok"}, "position_sizing_score": {"score": 10, "max_score": 15, "reason": "ok"}, "holding_period_score": {"score": 5, "max_score": 5, "reason": "ok"}, "risk_control_score": {"score": 10, "max_score": 10, "reason": "ok"}, "decision_attribution_score": {"score": 5, "max_score": 5, "reason": "ok"}}, "summary": "good trade", "strengths": ["entry"], "weaknesses": [], "mistake_tags": [], "improvement_suggestions": [], "data_limitations": [], "evidence_used": []}',
            "trace": [],
        }
        node = make_compose_trade_review_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(
                merged_review_context={"trade_facts": {}},
                behavior_pattern_analysis={"behavior_score": 75},
                opportunity_cost_analysis={"opportunity_cost_score": 60},
            ))
        assert "trade_review_output" in result
        assert result["trade_review_output"]["overall_score"] > 0

    def test_invalid_json_tries_repair(self):
        deps = _mock_deps()
        deps.llm_service.get_active_provider.return_value = _mock_provider()
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {"content": "not json", "trace": []}
        repaired = '{"symbol": "AMD.US", "overall_score": 50, "rating": "average", "score_detail": {"return_result_score": {"score": 10, "max_score": 20, "reason": ""}, "relative_performance_score": {"score": 8, "max_score": 15, "reason": ""}, "entry_quality_score": {"score": 8, "max_score": 15, "reason": ""}, "exit_quality_score": {"score": 8, "max_score": 15, "reason": ""}, "position_sizing_score": {"score": 8, "max_score": 15, "reason": ""}, "holding_period_score": {"score": 3, "max_score": 5, "reason": ""}, "risk_control_score": {"score": 5, "max_score": 10, "reason": ""}, "decision_attribution_score": {"score": 0, "max_score": 5, "reason": ""}}, "summary": "repaired", "strengths": [], "weaknesses": [], "mistake_tags": [], "improvement_suggestions": [], "data_limitations": [], "evidence_used": []}'
        deps.llm_service.chat.return_value = repaired
        deps.llm_service.chat_with_metadata.return_value = type("Result", (), {"content": repaired, "call_metadata": None})()
        node = make_compose_trade_review_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["trade_review_output"]["summary"] == "repaired"

    def test_total_failure_returns_fallback(self):
        deps = _mock_deps()
        deps.llm_service.get_active_provider.return_value = _mock_provider()
        mock_runtime = MagicMock()
        mock_runtime.run.side_effect = RuntimeError("LLM totally down")
        node = make_compose_trade_review_node(deps)
        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = node(_base_state(merged_review_context={"trade_facts": {}}))
        assert result["trade_review_output"]["overall_score"] == 0


class TestPersistTradeReviewNode:
    def test_saves_document(self):
        deps = _mock_deps()
        deps.llm_service.get_active_provider.return_value = _mock_provider()
        saved_doc = {}
        def capture(doc):
            saved_doc.update(doc)
            return doc
        deps.repository.save_review.side_effect = capture

        node = make_persist_trade_review_node(deps)
        state = _base_state(
            trade_review_output={
                "overall_score": 75,
                "rating": "good",
                "score_detail": {},
                "summary": "ok",
                "strengths": [],
                "weaknesses": [],
                "mistake_tags": [],
                "improvement_suggestions": [],
                "data_limitations": [],
                "evidence_used": [],
            },
            merged_review_context={"trade_facts": {}},
            structured_output={"trade_review_main": {"contract_name": "trade_review_main", "repaired": False}},
            raw_llm_response='{"original_response_preview": "{}"}',
        )
        result = node(state)
        assert "saved_document" in result
        assert saved_doc["metadata"]["agent_mode"] == TRADE_REVIEW_AGENT_MODE_LANGGRAPH
        assert saved_doc["metadata"]["graph_version"] == TRADE_REVIEW_GRAPH_VERSION
        assert saved_doc["metadata"]["structured_output"]["trade_review_main"]["contract_name"] == "trade_review_main"
        assert "original_response_preview" in saved_doc["raw_llm_response"]

    def test_persist_error_returns_error_trace(self):
        deps = _mock_deps()
        deps.llm_service.get_active_provider.return_value = _mock_provider()
        deps.repository.save_review.side_effect = RuntimeError("ES down")
        node = make_persist_trade_review_node(deps)
        state = _base_state(
            trade_review_output={"overall_score": 0, "rating": "poor", "score_detail": {}, "summary": "fail"},
            merged_review_context={},
        )
        result = node(state)
        assert "persist_trade_review" in result["errors"][0]


# === Runner Tests ===


class TestTradeReviewGraphRunner:
    def test_initial_state_symbol_review(self):
        deps = _mock_deps()
        runner = TradeReviewGraphRunner(
            evidence_builder=deps.evidence_builder,
            llm_service=deps.llm_service,
            repository=deps.repository,
        )
        state = runner._initial_state("symbol_level_review", symbol="AMD.US", start_date="2025-01-01")
        assert state["review_type"] == "symbol_level_review"
        assert state["symbol"] == "AMD.US"
        assert state["errors"] == []
        assert state["node_traces"] == []

    def test_initial_state_single_trade(self):
        deps = _mock_deps()
        runner = TradeReviewGraphRunner(
            evidence_builder=deps.evidence_builder,
            llm_service=deps.llm_service,
            repository=deps.repository,
        )
        state = runner._initial_state("single_trade_review", trade_id="t1")
        assert state["review_type"] == "single_trade_review"
        assert state["trade_id"] == "t1"

    def test_runner_fallback_saves_document(self):
        deps = _mock_deps()
        saved = {}
        def capture(doc):
            saved.update(doc)
            return doc
        deps.repository.save_review.side_effect = capture

        runner = TradeReviewGraphRunner(
            evidence_builder=deps.evidence_builder,
            llm_service=deps.llm_service,
            repository=deps.repository,
        )
        result = runner._build_fallback(
            {"review_type": "symbol_level_review", "symbol": "AMD.US"},
            "test failure",
        )
        assert result["fallback_used"] is True
        assert "test failure" in result["fallback_reason"]
        assert result["metadata"]["agent_mode"] == TRADE_REVIEW_AGENT_MODE_LANGGRAPH

    def test_runner_fallback_on_graph_error(self):
        deps = _mock_deps()
        saved = {}
        def capture(doc):
            saved.update(doc)
            return doc
        deps.repository.save_review.side_effect = capture

        runner = TradeReviewGraphRunner(
            evidence_builder=deps.evidence_builder,
            llm_service=deps.llm_service,
            repository=deps.repository,
        )
        # Force graph.invoke to raise
        runner.graph = MagicMock()
        runner.graph.invoke.side_effect = RuntimeError("graph exploded")
        result = runner.generate_symbol_review("AMD.US")
        assert result["fallback_used"] is True

    def test_finalize_does_not_fail_when_replay_snapshot_persist_fails(self):
        deps = _mock_deps()
        deps.repository.save_review.side_effect = lambda doc: doc
        trace_service = MagicMock()
        replay_service = MagicMock()
        replay_service.record_snapshot.side_effect = RuntimeError("mapping exploded")
        runner = TradeReviewGraphRunner(
            evidence_builder=deps.evidence_builder,
            llm_service=deps.llm_service,
            repository=deps.repository,
            trace_service=trace_service,
            replay_service=replay_service,
        )
        document = {
            "id": "AMD.US",
            "review_type": "symbol_level_review",
            "symbol": "AMD.US",
            "status": "success",
            "summary": "ok",
            "data_limitations": [],
            "metadata": {},
            "run_trace": [{"node_name": "persist_trade_review", "status": "success"}],
        }
        initial_state = {
            "review_type": "symbol_level_review",
            "symbol": "AMD.US",
            "started_at": "2026-05-20T00:00:00+00:00",
            "agent_run_id": "trade-review-run-1",
        }

        result = runner._finalize(document, initial_state, {"node_traces": document["run_trace"]})

        assert result["status"] == "success"
        assert result["agent_replay"]["persisted"] is False
        assert "mapping exploded" in result["agent_replay"]["error"]
        assert any("agent_replay_persist_failed" in item for item in result["data_limitations"])
        trace_service.record_trace.assert_called_once()
        replay_service.record_snapshot.assert_called_once()
        deps.repository.save_review.assert_called_once()


# === Thin Façade Tests ===


class TestTradeReviewAgentFacade:
    def test_generate_symbol_review_delegates_to_runner(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()
        agent = TradeReviewAgent(mock_builder, mock_llm, mock_repo)

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_symbol_review.return_value = {
                "id": "test",
                "metadata": {"agent_mode": TRADE_REVIEW_AGENT_MODE_LANGGRAPH},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_symbol_review("AMD.US", "2025-01-01", "2025-12-31")

        mock_runner.generate_symbol_review.assert_called_once_with(
            symbol="AMD.US", start_date="2025-01-01", end_date="2025-12-31",
        )
        assert result["metadata"]["agent_mode"] == TRADE_REVIEW_AGENT_MODE_LANGGRAPH

    def test_generate_single_trade_review_delegates_to_runner(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()
        agent = TradeReviewAgent(mock_builder, mock_llm, mock_repo)

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_single_trade_review.return_value = {
                "id": "test",
                "metadata": {"agent_mode": TRADE_REVIEW_AGENT_MODE_LANGGRAPH},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_single_trade_review("trade-123")

        mock_runner.generate_single_trade_review.assert_called_once_with(trade_id="trade-123")
        assert result["metadata"]["agent_mode"] == TRADE_REVIEW_AGENT_MODE_LANGGRAPH

    def test_constructor_accepts_investment_policy_service(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_policy_service = MagicMock()
        agent = TradeReviewAgent(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            investment_policy_service=mock_policy_service,
        )

        runner = agent._get_graph_runner()

        assert agent.investment_policy_service is mock_policy_service
        assert runner.deps.investment_policy_service is mock_policy_service


# === Version Constants Tests ===


class TestTradeReviewGraphVersions:
    def test_langgraph_mode_constant(self):
        assert TRADE_REVIEW_AGENT_MODE_LANGGRAPH == "trade_review_langgraph_v1"

    def test_graph_version_constant(self):
        assert TRADE_REVIEW_GRAPH_VERSION == "trade_review_graph_v1"

    def test_graph_schema_version_exists(self):
        from app.agents.versions import TRADE_REVIEW_GRAPH_SCHEMA_VERSION
        assert TRADE_REVIEW_GRAPH_SCHEMA_VERSION == "trade_review_graph_state_v1"


# === Deprecated Path Tests ===


class TestDeprecatedPaths:
    def test_run_tool_agent_is_deprecated(self):
        from app.services.trade_review_agent import TradeReviewAgent
        agent = TradeReviewAgent(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(RuntimeError, match="deprecated"):
            agent._run_tool_agent(review_type="symbol_level_review", symbol="AMD.US", trade_id=None, start_date=None, end_date=None)

    def test_run_and_save_is_deprecated(self):
        from app.services.trade_review_agent import TradeReviewAgent
        agent = TradeReviewAgent(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(RuntimeError, match="deprecated"):
            agent._run_and_save({"symbol": "AMD.US"})

    def test_call_llm_is_deprecated(self):
        from app.services.trade_review_agent import TradeReviewAgent
        agent = TradeReviewAgent(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(RuntimeError, match="deprecated"):
            agent._call_llm({"symbol": "AMD.US"})

    def test_review_tools_is_deprecated(self):
        from app.services.trade_review_agent import TradeReviewAgent
        agent = TradeReviewAgent(MagicMock(), MagicMock(), MagicMock())
        with pytest.raises(RuntimeError, match="deprecated"):
            agent._review_tools()


# === LLM Provider Check Tests ===


class TestLLMProviderCheck:
    def test_generate_symbol_review_requires_llm_provider(self):
        from app.services.trade_review_agent import TradeReviewAgent
        from app.services.llm_service import LLMConfigError
        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = None
        agent = TradeReviewAgent(MagicMock(), mock_llm, MagicMock())
        with pytest.raises(LLMConfigError):
            agent.generate_symbol_review("AMD.US", None, None)

    def test_generate_single_trade_review_requires_llm_provider(self):
        from app.services.trade_review_agent import TradeReviewAgent
        from app.services.llm_service import LLMConfigError
        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = None
        agent = TradeReviewAgent(MagicMock(), mock_llm, MagicMock())
        with pytest.raises(LLMConfigError):
            agent.generate_single_trade_review("trade-1")


# === MCP Adapter Tests ===


class TestMCPAdapter:
    def test_graph_deps_has_optional_mcp_adapter(self):
        mock_mcp = MagicMock()
        runner = TradeReviewGraphRunner(
            evidence_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=mock_mcp,
        )
        assert runner.deps.mcp_adapter is mock_mcp

    def test_graph_deps_mcp_adapter_defaults_none(self):
        runner = TradeReviewGraphRunner(
            evidence_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
        )
        assert runner.deps.mcp_adapter is None


# === Fan-in Execution Semantics Tests ===


class TestTradeReviewFanInExecutionSemantics:
    """Test real graph execution with mocked deps to verify fan-in semantics."""

    def test_build_context_waits_for_all_five_evidence_nodes_and_runs_once(self):
        """Verify the graph runs all nodes exactly once and produces a valid document."""
        from app.agents.trade_review_graph.runner import TradeReviewGraphRunner

        mock_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        # Mock IBKR evidence
        mock_builder.tool_get_symbol_trades.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "trades": [{"trade_id": "t1", "side": "BUY", "date": "2025-06-01", "price": 100, "quantity": 10, "amount": 1000}],
        }
        mock_builder.tool_get_current_position.return_value = {
            "source": "IBKR",
            "symbol": "AMD.US",
            "position": {"quantity": 10},
        }
        mock_builder.tool_get_account_context.return_value = {
            "source": "IBKR",
            "account_value_at_start": 100000,
        }
        # Mock Longbridge evidence
        mock_builder.tool_get_price_context.return_value = {
            "source": "Longbridge",
            "price_context": {"symbol_candles": [{"date": "2025-06-01", "close": 100}]},
        }
        mock_builder.tool_get_benchmark_context.return_value = {
            "source": "Longbridge",
            "benchmark_context": {"SPY.US": {"period_return": 0.05}},
        }
        mock_builder.tool_get_symbol_news.return_value = {
            "source": "Longbridge",
            "news": [{"title": "AMD earnings"}],
        }

        # Mock LLM provider
        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.base_url = "https://test.com"
        mock_provider.default_model = "test-model"
        mock_llm.get_active_provider.return_value = mock_provider

        # Mock ToolCallingRuntime for behavior_pattern, opportunity_cost, compose
        valid_review_json = (
            '{"symbol": "AMD.US", "overall_score": 75, "rating": "good", '
            '"score_detail": {"return_result_score": {"score": 15, "max_score": 20, "reason": "ok"}, '
            '"relative_performance_score": {"score": 10, "max_score": 15, "reason": "ok"}, '
            '"entry_quality_score": {"score": 10, "max_score": 15, "reason": "ok"}, '
            '"exit_quality_score": {"score": 10, "max_score": 15, "reason": "ok"}, '
            '"position_sizing_score": {"score": 10, "max_score": 15, "reason": "ok"}, '
            '"holding_period_score": {"score": 5, "max_score": 5, "reason": "ok"}, '
            '"risk_control_score": {"score": 10, "max_score": 10, "reason": "ok"}, '
            '"decision_attribution_score": {"score": 5, "max_score": 5, "reason": "ok"}}, '
            '"summary": "good trade", "strengths": ["entry"], "weaknesses": [], '
            '"mistake_tags": [], "improvement_suggestions": [], '
            '"data_limitations": [], "evidence_used": []}'
        )

        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {
            "content": valid_review_json,
            "trace": [],
        }

        # Capture saved document
        saved_doc = {}
        def capture(doc):
            saved_doc.update(doc)
            return doc
        mock_repo.save_review.side_effect = capture

        runner = TradeReviewGraphRunner(
            evidence_builder=mock_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=mock_runtime):
            result = runner.generate_symbol_review("AMD.US", "2025-01-01", "2025-12-31")

        # Verify evidence tools called exactly once each
        mock_builder.tool_get_current_position.assert_called_once_with("AMD.US")
        mock_builder.tool_get_account_context.assert_called_once()
        mock_builder.tool_get_price_context.assert_called_once()
        mock_builder.tool_get_benchmark_context.assert_called_once()
        mock_builder.tool_get_symbol_news.assert_called_once_with("AMD.US", 10)

        # Verify repository.save_review called exactly once
        mock_repo.save_review.assert_called_once()

        # Verify run_trace contains all expected nodes
        run_trace = result.get("run_trace", [])
        node_names_in_trace = {entry.get("node_name") for entry in run_trace if entry.get("node_name")}
        expected_nodes = {
            "load_trade_facts",
            "position_evidence", "account_evidence", "market_evidence",
            "benchmark_evidence", "event_evidence",
            "build_trade_review_context",
            "behavior_pattern", "opportunity_cost",
            "compose_trade_review", "persist_trade_review",
        }
        assert expected_nodes == node_names_in_trace, f"Missing nodes: {expected_nodes - node_names_in_trace}"

        # Verify each critical node appears exactly once in run_trace
        for critical_node in ("build_trade_review_context", "compose_trade_review", "persist_trade_review"):
            count = sum(1 for e in run_trace if e.get("node_name") == critical_node)
            assert count == 1, f"{critical_node} appeared {count} times, expected 1"

        # Verify data_sources in evidence_pack
        evidence_pack = result.get("evidence_pack", {})
        assert evidence_pack.get("data_sources", {}).get("trade_data") == "IBKR_ONLY"
        assert evidence_pack.get("data_sources", {}).get("public_market_data") == "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"

        # Verify metadata
        assert result["metadata"]["agent_mode"] == TRADE_REVIEW_AGENT_MODE_LANGGRAPH
        assert result["metadata"]["graph_version"] == TRADE_REVIEW_GRAPH_VERSION
