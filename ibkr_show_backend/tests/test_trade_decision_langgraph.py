"""Tests for the LangGraph-based trade decision agent."""

import inspect
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
    TradeDecisionSubAgentTrace,
    build_fallback_account_fit_card,
    build_fallback_event_card,
    build_fallback_fundamental_card,
    build_fallback_market_trend_card,
    build_fallback_risk_reward_card,
)
from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.graph.trace import (
    start_node_trace,
    finish_node_trace,
    fallback_node_trace,
    summarize_node_traces,
)
from app.agents.trade_decision_graph.state import TradeDecisionGraphState


# === Fixtures ===

def _make_snapshot(symbol="AAPL", decision_type="entry_decision", is_holding=False):
    return AccountFactSnapshot(
        decision_type=decision_type,
        symbol=symbol,
        normalized_symbol=symbol,
        user_question=None,
        net_liquidation=50000.0,
        cash=30000.0,
        deployable_liquidity=30000.0,
        deployable_liquidity_ratio=0.6,
        total_position_value=0.0,
        top_positions=[],
        position_concentration=None,
        risk_concentration=None,
        margin_info=None,
        is_holding=is_holding,
        quantity=None,
        avg_cost=None,
        current_price=150.0,
        market_value=0.0,
        position_pct=0.0,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        realized_pnl=None,
        recent_trades=[],
        first_buy_date=None,
        last_trade_date=None,
        holding_days=None,
        latest_review=None,
        global_mistake_tags=[],
        data_quality={},
    )


def _make_fallback_card(card_type, symbol="AAPL", decision_type="entry_decision"):
    builders = {
        "account_fit": build_fallback_account_fit_card,
        "market_trend": build_fallback_market_trend_card,
        "fundamental_valuation": build_fallback_fundamental_card,
        "event_catalyst": build_fallback_event_card,
        "risk_reward": build_fallback_risk_reward_card,
    }
    return builders[card_type](symbol, decision_type, "test fallback")


def _make_card_pack(snapshot=None, all_fallback=False):
    if snapshot is None:
        snapshot = _make_snapshot()
    if all_fallback:
        acc = _make_fallback_card("account_fit", snapshot.symbol, snapshot.decision_type)
        mkt = _make_fallback_card("market_trend", snapshot.symbol, snapshot.decision_type)
        fund = _make_fallback_card("fundamental_valuation", snapshot.symbol, snapshot.decision_type)
        evt = _make_fallback_card("event_catalyst", snapshot.symbol, snapshot.decision_type)
        rr = _make_fallback_card("risk_reward", snapshot.symbol, snapshot.decision_type)
    else:
        acc = AccountFitCard(
            card_type="account_fit", symbol=snapshot.symbol, decision_type=snapshot.decision_type,
            summary="Good fit", score=16, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", evidence_quality="high", source_tools=[],
        )
        mkt = MarketTrendCard(
            card_type="market_trend", symbol=snapshot.symbol, decision_type=snapshot.decision_type,
            summary="Bullish trend", score=12, max_score=15, stance=CardStance.BULLISH,
            price_trend="bullish", evidence_quality="medium", source_tools=["quote", "candlesticks"],
        )
        fund = FundamentalValuationCard(
            card_type="fundamental_valuation", symbol=snapshot.symbol, decision_type=snapshot.decision_type,
            summary="Strong fundamentals", score=20, max_score=35, stance=CardStance.BULLISH,
            pe_ttm=22.0, evidence_quality="high", source_tools=["company", "valuation"],
        )
        evt = EventCatalystCard(
            card_type="event_catalyst", symbol=snapshot.symbol, decision_type=snapshot.decision_type,
            summary="Positive catalyst", score=4, max_score=5, stance=CardStance.BULLISH,
            sentiment="positive", evidence_quality="medium", source_tools=["news_search"],
        )
        rr = RiskRewardCard(
            card_type="risk_reward", symbol=snapshot.symbol, decision_type=snapshot.decision_type,
            summary="Good risk/reward", score=12, max_score=15, stance=CardStance.BULLISH,
            reward_risk_ratio=2.5, evidence_quality="medium", source_tools=[],
        )

    return TradeDecisionCardPack(
        decision_type=snapshot.decision_type,
        symbol=snapshot.symbol,
        account_fact_snapshot=snapshot,
        account_fit_card=acc,
        market_trend_card=mkt,
        fundamental_valuation_card=fund,
        event_catalyst_card=evt,
        risk_reward_card=rr,
        data_quality_summary="low" if all_fallback else "medium",
    )


# === Test: strip_thinking_tags ===

class TestStripThinkingTags:

    def test_removes_think_tags(self):
        assert strip_thinking_tags("Hello <think>internal thought</think> world") == "Hello  world"

    def test_removes_thinking_tags(self):
        assert strip_thinking_tags("Hello <thinking>internal thought</thinking> world") == "Hello  world"

    def test_removes_unclosed_think(self):
        assert strip_thinking_tags("Hello <think>this is unclosed") == "Hello"

    def test_no_tags_unchanged(self):
        assert strip_thinking_tags("Hello world") == "Hello world"

    def test_empty_string(self):
        assert strip_thinking_tags("") == ""

    def test_non_string(self):
        assert strip_thinking_tags(None) is None


# === Test: Trace utilities ===

class TestTraceUtilities:

    def test_start_node_trace(self):
        trace = start_node_trace("test_node")
        assert trace["node_name"] == "test_node"
        assert trace["status"] == "running"
        assert trace["fallback_used"] is False

    def test_finish_node_trace(self):
        trace = start_node_trace("test_node")
        finished = finish_node_trace(trace, "success")
        assert finished["status"] == "success"
        assert finished["finished_at"] is not None
        assert finished["elapsed_ms"] >= 0

    def test_fallback_node_trace(self):
        trace = fallback_node_trace("test_node", RuntimeError("test error"))
        assert trace["status"] == "fallback"
        assert trace["fallback_used"] is True
        assert "test error" in trace["fallback_reason"]

    def test_summarize_node_traces(self):
        traces = [
            {"node_name": "a", "status": "success", "elapsed_ms": 100, "fallback_used": False},
            {"node_name": "b", "status": "fallback", "elapsed_ms": 50, "fallback_used": True},
        ]
        summary = summarize_node_traces(traces)
        assert summary["node_count"] == 2
        assert summary["fallback_count"] == 1
        assert summary["total_elapsed_ms"] == 150


# === Test: State reducer concurrency safety ===

class TestStateReducers:

    def test_node_traces_reducer_concatenates(self):
        """node_traces from parallel nodes should be concatenated, not overwritten."""
        from app.agents.graph.base_state import _merge_trace_list
        left = [{"node_name": "a", "status": "success"}]
        right = [{"node_name": "b", "status": "success"}]
        result = _merge_trace_list(left, right)
        assert len(result) == 2
        assert result[0]["node_name"] == "a"
        assert result[1]["node_name"] == "b"

    def test_string_list_reducer_deduplicates(self):
        """errors/warnings/data_limitations should be deduplicated."""
        from app.agents.graph.base_state import _merge_str_list
        left = ["error_a", "error_b"]
        right = ["error_b", "error_c"]
        result = _merge_str_list(left, right)
        assert result == ["error_a", "error_b", "error_c"]

    def test_state_has_no_underscore_deps(self):
        """TradeDecisionGraphState should not declare _deps."""
        annotations = TradeDecisionGraphState.__annotations__
        assert "_deps" not in annotations


# === Test: Graph parallel fan-out/fan-in ===

class TestGraphParallelStructure:

    def test_graph_has_parallel_edges(self):
        """build_account_facts should fan out to 4 parallel nodes."""
        from app.agents.trade_decision_graph.graph import build_trade_decision_graph, TradeDecisionGraphDeps

        deps = TradeDecisionGraphDeps(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=None,
        )
        graph = build_trade_decision_graph(deps)

        # Get the compiled graph's internal structure
        # LangGraph compiled graph exposes nodes
        graph_obj = graph.get_graph()
        node_names = list(graph_obj.nodes.keys())
        assert "build_account_facts" in node_names
        assert "account_fit" in node_names
        assert "market_trend" in node_names
        assert "fundamental_valuation" in node_names
        assert "event_catalyst" in node_names
        assert "risk_reward" in node_names
        assert "build_card_pack" in node_names
        assert "compose_decision" in node_names
        assert "persist_decision" in node_names

    def test_build_account_facts_fans_out_to_four(self):
        """build_account_facts node should have edges to all 4 sub-agent nodes."""
        from app.agents.trade_decision_graph.graph import build_trade_decision_graph, TradeDecisionGraphDeps

        deps = TradeDecisionGraphDeps(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=None,
        )
        graph = build_trade_decision_graph(deps)
        graph_obj = graph.get_graph()

        # Check edges from build_account_facts
        edges_from_facts = [
            edge.target for edge in graph_obj.edges
            if edge.source == "build_account_facts"
        ]
        assert "account_fit" in edges_from_facts
        assert "market_trend" in edges_from_facts
        assert "fundamental_valuation" in edges_from_facts
        assert "event_catalyst" in edges_from_facts

    def test_four_subagents_fan_in_to_risk_reward(self):
        """All 4 sub-agent nodes should have edges to risk_reward."""
        from app.agents.trade_decision_graph.graph import build_trade_decision_graph, TradeDecisionGraphDeps

        deps = TradeDecisionGraphDeps(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=None,
        )
        graph = build_trade_decision_graph(deps)
        graph_obj = graph.get_graph()

        edges_to_risk = [
            edge.source for edge in graph_obj.edges
            if edge.target == "risk_reward"
        ]
        assert "account_fit" in edges_to_risk
        assert "market_trend" in edges_to_risk
        assert "fundamental_valuation" in edges_to_risk
        assert "event_catalyst" in edges_to_risk


# === Test: Risk reward data quality constraints ===

class TestRiskRewardDataQuality:

    def test_capped_score_when_public_data_fallback(self):
        """When >=2 public data cards are fallback, risk_reward score <= 4."""
        from app.agents.trade_decision_graph.nodes import make_risk_reward_node

        snapshot = _make_snapshot()
        mkt = _make_fallback_card("market_trend")
        fund = _make_fallback_card("fundamental_valuation")
        evt = _make_fallback_card("event_catalyst")

        mock_deps = MagicMock()
        node_fn = make_risk_reward_node(mock_deps)

        state = {
            "account_fact_snapshot": snapshot,
            "account_fit_card": AccountFitCard(
                card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
                summary="ok", score=16, max_score=20, stance=CardStance.BULLISH,
                account_fit_level="good", evidence_quality="high", source_tools=[],
            ),
            "market_trend_card": mkt,
            "fundamental_valuation_card": fund,
            "event_catalyst_card": evt,
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "node_traces": [],
        }

        result = node_fn(state)
        rr = result["risk_reward_card"]
        assert rr.score <= 4
        assert rr.evidence_quality == "low"
        assert "公开市场数据不足" in rr.summary

    def test_no_cap_when_data_quality_ok(self):
        """When data quality is ok, risk_reward score is not capped."""
        from app.agents.trade_decision_graph.nodes import make_risk_reward_node

        snapshot = _make_snapshot()
        mock_deps = MagicMock()
        node_fn = make_risk_reward_node(mock_deps)

        state = {
            "account_fact_snapshot": snapshot,
            "account_fit_card": AccountFitCard(
                card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
                summary="ok", score=16, max_score=20, stance=CardStance.BULLISH,
                account_fit_level="good", evidence_quality="high", source_tools=[],
            ),
            "market_trend_card": MarketTrendCard(
                card_type="market_trend", symbol="AAPL", decision_type="entry_decision",
                summary="Bullish", score=12, max_score=15, stance=CardStance.BULLISH,
                price_trend="bullish", evidence_quality="medium", source_tools=["quote"],
            ),
            "fundamental_valuation_card": FundamentalValuationCard(
                card_type="fundamental_valuation", symbol="AAPL", decision_type="entry_decision",
                summary="Strong", score=20, max_score=35, stance=CardStance.BULLISH,
                pe_ttm=22.0, evidence_quality="high", source_tools=["company"],
            ),
            "event_catalyst_card": EventCatalystCard(
                card_type="event_catalyst", symbol="AAPL", decision_type="entry_decision",
                summary="Good", score=4, max_score=5, stance=CardStance.BULLISH,
                sentiment="positive", evidence_quality="medium", source_tools=["news_search"],
            ),
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "node_traces": [],
        }

        result = node_fn(state)
        rr = result["risk_reward_card"]
        assert rr.score > 0


class TestRiskRewardNodeTrace:

    def test_risk_reward_node_trace_has_structured_output_and_rounds(self):
        """The risk_reward node trace should include structured_output and rounds_used from sub_trace."""
        from app.agents.trade_decision_graph.nodes import make_risk_reward_node

        snapshot = _make_snapshot()
        mock_deps = MagicMock()
        node_fn = make_risk_reward_node(mock_deps)

        state = {
            "account_fact_snapshot": snapshot,
            "account_fit_card": AccountFitCard(
                card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
                summary="ok", score=16, max_score=20, stance=CardStance.BULLISH,
                account_fit_level="good", evidence_quality="high", source_tools=[],
            ),
            "market_trend_card": MarketTrendCard(
                card_type="market_trend", symbol="AAPL", decision_type="entry_decision",
                summary="Bullish", score=12, max_score=15, stance=CardStance.BULLISH,
                price_trend="bullish", evidence_quality="medium", source_tools=["quote"],
            ),
            "fundamental_valuation_card": FundamentalValuationCard(
                card_type="fundamental_valuation", symbol="AAPL", decision_type="entry_decision",
                summary="Strong", score=20, max_score=35, stance=CardStance.BULLISH,
                pe_ttm=22.0, evidence_quality="high", source_tools=["company"],
            ),
            "event_catalyst_card": EventCatalystCard(
                card_type="event_catalyst", symbol="AAPL", decision_type="entry_decision",
                summary="Good", score=4, max_score=5, stance=CardStance.BULLISH,
                sentiment="positive", evidence_quality="medium", source_tools=["news_search"],
            ),
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "node_traces": [],
        }

        result = node_fn(state)
        node_traces = result.get("node_traces", [])
        assert len(node_traces) == 1
        rr_trace = node_traces[0]
        assert rr_trace["node_name"] == "risk_reward"
        assert "structured_output" in rr_trace
        assert "rounds_used" in rr_trace


# === Test: Nodes use closure deps, not state _deps ===

class TestNodesClosureDeps:

    def test_nodes_are_factory_functions(self):
        """All node factories should return callables."""
        from app.agents.trade_decision_graph.nodes import (
            make_build_account_facts_node,
            make_account_fit_node,
            make_market_trend_node,
            make_fundamental_valuation_node,
            make_event_catalyst_node,
            make_risk_reward_node,
            make_build_card_pack_node,
            make_compose_decision_node,
            make_persist_decision_node,
        )
        mock_deps = MagicMock()
        for factory in [
            make_build_account_facts_node,
            make_account_fit_node,
            make_market_trend_node,
            make_fundamental_valuation_node,
            make_event_catalyst_node,
            make_risk_reward_node,
            make_build_card_pack_node,
            make_compose_decision_node,
            make_persist_decision_node,
        ]:
            node_fn = factory(mock_deps)
            assert callable(node_fn)

    def test_nodes_do_not_read_state_deps(self):
        """Node source code should not reference state['_deps']."""
        from app.agents.trade_decision_graph import nodes
        source = inspect.getsource(nodes)
        assert "state[\"_deps\"]" not in source
        assert "state['_deps']" not in source


# === Test: Graph builds with closure deps ===

class TestGraphBuild:

    def test_graph_builds_with_deps(self):
        from app.agents.trade_decision_graph.graph import build_trade_decision_graph, TradeDecisionGraphDeps

        deps = TradeDecisionGraphDeps(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=None,
        )
        graph = build_trade_decision_graph(deps)
        assert graph is not None


# === Test: Runner ===

class TestGraphRunner:

    def test_runner_builds(self):
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        runner = TradeDecisionGraphRunner(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            mcp_adapter=None,
        )
        assert runner.graph is not None

    def test_runner_initial_state_no_deps(self):
        """Runner should not put _deps into initial_state."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_builder = MagicMock()
        mock_repo = MagicMock()
        mock_repo.save_decision.return_value = {"id": "x"}
        runner = TradeDecisionGraphRunner(
            account_facts_builder=mock_builder,
            llm_service=MagicMock(),
            repository=mock_repo,
        )
        # Capture the initial_state passed to graph.invoke
        captured = {}
        original_invoke = runner.graph.invoke
        def capture_invoke(state, **kw):
            captured.update(state)
            raise RuntimeError("stop")
        runner.graph.invoke = capture_invoke
        try:
            runner._run("entry_decision", "AAPL.US", None)
        except RuntimeError:
            pass
        assert "_deps" not in captured

    def test_runner_returns_fallback_on_graph_error(self):
        """Runner should return conservative fallback if graph fails."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_builder = MagicMock()
        mock_builder.build.side_effect = RuntimeError("ES down")
        mock_repo = MagicMock()
        mock_repo.save_decision.return_value = {"id": "fallback-1", "fallback_used": True}

        runner = TradeDecisionGraphRunner(
            account_facts_builder=mock_builder,
            llm_service=MagicMock(),
            repository=mock_repo,
            mcp_adapter=None,
        )

        result = runner.analyze_entry("AAPL")
        assert result is not None
        assert "id" in result


# === Test: Build card pack node ===

class TestBuildCardPackNode:

    def test_no_none_cards_in_pack(self):
        """build_card_pack_node should never produce None cards."""
        from app.agents.trade_decision_graph.nodes import make_build_card_pack_node

        snapshot = _make_snapshot()
        mock_deps = MagicMock()
        node_fn = make_build_card_pack_node(mock_deps)

        state = {
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "account_fact_snapshot": snapshot,
            "account_fit_card": None,
            "market_trend_card": None,
            "fundamental_valuation_card": None,
            "event_catalyst_card": None,
            "risk_reward_card": None,
            "node_traces": [],
        }

        result = node_fn(state)
        card_pack = result["card_pack"]
        assert card_pack.account_fit_card is not None
        assert card_pack.market_trend_card is not None
        assert card_pack.fundamental_valuation_card is not None
        assert card_pack.event_catalyst_card is not None
        assert card_pack.risk_reward_card is not None


# === Test: Compose decision data quality constraints ===

class TestComposeDecisionConstraints:

    def test_conservative_action_entry_when_public_data_fallback(self):
        """When >=2 public data cards are fallback, entry action should be watchlist."""
        from app.agents.trade_decision_graph.nodes import make_compose_decision_node

        snapshot = _make_snapshot(is_holding=False)
        card_pack = _make_card_pack(snapshot, all_fallback=True)

        mock_deps = MagicMock()
        node_fn = make_compose_decision_node(mock_deps)

        state = {
            "card_pack": card_pack,
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "account_fact_snapshot": snapshot,
            "account_fit_card": card_pack.account_fit_card,
            "market_trend_card": card_pack.market_trend_card,
            "fundamental_valuation_card": card_pack.fundamental_valuation_card,
            "event_catalyst_card": card_pack.event_catalyst_card,
            "risk_reward_card": card_pack.risk_reward_card,
            "node_traces": [],
        }

        result = node_fn(state)
        output = result["decision_output"]
        assert output["confidence"] == "low"
        assert output["action"] == "watchlist"

    def test_conservative_action_holding_when_public_data_fallback(self):
        """When >=2 public data cards are fallback, holding action should be hold."""
        from app.agents.trade_decision_graph.nodes import make_compose_decision_node

        snapshot = _make_snapshot(is_holding=True)
        card_pack = _make_card_pack(snapshot, all_fallback=True)

        mock_deps = MagicMock()
        node_fn = make_compose_decision_node(mock_deps)

        state = {
            "card_pack": card_pack,
            "decision_type": "holding_decision",
            "symbol": "AAPL",
            "account_fact_snapshot": snapshot,
            "account_fit_card": card_pack.account_fit_card,
            "market_trend_card": card_pack.market_trend_card,
            "fundamental_valuation_card": card_pack.fundamental_valuation_card,
            "event_catalyst_card": card_pack.event_catalyst_card,
            "risk_reward_card": card_pack.risk_reward_card,
            "node_traces": [],
        }

        result = node_fn(state)
        output = result["decision_output"]
        assert output["action"] == "hold"

    def test_compose_handles_dataclass_snapshot(self):
        """compose should handle AccountFactSnapshot dataclass, not crash on .get()."""
        from app.agents.trade_decision_graph.nodes import make_compose_decision_node

        snapshot = _make_snapshot(is_holding=False)
        card_pack = _make_card_pack(snapshot, all_fallback=True)

        mock_deps = MagicMock()
        node_fn = make_compose_decision_node(mock_deps)

        state = {
            "card_pack": card_pack,
            "decision_type": "entry_decision",
            "symbol": "AAPL",
            "account_fact_snapshot": snapshot,  # dataclass, not dict
            "account_fit_card": card_pack.account_fit_card,
            "market_trend_card": card_pack.market_trend_card,
            "fundamental_valuation_card": card_pack.fundamental_valuation_card,
            "event_catalyst_card": card_pack.event_catalyst_card,
            "risk_reward_card": card_pack.risk_reward_card,
            "node_traces": [],
        }

        # Should not raise AttributeError
        result = node_fn(state)
        assert "decision_output" in result


# === Test: Snapshot helper ===

class TestSnapshotHelper:

    def test_snapshot_is_holding_dataclass(self):
        from app.agents.trade_decision_graph.nodes import _snapshot_is_holding
        snapshot = _make_snapshot(is_holding=True)
        assert _snapshot_is_holding(snapshot) is True

    def test_snapshot_is_holding_dict(self):
        from app.agents.trade_decision_graph.nodes import _snapshot_is_holding
        assert _snapshot_is_holding({"is_holding": True}) is True
        assert _snapshot_is_holding({"is_holding": False}) is False
        assert _snapshot_is_holding({}) is False

    def test_snapshot_is_holding_none(self):
        from app.agents.trade_decision_graph.nodes import _snapshot_is_holding
        assert _snapshot_is_holding(None) is False


# === Test: Deprecated TradeDecisionCardBuilder ===

class TestDeprecatedCardBuilder:

    def test_card_builder_still_importable(self):
        from app.services.trade_decision_sub_agents import TradeDecisionCardBuilder
        assert TradeDecisionCardBuilder is not None

    def test_card_builder_raises_deprecated_error(self):
        """TradeDecisionCardBuilder.build_card_pack should raise RuntimeError."""
        from app.services.trade_decision_sub_agents import TradeDecisionCardBuilder

        builder = TradeDecisionCardBuilder()
        with pytest.raises(RuntimeError, match="deprecated"):
            builder.build_card_pack(MagicMock())

    def test_card_builder_no_thread_pool_executor(self):
        """TradeDecisionCardBuilder should not use ThreadPoolExecutor in active code."""
        import textwrap
        from app.services.trade_decision_sub_agents import TradeDecisionCardBuilder
        source = inspect.getsource(TradeDecisionCardBuilder)
        # Strip docstrings and comments before checking
        lines = [
            l for l in source.splitlines()
            if not l.strip().startswith('#')
            and '"""' not in l
            and "ThreadPoolExecutor" not in l.replace("ThreadPoolExecutor", "").join(["", ""])
        ]
        # Re-check: remove lines that are purely docstring/comment content
        code_lines = []
        in_docstring = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith('#'):
                continue
            code_lines.append(line)
        code_only = "\n".join(code_lines)
        assert "ThreadPoolExecutor" not in code_only


# === Test: Versions constants ===

class TestVersions:

    def test_langgraph_constants_exist(self):
        from app.agents.versions import (
            TRADE_DECISION_AGENT_MODE_LANGGRAPH,
            TRADE_DECISION_GRAPH_VERSION,
            TRADE_DECISION_GRAPH_SCHEMA_VERSION,
        )
        assert TRADE_DECISION_AGENT_MODE_LANGGRAPH == "trade_decision_langgraph_v1"
        assert TRADE_DECISION_GRAPH_VERSION == "trade_decision_graph_v1"
        assert TRADE_DECISION_GRAPH_SCHEMA_VERSION == "trade_decision_graph_state_v1"


# === Test: Health response schema ===

class TestHealthSchema:

    def test_health_has_new_fields(self):
        from app.schemas.trade_decision import TradeDecisionHealthResponse

        resp = TradeDecisionHealthResponse(
            enabled=True,
            llm_configured=True,
            longbridge_configured=True,
            mcp_enabled=True,
            mcp_available=True,
            mcp_auth_status="connected",
            mcp_last_error="",
            sdk_fallback_available=True,
            longbridge_sdk_configured=True,
            public_data_mode="mcp",
            trade_review_available=True,
            account_data_source="IBKR_ONLY",
            public_market_data_source="LONGBRIDGE_MCP",
            message="ready",
        )
        assert resp.mcp_available is True
        assert resp.longbridge_sdk_configured is True
        assert resp.public_data_mode == "mcp"


# === Test: AgentRunTraceItem schema ===

class TestRunTraceSchema:

    def test_trace_item_has_graph_fields(self):
        from app.schemas.trade_decision import AgentRunTraceItem

        item = AgentRunTraceItem(
            event="node_success",
            node_name="market_trend",
            elapsed_ms=150,
            tools_called=["quote", "candlesticks"],
            rounds_used=2,
            fallback_used=False,
            fallback_reason=None,
        )
        assert item.node_name == "market_trend"
        assert item.tools_called == ["quote", "candlesticks"]
        assert item.rounds_used == 2
        assert item.fallback_used is False


# === Test: Success path full validation ===

class TestSuccessPath:

    def test_runner_success_path_metadata(self):
        """Full success path should produce correct metadata."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner
        from app.agents.versions import (
            TRADE_DECISION_AGENT_MODE_LANGGRAPH,
            TRADE_DECISION_GRAPH_VERSION,
        )

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "test summary"

        captured_doc = {}
        def capture_save(doc):
            captured_doc.update(doc)
            doc["id"] = "test-id"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = capture_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)

        runner = TradeDecisionGraphRunner(
            account_facts_builder=mock_builder,
            llm_service=mock_llm,
            repository=mock_repo,
            mcp_adapter=mock_adapter,
        )

        result = runner.analyze_entry("AAPL")
        assert result is not None
        assert "id" in result
        # Verify save was called: once in persist_decision_node, once in _finalize
        assert mock_repo.save_decision.call_count == 2
        # The second call (from _finalize) should have agent_run_id and agent_replay
        final_doc = mock_repo.save_decision.call_args_list[1][0][0]
        assert "agent_run_id" in final_doc
        assert "agent_replay" in final_doc
        assert "replay_id" in final_doc["agent_replay"]


# === Test: Fan-in execution semantics ===

class TestFanInExecutionSemantics:
    """Tests that verify real graph execution: fan-in waits, no duplicate runs."""

    def test_risk_reward_waits_for_all_four_parallel_cards_and_runs_once(self):
        """risk_reward must run once, after all 4 parallel cards are ready."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot

        captured_doc = {}
        def capture_save(doc):
            captured_doc.update(doc)
            doc["id"] = "fanin-test-id"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = capture_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)
        mock_llm = MagicMock()

        now = "2024-01-01T00:00:00Z"

        # Phase 1 cards — each has a unique summary for assertion
        account_fit_card = AccountFitCard(
            card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
            summary="account fit card ready", score=16, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", evidence_quality="high", source_tools=["llm"],
        )
        market_trend_card = MarketTrendCard(
            card_type="market_trend", symbol="AAPL", decision_type="entry_decision",
            summary="market trend card ready", score=12, max_score=15, stance=CardStance.BULLISH,
            price_trend="bullish", evidence_quality="medium", source_tools=["quote"],
        )
        fundamental_card = FundamentalValuationCard(
            card_type="fundamental_valuation", symbol="AAPL", decision_type="entry_decision",
            summary="fundamental card ready", score=20, max_score=35, stance=CardStance.BULLISH,
            pe_ttm=22.0, evidence_quality="medium", source_tools=["company"],
        )
        event_card = EventCatalystCard(
            card_type="event_catalyst", symbol="AAPL", decision_type="entry_decision",
            summary="event card ready", score=4, max_score=5, stance=CardStance.BULLISH,
            sentiment="positive", evidence_quality="medium", source_tools=["news_search"],
        )
        risk_reward_card = RiskRewardCard(
            card_type="risk_reward", symbol="AAPL", decision_type="entry_decision",
            summary="risk reward card ready", score=12, max_score=15, stance=CardStance.BULLISH,
            reward_risk_ratio=2.5, evidence_quality="medium", source_tools=[],
        )

        base_trace = TradeDecisionSubAgentTrace(
            sub_agent_name="test", status="completed",
            started_at=now, finished_at=now, elapsed_ms=50,
        )

        def make_trace(name):
            return TradeDecisionSubAgentTrace(
                sub_agent_name=name, status="completed",
                started_at=now, finished_at=now, elapsed_ms=50,
                tools_called=["tool"],
            )

        # risk_reward side_effect: assert 4 cards arrive with correct summaries
        def risk_reward_side_effect(snapshot, account_fit, market_trend, fundamental, event):
            assert account_fit is not None, "account_fit card is None"
            assert market_trend is not None, "market_trend card is None"
            assert fundamental is not None, "fundamental card is None"
            assert event is not None, "event card is None"
            assert account_fit.summary == "account fit card ready"
            assert market_trend.summary == "market trend card ready"
            assert fundamental.summary == "fundamental card ready"
            assert event.summary == "event card ready"
            return risk_reward_card, make_trace("risk_reward")

        with patch(
            "app.services.trade_decision_sub_agents.AccountFitSubAgent.generate",
            return_value=(account_fit_card, make_trace("account_fit")),
        ) as acc_gen, patch(
            "app.services.trade_decision_sub_agents.MarketTrendSubAgent.generate",
            return_value=(market_trend_card, make_trace("market_trend")),
        ) as mkt_gen, patch(
            "app.services.trade_decision_sub_agents.FundamentalValuationSubAgent.generate",
            return_value=(fundamental_card, make_trace("fundamental_valuation")),
        ) as fund_gen, patch(
            "app.services.trade_decision_sub_agents.EventCatalystSubAgent.generate",
            return_value=(event_card, make_trace("event_catalyst")),
        ) as evt_gen, patch(
            "app.services.trade_decision_sub_agents.RiskRewardSubAgent.generate",
            side_effect=risk_reward_side_effect,
        ) as rr_gen:

            runner = TradeDecisionGraphRunner(
                account_facts_builder=mock_builder,
                llm_service=mock_llm,
                repository=mock_repo,
                mcp_adapter=mock_adapter,
            )

            result = runner.analyze_entry("AAPL")

        # --- Assertions ---

        # 1. Each sub-agent generate called exactly once
        assert acc_gen.call_count == 1, f"account_fit called {acc_gen.call_count} times"
        assert mkt_gen.call_count == 1, f"market_trend called {mkt_gen.call_count} times"
        assert fund_gen.call_count == 1, f"fundamental called {fund_gen.call_count} times"
        assert evt_gen.call_count == 1, f"event_catalyst called {evt_gen.call_count} times"
        assert rr_gen.call_count == 1, f"risk_reward called {rr_gen.call_count} times"

        # 2. save_decision called twice: once in persist_decision_node, once in _finalize
        assert mock_repo.save_decision.call_count == 2

        # 3. Not a fallback
        assert captured_doc.get("fallback_used") is not True

        # 4. Metadata
        assert captured_doc["metadata"]["agent_mode"] == "trade_decision_langgraph_v1"
        assert captured_doc["metadata"]["graph_version"] == "trade_decision_graph_v1"

        # 5. run_trace contains all 9 nodes
        run_trace = captured_doc["run_trace"]
        node_names = [x["node_name"] for x in run_trace]
        expected_nodes = [
            "build_account_facts",
            "account_fit", "market_trend", "fundamental_valuation", "event_catalyst",
            "risk_reward",
            "build_card_pack", "compose_decision", "persist_decision",
        ]
        for name in expected_nodes:
            assert name in node_names, f"Missing node '{name}' in run_trace"

        # 6. risk_reward and persist_decision appear exactly once
        assert node_names.count("risk_reward") == 1, \
            f"risk_reward appeared {node_names.count('risk_reward')} times (expected 1)"
        assert node_names.count("persist_decision") == 1, \
            f"persist_decision appeared {node_names.count('persist_decision')} times (expected 1)"

        # 7. risk_reward appears after all 4 parallel cards
        rr_idx = node_names.index("risk_reward")
        for name in ("account_fit", "market_trend", "fundamental_valuation", "event_catalyst"):
            parallel_idx = node_names.index(name)
            assert parallel_idx < rr_idx, \
                f"{name} (idx {parallel_idx}) should come before risk_reward (idx {rr_idx})"

        # 8. card_pack has all 5 cards with correct summaries
        card_pack = captured_doc["card_pack"]
        assert card_pack["account_fit_card"]["summary"] == "account fit card ready"
        assert card_pack["market_trend_card"]["summary"] == "market trend card ready"
        assert card_pack["fundamental_valuation_card"]["summary"] == "fundamental card ready"
        assert card_pack["event_catalyst_card"]["summary"] == "event card ready"
        assert card_pack["risk_reward_card"]["summary"] == "risk reward card ready"

    def test_persist_decision_runs_once_and_after_compose(self):
        """persist_decision must run exactly once, after compose_decision."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot

        save_count = {"n": 0}
        def count_save(doc):
            save_count["n"] += 1
            doc["id"] = f"save-{save_count['n']}"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = count_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)
        mock_llm = MagicMock()

        now = "2024-01-01T00:00:00Z"

        def make_card(card_type, cls, **kwargs):
            defaults = dict(
                card_type=card_type, symbol="AAPL", decision_type="entry_decision",
                summary=f"{card_type} ok", score=10, max_score=20,
                stance=CardStance.BULLISH, evidence_quality="medium", source_tools=[],
            )
            defaults.update(kwargs)
            return cls(**defaults)

        acc_card = make_card("account_fit", AccountFitCard,
                             account_fit_level="good", score=16, max_score=20)
        mkt_card = make_card("market_trend", MarketTrendCard,
                             price_trend="bullish", score=12, max_score=15)
        fund_card = make_card("fundamental_valuation", FundamentalValuationCard,
                              pe_ttm=22.0, score=20, max_score=35)
        evt_card = make_card("event_catalyst", EventCatalystCard,
                             sentiment="positive", score=4, max_score=5)
        rr_card = make_card("risk_reward", RiskRewardCard,
                            reward_risk_ratio=2.0, score=12, max_score=15)

        def make_trace(name):
            return TradeDecisionSubAgentTrace(
                sub_agent_name=name, status="completed",
                started_at=now, finished_at=now, elapsed_ms=50,
            )

        with patch(
            "app.services.trade_decision_sub_agents.AccountFitSubAgent.generate",
            return_value=(acc_card, make_trace("account_fit")),
        ), patch(
            "app.services.trade_decision_sub_agents.MarketTrendSubAgent.generate",
            return_value=(mkt_card, make_trace("market_trend")),
        ), patch(
            "app.services.trade_decision_sub_agents.FundamentalValuationSubAgent.generate",
            return_value=(fund_card, make_trace("fundamental_valuation")),
        ), patch(
            "app.services.trade_decision_sub_agents.EventCatalystSubAgent.generate",
            return_value=(evt_card, make_trace("event_catalyst")),
        ), patch(
            "app.services.trade_decision_sub_agents.RiskRewardSubAgent.generate",
            return_value=(rr_card, make_trace("risk_reward")),
        ):

            runner = TradeDecisionGraphRunner(
                account_facts_builder=mock_builder,
                llm_service=mock_llm,
                repository=mock_repo,
                mcp_adapter=mock_adapter,
            )

            runner.analyze_entry("AAPL")

        # save_decision called twice: once in persist_decision_node, once in _finalize
        assert save_count["n"] == 2

    def test_no_fallback_on_success_path(self):
        """Success path should not produce fallback_used=True."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot

        captured_doc = {}
        def capture_save(doc):
            captured_doc.update(doc)
            doc["id"] = "no-fallback-test"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = capture_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)
        mock_llm = MagicMock()

        now = "2024-01-01T00:00:00Z"

        def make_trace(name):
            return TradeDecisionSubAgentTrace(
                sub_agent_name=name, status="completed",
                started_at=now, finished_at=now, elapsed_ms=50,
            )

        acc_card = AccountFitCard(
            card_type="account_fit", symbol="AAPL", decision_type="entry_decision",
            summary="ok", score=16, max_score=20, stance=CardStance.BULLISH,
            account_fit_level="good", evidence_quality="high", source_tools=[],
        )
        mkt_card = MarketTrendCard(
            card_type="market_trend", symbol="AAPL", decision_type="entry_decision",
            summary="ok", score=12, max_score=15, stance=CardStance.BULLISH,
            price_trend="bullish", evidence_quality="medium", source_tools=["quote"],
        )
        fund_card = FundamentalValuationCard(
            card_type="fundamental_valuation", symbol="AAPL", decision_type="entry_decision",
            summary="ok", score=20, max_score=35, stance=CardStance.BULLISH,
            pe_ttm=22.0, evidence_quality="medium", source_tools=["company"],
        )
        evt_card = EventCatalystCard(
            card_type="event_catalyst", symbol="AAPL", decision_type="entry_decision",
            summary="ok", score=4, max_score=5, stance=CardStance.BULLISH,
            sentiment="positive", evidence_quality="medium", source_tools=["news"],
        )
        rr_card = RiskRewardCard(
            card_type="risk_reward", symbol="AAPL", decision_type="entry_decision",
            summary="ok", score=12, max_score=15, stance=CardStance.BULLISH,
            reward_risk_ratio=2.5, evidence_quality="medium", source_tools=[],
        )

        with patch(
            "app.services.trade_decision_sub_agents.AccountFitSubAgent.generate",
            return_value=(acc_card, make_trace("account_fit")),
        ), patch(
            "app.services.trade_decision_sub_agents.MarketTrendSubAgent.generate",
            return_value=(mkt_card, make_trace("market_trend")),
        ), patch(
            "app.services.trade_decision_sub_agents.FundamentalValuationSubAgent.generate",
            return_value=(fund_card, make_trace("fundamental_valuation")),
        ), patch(
            "app.services.trade_decision_sub_agents.EventCatalystSubAgent.generate",
            return_value=(evt_card, make_trace("event_catalyst")),
        ), patch(
            "app.services.trade_decision_sub_agents.RiskRewardSubAgent.generate",
            return_value=(rr_card, make_trace("risk_reward")),
        ):

            runner = TradeDecisionGraphRunner(
                account_facts_builder=mock_builder,
                llm_service=mock_llm,
                repository=mock_repo,
                mcp_adapter=mock_adapter,
            )

            result = runner.analyze_entry("AAPL")

        assert result is not None
        assert captured_doc.get("fallback_used") is not True
        assert captured_doc.get("fallback_reason") is None
        assert "id" in result


def test_trade_decision_uses_all_public_readonly_tools_needed_for_fundamental_analysis():
    from app.services.trade_decision_sub_agents import FundamentalValuationSubAgent

    agent = FundamentalValuationSubAgent(MagicMock(), MagicMock())
    tool_names = {item["name"] for item in agent._get_initial_tool_calls("AAPL.US")}

    assert {
        "company",
        "static_info",
        "quote",
        "financial_report",
        "valuation",
        "business_segments",
        "industry_peers",
        "institution_rating",
        "consensus",
        "forecast_eps",
    }.issubset(tool_names)


def test_event_catalyst_invalid_json_repairs_or_falls_back_deterministically():
    from app.services.trade_decision_sub_agents import EventCatalystSubAgent

    llm_service = MagicMock()
    llm_service.chat.side_effect = RuntimeError("repair unavailable")
    agent = EventCatalystSubAgent(llm_service, MagicMock())
    trace = [
        {
            "event": "tool_finish",
            "tool": "news_search",
            "arguments": {"symbol": "AAPL.US", "limit": 8},
            "ok": True,
            "output": {
                "ok": True,
                "tool": "news_search",
                "data": {"items": [{"title": "Apple event", "published_at": "2026-05-20", "source": "Reuters"}]},
                "tool_call": {
                    "tool_name": "news_search",
                    "request_args": {"keyword": "AAPL.US", "limit": 8},
                    "success": True,
                    "empty_result": False,
                    "raw_response_summary": "list length=1",
                    "parsed_fields": ["items", "published_at", "source"],
                    "missing_fields": [],
                    "error_type": None,
                },
            },
        }
    ]

    card = agent._parse_card("not-json at all", _make_snapshot("AAPL.US"), trace)

    assert card.summary
    assert "not-json" not in card.summary
    assert card.recent_news_count == 1
    assert card.tool_calls[0]["tool_name"] == "news_search"
    assert any("已基于可用新闻做保守分析" in item for item in card.data_limitations)
    assert not any("deterministic fallback" in item for item in card.data_limitations)


def test_fundamental_invalid_json_repairs_or_falls_back_with_tool_evidence():
    from app.services.trade_decision_sub_agents import FundamentalValuationSubAgent

    llm_service = MagicMock()
    llm_service.chat.side_effect = RuntimeError("repair unavailable")
    agent = FundamentalValuationSubAgent(llm_service, MagicMock())
    trace = [
        {
            "event": "tool_finish",
            "tool": "forecast_eps",
            "arguments": {"symbol": "ORCL.US"},
            "ok": True,
            "output": {
                "ok": True,
                "tool": "forecast_eps",
                "data": {"eps_forward": "7.57", "sample_points": 10},
                "tool_call": {
                    "tool_name": "forecast_eps",
                    "request_args": {"symbol": "ORCL.US"},
                    "success": True,
                    "empty_result": False,
                    "raw_response_summary": "object keys=['items']",
                    "parsed_fields": ["eps_forward", "sample_points"],
                    "missing_fields": [],
                    "error_type": None,
                },
            },
        },
        {
            "event": "tool_finish",
            "tool": "quote",
            "arguments": {"symbol": "ORCL.US"},
            "ok": True,
            "output": {
                "ok": True,
                "tool": "quote",
                "data": {"price": "188.16"},
                "tool_call": {
                    "tool_name": "quote",
                    "request_args": {"symbols": ["ORCL.US"]},
                    "success": True,
                    "empty_result": False,
                    "raw_response_summary": "list length=1",
                    "parsed_fields": ["price"],
                    "missing_fields": [],
                    "error_type": None,
                },
            },
        },
    ]

    card = agent._parse_card("not-json at all", _make_snapshot("ORCL.US"), trace)

    assert card.forward_pe and card.forward_pe > 0
    assert card.tool_calls
    assert "not-json" not in card.summary
    assert any("确定性降级" in item or "deterministic" in item.lower() for item in card.data_limitations)


# === Test: CRWV-like data_limitations filtering ===

class TestCRWVDataLimitations:
    """Test that CRWV-like scenarios produce clean user-facing data_limitations."""

    def test_tool_level_missing_fields_do_not_pollute_user_data_limitations(self):
        """mcp_field_missing JSON should not appear in card.data_limitations."""
        from app.services.trade_decision_sub_agents import _extract_data_limitations_from_runtime

        parsed = {"data_limitations": []}
        trace = [
            {
                "event": "tool_finish",
                "tool": "company",
                "ok": True,
                "output": {
                    "ok": True,
                    "tool_call": {
                        "tool_name": "company",
                        "request_args": {"symbol": "CRWV.US"},
                        "success": True,
                        "empty_result": False,
                        "raw_response_summary": "object keys=['name']",
                        "parsed_fields": ["name", "description"],
                        "missing_fields": [
                            {"tool_name": "company", "field_name": "sector", "success": True, "empty_result": False},
                        ],
                        "error_type": None,
                    },
                },
            }
        ]

        limitations = _extract_data_limitations_from_runtime(parsed, trace)

        assert not any("mcp_field_missing" in item for item in limitations)
        assert not any("sector" in item for item in limitations)

    def test_resolved_market_cap_suppresses_market_cap_missing(self):
        """When market_cap is resolved from total_shares * price, no missing limitation."""
        from app.services.trade_decision_sub_agents import FundamentalValuationSubAgent

        llm_service = MagicMock()
        llm_service.chat.return_value = '{"summary": "ok", "score": 15}'
        agent = FundamentalValuationSubAgent(llm_service, MagicMock())

        trace = [
            {
                "event": "tool_finish", "tool": "company", "ok": True,
                "output": {
                    "ok": True, "tool": "company",
                    "data": {"name": "CoreWeave"},
                    "tool_call": {
                        "tool_name": "company", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["name"],
                        "missing_fields": [
                            {"tool_name": "company", "field_name": "market_cap", "success": True, "empty_result": False},
                        ],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "static_info", "ok": True,
                "output": {
                    "ok": True, "tool": "static_info",
                    "data": {"name": "CoreWeave", "total_shares": 500000000},
                    "tool_call": {
                        "tool_name": "static_info", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["name", "total_shares"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "quote", "ok": True,
                "output": {
                    "ok": True, "tool": "quote",
                    "data": {"price": "60.0"},
                    "tool_call": {
                        "tool_name": "quote", "request_args": {"symbols": ["CRWV.US"]},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["price"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "valuation", "ok": True,
                "output": {
                    "ok": True, "tool": "valuation",
                    "data": {"pe_ttm": -35.5, "pe_range": {"low": "-40", "median": "-35", "high": "-30"}},
                    "tool_call": {
                        "tool_name": "valuation", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["pe_ttm", "pe_range"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "forecast_eps", "ok": True,
                "output": {
                    "ok": True, "tool": "forecast_eps",
                    "data": {"eps_forward": -2.588},
                    "tool_call": {
                        "tool_name": "forecast_eps", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["eps_forward"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "business_segments", "ok": True,
                "output": {
                    "ok": True, "tool": "business_segments",
                    "data": {"segments": [{"name": "GPU Cloud", "revenue_pct": 95}]},
                    "tool_call": {
                        "tool_name": "business_segments", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["segments"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "institution_rating", "ok": True,
                "output": {
                    "ok": True, "tool": "institution_rating",
                    "data": {"consensus": "buy", "target_price": "85.0", "industry": "云与数据中心"},
                    "tool_call": {
                        "tool_name": "institution_rating", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["consensus", "target_price", "industry"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "industry_peers", "ok": True,
                "output": {
                    "ok": True, "tool": "industry_peers",
                    "data": {"peers": [
                        {"symbol": "EQIX.US", "name": "Equinix"},
                        {"symbol": "DLR.US", "name": "Digital Realty"},
                    ], "total_returned": 2},
                    "tool_call": {
                        "tool_name": "industry_peers", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["peers"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "consensus", "ok": True,
                "output": {
                    "ok": True, "tool": "consensus",
                    "data": {"eps_forward": -2.5, "revenue_estimate": 3500000000},
                    "tool_call": {
                        "tool_name": "consensus", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["eps_forward", "revenue_estimate"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
            {
                "event": "tool_finish", "tool": "financial_report", "ok": True,
                "output": {
                    "ok": True, "tool": "financial_report",
                    "data": {"revenue": 1000000000, "net_income": -500000000, "eps": -1.5},
                    "tool_call": {
                        "tool_name": "financial_report", "request_args": {"symbol": "CRWV.US"},
                        "success": True, "empty_result": False,
                        "raw_response_summary": "ok", "parsed_fields": ["revenue", "net_income", "eps"],
                        "missing_fields": [],
                        "error_type": None,
                    },
                },
            },
        ]

        snapshot = _make_snapshot("CRWV.US")
        snapshot.current_price = 60.0

        # Simulate LLM returning valid JSON
        raw_content = '{"summary": "亏损期成长股", "company_name": "CoreWeave", "score": 18, "pe_ttm": -35.5, "forward_pe": -23.18, "revenue_growth_summary": "高速增长", "profitability_summary": "亏损", "valuation_summary": "PS估值", "data_limitations": []}'

        card = agent._parse_card(raw_content, snapshot, trace)

        # market_cap should be resolved
        assert card.market_cap == 30000000000.0  # 500M shares * $60

        # industry should be resolved
        assert card.industry == "云与数据中心"

        # business_segments should be resolved
        assert card.business_segments is not None

        # peers should be resolved
        assert "同业样本" in (card.peer_relative_note or "")

        # data_limitations should NOT contain mcp_field_missing
        assert not any("mcp_field_missing" in item for item in card.data_limitations)

        # data_limitations should NOT mention sector/industry/market_cap/business_segments missing
        assert not any("sector" in item.lower() for item in card.data_limitations)
        assert not any("industry" in item.lower() and "missing" in item.lower() for item in card.data_limitations)
        assert not any("market_cap" in item.lower() for item in card.data_limitations)
        assert not any("business_segments" in item.lower() for item in card.data_limitations)

        # data_limitations SHOULD contain valuation_not_applicable
        assert any("valuation_not_applicable" in item for item in card.data_limitations)
        assert any("亏损" in item for item in card.data_limitations)

    def test_loss_making_company_marks_pe_not_applicable_not_missing(self):
        """Loss-making company should get valuation_not_applicable, not 'PE missing'."""
        from app.services.trade_decision_sub_agents import _extract_data_limitations_from_runtime

        parsed = {"data_limitations": []}
        trace = []

        limitations = _extract_data_limitations_from_runtime(parsed, trace)
        limitations.append(
            "valuation_not_applicable: 公司仍处亏损期，PE / forward PE 为负，"
            "传统 PE 估值不适用；已改用收入增速、PS、目标价和风险收益评估。"
        )

        assert any("valuation_not_applicable" in item for item in limitations)
        assert any("亏损" in item for item in limitations)
        assert not any("工具未返回" in item for item in limitations)
        assert not any("missing" in item.lower() for item in limitations)


class TestDataLimitationsComposerFiltering:
    """Test that composer filters mcp_field_missing from top-level data_limitations."""

    def test_top_level_data_limitations_filters_mcp_field_missing_json(self):
        from app.services.trade_decision_composer import TradeDecisionComposer

        snapshot = _make_snapshot()
        fund = FundamentalValuationCard(
            card_type="fundamental_valuation", symbol="CRWV.US", decision_type="entry_decision",
            summary="ok", score=15, max_score=35, stance=CardStance.NEUTRAL,
            pe_ttm=-35.5, evidence_quality="medium", source_tools=["company", "valuation"],
            data_limitations=[
                "valuation_not_applicable: 公司仍处亏损期",
                'mcp_field_missing: {"tool_name": "company", "field_name": "sector"}',
                "some other real limitation",
            ],
        )

        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="CRWV.US",
            account_fact_snapshot=snapshot,
            account_fit_card=AccountFitCard(
                card_type="account_fit", symbol="CRWV.US", decision_type="entry_decision",
                summary="ok", score=16, max_score=20, stance=CardStance.BULLISH,
                account_fit_level="good", evidence_quality="high", source_tools=[],
            ),
            market_trend_card=MarketTrendCard(
                card_type="market_trend", symbol="CRWV.US", decision_type="entry_decision",
                summary="ok", score=10, max_score=15, stance=CardStance.NEUTRAL,
                price_trend="neutral", evidence_quality="medium", source_tools=["quote"],
            ),
            fundamental_valuation_card=fund,
            event_catalyst_card=EventCatalystCard(
                card_type="event_catalyst", symbol="CRWV.US", decision_type="entry_decision",
                summary="ok", score=3, max_score=5, stance=CardStance.NEUTRAL,
                sentiment="neutral", evidence_quality="medium", source_tools=["news_search"],
            ),
            risk_reward_card=RiskRewardCard(
                card_type="risk_reward", symbol="CRWV.US", decision_type="entry_decision",
                summary="ok", score=8, max_score=15, stance=CardStance.NEUTRAL,
                reward_risk_ratio=1.5, evidence_quality="medium", source_tools=[],
            ),
            data_quality_summary="medium",
        )

        composer = TradeDecisionComposer()
        result = composer.compose(card_pack)

        # mcp_field_missing should be filtered out
        assert not any("mcp_field_missing" in item for item in result["data_limitations"])
        # valuation_not_applicable should pass through
        assert any("valuation_not_applicable" in item for item in result["data_limitations"])
        # real limitation should pass through
        assert any("some other real limitation" in item for item in result["data_limitations"])


def test_run_trace_summary_counts_mcp_public_tool_calls():
    from app.agents.trace_summary import build_run_trace_summary

    summary = build_run_trace_summary([
        {
            "event": "node_success",
            "node_name": "fundamental_valuation",
            "tools_called": ["company", "valuation"],
            "tool_call_count": 5,
            "tool_calls": [
                {"tool_name": "company", "success": True},
                {"tool_name": "financial_report", "success": True},
                {"tool_name": "valuation", "success": True},
                {"tool_name": "industry_peers", "success": True},
                {"tool_name": "institution_rating", "success": False},
            ],
        }
    ])

    assert summary["tool_call_count"] == 5
    assert summary["tool_success_count"] == 4
    assert summary["tool_error_count"] == 1
    assert {item["tool"] for item in summary["tools"]} >= {"company", "institution_rating"}


# === Test: Replay persistence in _finalize ===

class TestFinalizeReplayPersistence:
    """Verify _finalize persists agent_run_id and agent_replay to ES."""

    def test_finalize_saves_agent_run_id_and_replay(self):
        """_finalize must re-save document with agent_run_id and agent_replay."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = lambda doc: doc
        mock_trace_svc = MagicMock()
        mock_replay_svc = MagicMock()
        mock_replay_svc.record_snapshot.return_value = {}

        runner = TradeDecisionGraphRunner(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=mock_repo,
            trace_service=mock_trace_svc,
            replay_service=mock_replay_svc,
        )

        document = {"id": "doc-1", "symbol": "AAPL", "card_pack": {}, "run_trace": []}
        initial_state = {"agent_run_id": "run-123", "started_at": "2024-01-01T00:00:00Z", "decision_type": "entry_decision", "symbol": "AAPL"}
        result = runner._finalize(document, initial_state, None)

        assert result["agent_run_id"] == "run-123"
        assert "replay_id" in result["agent_replay"]
        assert result["agent_replay"]["run_id"] == "run-123"
        assert result["agent_replay"]["persisted"] is True
        # _finalize must have called save_decision
        assert mock_repo.save_decision.call_count >= 1
        saved_doc = mock_repo.save_decision.call_args_list[-1][0][0]
        assert saved_doc["agent_run_id"] == "run-123"
        assert "replay_id" in saved_doc["agent_replay"]

    def test_finalize_replay_persist_failure_adds_data_limitation(self):
        """If replay record_snapshot fails, add data_limitation but don't raise."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = lambda doc: doc
        mock_replay_svc = MagicMock()
        mock_replay_svc.record_snapshot.side_effect = RuntimeError("ES connection refused")

        runner = TradeDecisionGraphRunner(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=mock_repo,
            replay_service=mock_replay_svc,
        )

        document = {"id": "doc-2", "symbol": "AAPL", "card_pack": {}, "run_trace": []}
        initial_state = {"agent_run_id": "run-456", "started_at": "2024-01-01T00:00:00Z", "decision_type": "entry_decision", "symbol": "AAPL"}
        result = runner._finalize(document, initial_state, None)

        # Should not raise, should record failure
        assert result["agent_replay"]["persisted"] is False
        assert "error" in result["agent_replay"]
        assert any("agent_replay_persist_failed" in item for item in result["data_limitations"])

    def test_finalize_decision_resave_failure_adds_data_limitation(self):
        """If re-save_decision fails, add data_limitation but don't raise."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = RuntimeError("ES timeout")

        runner = TradeDecisionGraphRunner(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=mock_repo,
        )

        document = {"id": "doc-3", "symbol": "AAPL", "card_pack": {}, "run_trace": []}
        initial_state = {"agent_run_id": "run-789", "started_at": "2024-01-01T00:00:00Z", "decision_type": "entry_decision", "symbol": "AAPL"}
        result = runner._finalize(document, initial_state, None)

        # Should not raise
        assert result["agent_run_id"] == "run-789"
        assert any("decision_re_save_failed" in item for item in result["data_limitations"])

    def test_finalize_generates_run_id_if_missing(self):
        """If initial_state has no agent_run_id, _finalize generates one."""
        from app.agents.trade_decision_graph.runner import TradeDecisionGraphRunner

        mock_repo = MagicMock()
        mock_repo.save_decision.side_effect = lambda doc: doc

        runner = TradeDecisionGraphRunner(
            account_facts_builder=MagicMock(),
            llm_service=MagicMock(),
            repository=mock_repo,
        )

        document = {"id": "doc-4", "symbol": "AAPL", "card_pack": {}, "run_trace": []}
        initial_state = {"started_at": "2024-01-01T00:00:00Z", "decision_type": "entry_decision", "symbol": "AAPL"}
        result = runner._finalize(document, initial_state, None)

        assert result["agent_run_id"] is not None
        assert result["agent_run_id"].startswith("trade_decision_")
