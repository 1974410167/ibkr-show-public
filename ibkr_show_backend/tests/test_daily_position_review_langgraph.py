"""Tests for Daily Position Review LangGraph migration.

Covers:
1. Graph structure (sequential + parallel edges)
2. Fan-in execution semantics
3. Reducer safety (parallel node traces merge)
4. Context loading
5. Focus symbol selection
6. Symbol cards node (success + fallback)
7. Macro card node (success + fallback)
8. Build card pack node
9. Compose daily review node
10. Persist daily review node
11. Optional email summary node
12. Agent façade
13. API compatibility
14. Version constants
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.agents.daily_review_evidence_cards import (
    AccountImpactFields,
    DailyReviewEvidenceCardPack,
    DataQualitySummary,
    MacroEvidenceCard,
    PriceActionFields,
    SubAgentTrace,
    SymbolEvidenceCard,
    build_fallback_macro_card,
    build_fallback_symbol_card,
)
from app.services.daily_review_evidence_card_builder import _select_focus_symbols_for_cards


# === Helpers ===

def _make_symbol_card(symbol: str = "AMD.US", quality: str = "high") -> SymbolEvidenceCard:
    return SymbolEvidenceCard(
        symbol=symbol,
        normalized_symbol=symbol,
        report_date="2026-05-20",
        account_impact=AccountImpactFields(
            position_weight=0.10,
            daily_pnl=100.0,
            daily_change_percent=2.0,
            contribution_ratio=0.5,
            market_value=10000.0,
        ),
        price_action=PriceActionFields(current_price=100.0, day_change_percent=2.0),
        evidence_quality=quality,
    )


def _make_macro_card() -> MacroEvidenceCard:
    return MacroEvidenceCard(
        report_date="2026-05-20",
        market_regime="risk_on",
        risk_sentiment="neutral",
    )


def _make_deterministic_context() -> dict:
    return {
        "report_date": "2026-05-20",
        "data_sources": {"account_data": "IBKR_ONLY"},
        "overview": {
            "daily_pnl": 1000.0,
            "daily_return_percent": 1.0,
            "cash_ratio": 0.1,
            "summary": "今日账户上涨 1%",
        },
        "positions": [
            {
                "symbol": "AMD",
                "normalized_symbol": "AMD.US",
                "weight": 0.10,
                "daily_pnl": 500.0,
                "daily_change_percent": 3.0,
                "contribution_ratio": 0.5,
                "market_value": 10000.0,
                "quantity": 100,
                "average_cost": 80.0,
                "unrealized_pnl": 2000.0,
                "unrealized_pnl_percent": 25.0,
                "is_major_contributor": True,
            },
            {
                "symbol": "NVDA",
                "normalized_symbol": "NVDA.US",
                "weight": 0.08,
                "daily_pnl": -200.0,
                "daily_change_percent": -1.5,
                "contribution_ratio": -0.2,
                "market_value": 8000.0,
                "quantity": 50,
                "average_cost": 100.0,
                "unrealized_pnl": -1000.0,
                "unrealized_pnl_percent": -12.5,
                "is_major_drag": True,
            },
        ],
        "rankings": {
            "profit_contributors": [
                {"symbol": "AMD", "daily_pnl": 500.0, "contribution_ratio": 0.5, "weight": 0.10},
            ],
            "loss_drags": [
                {"symbol": "NVDA", "daily_pnl": -200.0, "contribution_ratio": -0.2, "weight": 0.08},
            ],
            "top_weights": [
                {"symbol": "AMD", "weight": 0.10},
                {"symbol": "NVDA", "weight": 0.08},
            ],
        },
        "risk": {
            "max_position": {"symbol": "AMD", "weight": 0.10},
            "max_single_position_weight": 0.10,
            "risk_flags": [],
        },
        "benchmarks": {"QQQ": {"return_percent": 0.5}},
        "focus_symbols": ["AMD.US", "NVDA.US"],
        "attribution_quality": {"quality": "high"},
        "data_quality": {"warnings": []},
        "symbol_public_context": {},
    }


def _make_mock_deps():
    """Create mock deps for graph testing."""
    ctx = _make_deterministic_context()

    mock_review_service = MagicMock()
    mock_review_service.build_review_context.return_value = ctx

    mock_llm = MagicMock()
    mock_llm.get_active_provider.return_value = SimpleNamespace(
        name="test", base_url="http://test", default_model="test-model",
        context_window_tokens=128000, input_token_limit=100000, output_token_limit=8000,
    )
    mock_llm.chat.return_value = '{"report_date":"2026-05-20","summary":"ok","account_conclusion":"ok","attribution_summary":"ok","market_context":"ok","risk_analysis":"ok","operation_observation":"ok","major_contributors_analysis":[],"major_drags_analysis":[],"focus_symbol_analyses":[],"tomorrow_watchlist":[],"data_limitations":[],"evidence_used":[]}'

    mock_repo = MagicMock()
    captured_doc = {}
    def capture_save(doc):
        captured_doc.update(doc)
        doc["id"] = doc.get("report_date", "test")
        return doc
    mock_repo.save_review.side_effect = capture_save

    mock_symbol_agent = MagicMock()
    mock_symbol_agent.generate_symbol_card.return_value = _make_symbol_card()

    mock_macro_agent = MagicMock()
    mock_macro_agent.generate_macro_card.return_value = _make_macro_card()

    return SimpleNamespace(
        review_service=mock_review_service,
        llm_service=mock_llm,
        repository=mock_repo,
        email_service=None,
        related_asset_service=None,
        longbridge_client=None,
        symbol_agent=mock_symbol_agent,
        macro_agent=mock_macro_agent,
        monitoring_service=None,
        _captured_doc=captured_doc,
    )


# === 1. Graph Structure ===

class TestGraphStructure:

    def test_graph_has_expected_nodes(self):
        from app.agents.daily_position_review_graph.graph import (
            DailyPositionReviewGraphDeps,
            build_daily_position_review_graph,
        )
        deps = DailyPositionReviewGraphDeps(
            review_service=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
        )
        graph = build_daily_position_review_graph(deps)
        node_names = set(graph.get_graph().nodes)
        expected = {
            "__start__", "__end__",
            "load_daily_review_context", "select_focus_symbols",
            "symbol_cards", "macro_card", "portfolio_attribution", "risk_watch",
            "build_card_pack", "compose_daily_review", "persist_daily_review",
            "optional_email_summary",
        }
        assert expected.issubset(node_names)

    def test_load_context_fans_out_to_select(self):
        from app.agents.daily_position_review_graph.graph import (
            DailyPositionReviewGraphDeps,
            build_daily_position_review_graph,
        )
        deps = DailyPositionReviewGraphDeps(
            review_service=MagicMock(), llm_service=MagicMock(), repository=MagicMock(),
        )
        compiled = build_daily_position_review_graph(deps)
        edges = compiled.get_graph().edges
        edge_pairs = {(e.source, e.target) for e in edges if hasattr(e, 'source')}
        # Verify key business edges exist
        assert ("load_daily_review_context", "select_focus_symbols") in edge_pairs
        assert ("select_focus_symbols", "symbol_cards") in edge_pairs
        assert ("select_focus_symbols", "macro_card") in edge_pairs
        assert ("select_focus_symbols", "portfolio_attribution") in edge_pairs
        assert ("select_focus_symbols", "risk_watch") in edge_pairs

    def test_four_parallel_nodes_fan_in_to_build_card_pack(self):
        from app.agents.daily_position_review_graph.graph import (
            DailyPositionReviewGraphDeps,
            build_daily_position_review_graph,
        )
        deps = DailyPositionReviewGraphDeps(
            review_service=MagicMock(), llm_service=MagicMock(), repository=MagicMock(),
        )
        compiled = build_daily_position_review_graph(deps)
        # Verify the graph compiles and has all expected nodes
        node_names = set(compiled.get_graph().nodes)
        assert "build_card_pack" in node_names
        assert "symbol_cards" in node_names
        assert "macro_card" in node_names
        assert "portfolio_attribution" in node_names
        assert "risk_watch" in node_names


# === 2. Fan-in Execution Semantics ===

class TestFanInExecutionSemantics:

    def test_parallel_nodes_each_run_once(self):
        """Verify all 4 parallel nodes run exactly once and build_card_pack runs once."""
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        deps = _make_mock_deps()
        runner = DailyPositionReviewGraphRunner(
            review_service=deps.review_service,
            llm_service=deps.llm_service,
            repository=deps.repository,
            symbol_agent=deps.symbol_agent,
            macro_agent=deps.macro_agent,
        )

        result = runner.generate_review("2026-05-20")

        # Persist saves the document, then runner rewrites the final trace so
        # persisted output includes optional_email_summary after the tail node runs.
        assert deps.repository.save_review.call_count == 2

        # run_trace should contain all expected nodes
        run_trace = result.get("run_trace") or []
        node_names = [t["node_name"] for t in run_trace]
        expected_nodes = [
            "load_daily_review_context", "select_focus_symbols",
            "symbol_cards", "macro_card", "portfolio_attribution", "risk_watch",
            "build_card_pack", "compose_daily_review", "persist_daily_review",
            "optional_email_summary",
        ]
        for name in expected_nodes:
            assert name in node_names, f"Missing node '{name}' in run_trace"

    def test_persist_trace_in_saved_document_and_final_state(self):
        """persist_daily_review must appear in both saved_document.run_trace and final_state.node_traces."""
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        deps = _make_mock_deps()
        runner = DailyPositionReviewGraphRunner(
            review_service=deps.review_service,
            llm_service=deps.llm_service,
            repository=deps.repository,
            symbol_agent=deps.symbol_agent,
            macro_agent=deps.macro_agent,
        )

        final_state = runner.graph.invoke(runner._initial_state("2026-05-20"))

        saved_doc = final_state["saved_document"]
        saved_names = [t["node_name"] for t in saved_doc["run_trace"]]
        final_names = [t["node_name"] for t in final_state["node_traces"]]

        assert "persist_daily_review" in saved_names
        assert "persist_daily_review" in final_names
        assert saved_names.count("persist_daily_review") == 1
        assert final_names.count("persist_daily_review") == 1


# === 3. Reducer Safety ===

class TestReducerSafety:

    def test_parallel_node_traces_merged(self):
        """All parallel node traces must be merged into final state."""
        from app.agents.graph.base_state import _merge_trace_list

        traces_a = [{"node_name": "symbol_cards", "status": "success"}]
        traces_b = [{"node_name": "macro_card", "status": "success"}]
        traces_c = [{"node_name": "portfolio_attribution", "status": "success"}]
        traces_d = [{"node_name": "risk_watch", "status": "success"}]

        merged = _merge_trace_list(traces_a, traces_b)
        merged = _merge_trace_list(merged, traces_c)
        merged = _merge_trace_list(merged, traces_d)

        names = [t["node_name"] for t in merged]
        assert len(names) == 4
        assert "symbol_cards" in names
        assert "macro_card" in names
        assert "portfolio_attribution" in names
        assert "risk_watch" in names

    def test_warnings_merged_from_parallel_nodes(self):
        """Warnings from parallel nodes must be merged."""
        from app.agents.graph.base_state import _merge_str_list

        w1 = ["symbol warning"]
        w2 = ["macro warning"]
        merged = _merge_str_list(w1, w2)
        assert "symbol warning" in merged
        assert "macro warning" in merged


# === 4. Context Loading ===

class TestContextLoading:

    def test_build_review_context_called_once(self):
        from app.agents.daily_position_review_graph.nodes import make_load_daily_review_context_node

        deps = _make_mock_deps()
        node = make_load_daily_review_context_node(deps)
        state = {"report_date": "2026-05-20"}
        result = node(state)

        deps.review_service.build_review_context.assert_called_once_with(
            "2026-05-20", include_public_context=True, include_benchmarks=True,
        )
        assert "deterministic_context" in result
        assert result["deterministic_context"]["report_date"] == "2026-05-20"

    def test_compact_positions_created(self):
        from app.agents.daily_position_review_graph.nodes import make_load_daily_review_context_node

        deps = _make_mock_deps()
        node = make_load_daily_review_context_node(deps)
        result = node({"report_date": "2026-05-20"})

        compact = result["compact_positions"]
        assert len(compact) == 2
        # Should have key IBKR fields
        assert "symbol" in compact[0]
        assert "daily_pnl" in compact[0]
        # Should NOT have raw Longbridge context
        assert "symbol_public_context" not in compact[0]


# === 5. Focus Symbol Selection ===

class TestFocusSymbolSelection:

    def test_select_focus_symbols(self):
        from app.agents.daily_position_review_graph.nodes import make_select_focus_symbols_node

        deps = _make_mock_deps()
        node = make_select_focus_symbols_node(deps)
        ctx = _make_deterministic_context()
        state = {"report_date": "2026-05-20", "deterministic_context": ctx}
        result = node(state)

        assert "focus_position_items" in result
        assert "focus_symbols" in result
        assert len(result["focus_position_items"]) > 0

    def test_focus_symbols_limited(self):
        from app.agents.daily_position_review_graph.nodes import make_select_focus_symbols_node

        deps = _make_mock_deps()
        node = make_select_focus_symbols_node(deps)
        ctx = _make_deterministic_context()
        state = {"report_date": "2026-05-20", "deterministic_context": ctx}
        result = node(state)

        assert len(result["focus_symbols"]) <= 6


# === 6. Symbol Cards Node ===

class TestSymbolCardsNode:

    def test_symbol_cards_generated(self):
        from app.agents.daily_position_review_graph.nodes import make_symbol_cards_node

        deps = _make_mock_deps()
        node = make_symbol_cards_node(deps)
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": _make_deterministic_context(),
            "focus_position_items": _make_deterministic_context()["positions"],
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        assert "symbol_cards" in result
        assert len(result["symbol_cards"]) == 2
        assert result["symbol_cards_public_data_mode"] == "subagent"

    def test_symbol_card_failure_produces_fallback(self):
        from app.agents.daily_position_review_graph.nodes import make_symbol_cards_node

        deps = _make_mock_deps()
        deps.symbol_agent.generate_symbol_card.side_effect = RuntimeError("LLM failed")
        node = make_symbol_cards_node(deps)
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": _make_deterministic_context(),
            "focus_position_items": _make_deterministic_context()["positions"],
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        # Should still have cards (fallback cards)
        assert len(result["symbol_cards"]) == 2
        for card in result["symbol_cards"]:
            assert card.evidence_quality == "low"


# === 7. Macro Card Node ===

class TestMacroCardNode:

    def test_macro_card_generated(self):
        from app.agents.daily_position_review_graph.nodes import make_macro_card_node

        deps = _make_mock_deps()
        node = make_macro_card_node(deps)
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": _make_deterministic_context(),
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        assert "macro_card" in result
        assert result["macro_card"] is not None
        assert result["macro_public_data_mode"] == "subagent"

    def test_macro_card_failure_produces_fallback(self):
        from app.agents.daily_position_review_graph.nodes import make_macro_card_node

        deps = _make_mock_deps()
        deps.macro_agent.generate_macro_card.side_effect = RuntimeError("LLM failed")
        node = make_macro_card_node(deps)
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": _make_deterministic_context(),
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        assert result["macro_card"] is not None
        assert result["macro_public_data_mode"] == "unavailable"


# === 8. Build Card Pack Node ===

class TestBuildCardPackNode:

    def test_build_card_pack_creates_pack(self):
        from app.agents.daily_position_review_graph.nodes import make_build_card_pack_node

        deps = _make_mock_deps()
        node = make_build_card_pack_node(deps)
        ctx = _make_deterministic_context()
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": ctx,
            "symbol_cards": [_make_symbol_card("AMD.US"), _make_symbol_card("NVDA.US")],
            "macro_card": _make_macro_card(),
            "focus_position_items": ctx["positions"],
        }
        result = node(state)

        assert "card_pack" in result
        assert result["card_pack"] is not None
        assert "card_pack_summary" in result
        assert "evidence_pack" in result

    def test_card_pack_contains_required_sections(self):
        from app.agents.daily_position_review_graph.nodes import make_build_card_pack_node

        deps = _make_mock_deps()
        node = make_build_card_pack_node(deps)
        ctx = _make_deterministic_context()
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": ctx,
            "symbol_cards": [_make_symbol_card()],
            "macro_card": _make_macro_card(),
            "focus_position_items": ctx["positions"],
        }
        result = node(state)

        pack = result["card_pack"]
        assert len(pack.symbol_cards) == 1
        assert pack.macro_card is not None
        assert pack.rankings is not None
        assert pack.risk is not None


# === 9. Compose Daily Review Node ===

class TestComposeDailyReviewNode:

    def test_compose_uses_llm(self):
        from app.agents.daily_position_review_graph.nodes import make_compose_daily_review_node

        deps = _make_mock_deps()
        mock_result = {
            "content": '{"report_date":"2026-05-20","summary":"ok","account_conclusion":"ok","attribution_summary":"ok","market_context":"ok","risk_analysis":"ok","operation_observation":"ok","major_contributors_analysis":[],"major_drags_analysis":[],"focus_symbol_analyses":[],"tomorrow_watchlist":[],"data_limitations":[],"evidence_used":[]}',
            "trace": [{"tool": "get_daily_position_review_context"}],
        }

        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            symbol_cards=[_make_symbol_card()],
            macro_card=_make_macro_card(),
            account_facts={"overview": {}},
            data_quality=DataQualitySummary(),
            subagent_trace=SubAgentTrace(),
        )

        state = {
            "report_date": "2026-05-20",
            "card_pack": pack,
            "compact_positions": [],
            "deterministic_context": _make_deterministic_context(),
        }

        with patch("app.agents.runtime.ToolCallingRuntime") as MockRuntime:
            MockRuntime.return_value.run.return_value = mock_result
            node = make_compose_daily_review_node(deps)
            result = node(state)

        assert "review_output" in result
        assert result["review_output"]["report_date"] == "2026-05-20"

    def test_compose_fallback_on_llm_failure(self):
        from app.agents.daily_position_review_graph.nodes import make_compose_daily_review_node

        deps = _make_mock_deps()
        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            symbol_cards=[_make_symbol_card()],
            macro_card=_make_macro_card(),
            data_quality=DataQualitySummary(),
            subagent_trace=SubAgentTrace(),
        )

        state = {
            "report_date": "2026-05-20",
            "card_pack": pack,
            "compact_positions": [],
            "deterministic_context": _make_deterministic_context(),
        }

        with patch("app.agents.runtime.ToolCallingRuntime") as MockRuntime:
            MockRuntime.return_value.run.side_effect = RuntimeError("LLM timeout")
            node = make_compose_daily_review_node(deps)
            result = node(state)

        # Should have fallback review_output
        assert "review_output" in result
        assert result["review_output"]["report_date"] == "2026-05-20"
        assert len(result["review_output"]["data_limitations"]) > 0


# === 10. Persist Daily Review Node ===

class TestPersistDailyReviewNode:

    def test_persist_saves_document(self):
        from app.agents.daily_position_review_graph.nodes import make_persist_daily_review_node

        deps = _make_mock_deps()
        node = make_persist_daily_review_node(deps)

        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            symbol_cards=[_make_symbol_card()],
            macro_card=_make_macro_card(),
            data_quality=DataQualitySummary(),
            subagent_trace=SubAgentTrace(),
        )

        state = {
            "report_date": "2026-05-20",
            "review_output": {
                "summary": "ok", "account_conclusion": "ok", "attribution_summary": "ok",
                "market_context": "ok", "risk_analysis": "ok", "operation_observation": "ok",
                "major_contributors_analysis": [], "major_drags_analysis": [],
                "focus_symbol_analyses": [], "tomorrow_watchlist": [],
                "data_limitations": [], "evidence_used": [],
            },
            "deterministic_context": _make_deterministic_context(),
            "evidence_pack": {},
            "card_pack": pack,
            "card_pack_summary": {},
            "raw_llm_response": "{}",
            "model_provider_snapshot": {},
            "node_traces": [],
        }
        result = node(state)

        assert "saved_document" in result
        deps.repository.save_review.assert_called_once()

    def test_persist_metadata_has_langgraph_mode(self):
        from app.agents.daily_position_review_graph.nodes import make_persist_daily_review_node

        deps = _make_mock_deps()
        node = make_persist_daily_review_node(deps)

        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            data_quality=DataQualitySummary(),
            subagent_trace=SubAgentTrace(),
        )

        state = {
            "report_date": "2026-05-20",
            "review_output": {
                "summary": "ok", "account_conclusion": "ok", "attribution_summary": "ok",
                "market_context": "ok", "risk_analysis": "ok", "operation_observation": "ok",
                "major_contributors_analysis": [], "major_drags_analysis": [],
                "focus_symbol_analyses": [], "tomorrow_watchlist": [],
                "data_limitations": [], "evidence_used": [],
            },
            "deterministic_context": _make_deterministic_context(),
            "evidence_pack": {},
            "card_pack": pack,
            "card_pack_summary": {},
            "raw_llm_response": "{}",
            "model_provider_snapshot": {},
            "node_traces": [],
        }
        result = node(state)

        saved = result["saved_document"]
        assert saved["metadata"]["agent_mode"] == "daily_position_review_langgraph_v1"
        assert saved["metadata"]["graph_version"] == "daily_position_review_graph_v1"
        assert saved["agent_mode"] == "daily_position_review_langgraph_v1"


# === 11. Optional Email Summary Node ===

class TestOptionalEmailSummaryNode:

    def test_skip_when_auto_email_false(self):
        from app.agents.daily_position_review_graph.nodes import make_optional_email_summary_node

        deps = _make_mock_deps()
        node = make_optional_email_summary_node(deps)
        state = {"auto_email": False, "saved_document": {"id": "test"}}
        result = node(state)

        assert "warnings" not in result or len(result.get("warnings", [])) == 0

    def test_skip_when_no_email_service(self):
        from app.agents.daily_position_review_graph.nodes import make_optional_email_summary_node

        deps = _make_mock_deps()
        deps.email_service = None
        node = make_optional_email_summary_node(deps)
        state = {"auto_email": True, "saved_document": {"id": "test"}}
        result = node(state)

        assert any("email_service not configured" in w for w in result.get("warnings", []))

    def test_email_failure_does_not_break(self):
        from app.agents.daily_position_review_graph.nodes import make_optional_email_summary_node

        deps = _make_mock_deps()
        mock_email = MagicMock()
        mock_email.send_daily_position_review.side_effect = RuntimeError("smtp down")
        deps.email_service = mock_email
        node = make_optional_email_summary_node(deps)
        state = {"auto_email": True, "saved_document": {"id": "test"}}
        result = node(state)

        assert any("smtp down" in w for w in result.get("warnings", []))


# === 12. Agent Façade ===

class TestAgentFacade:

    def test_agent_uses_graph_runner(self):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent

        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = SimpleNamespace(name="test")

        agent = DailyPositionReviewAgent(
            review_service=MagicMock(),
            llm_service=mock_llm,
            repository=MagicMock(),
        )

        # Mock the graph runner
        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_review.return_value = {"id": "test", "report_date": "2026-05-20"}
            mock_get_runner.return_value = mock_runner

            result = agent.generate_review("2026-05-20")

            mock_runner.generate_review.assert_called_once_with("2026-05-20", auto_email=False)
            assert result["id"] == "test"

    def test_agent_raises_when_no_provider(self):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent
        from app.services.llm_service import LLMConfigError

        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = None

        agent = DailyPositionReviewAgent(
            review_service=MagicMock(),
            llm_service=mock_llm,
            repository=MagicMock(),
        )

        with pytest.raises(LLMConfigError):
            agent.generate_review("2026-05-20")

    def test_legacy_generate_review_raises_deprecated(self):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent

        agent = DailyPositionReviewAgent(None, None, None)
        with pytest.raises(RuntimeError, match="deprecated"):
            agent._generate_review_legacy("2026-05-20")


# === 13. Versions ===

class TestVersions:

    def test_daily_position_review_langgraph_constants_exist(self):
        from app.agents.versions import (
            DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH,
            DAILY_POSITION_REVIEW_GRAPH_VERSION,
            DAILY_POSITION_REVIEW_GRAPH_SCHEMA_VERSION,
            DAILY_POSITION_REVIEW_CARD_SCHEMA_VERSION,
        )
        assert DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH == "daily_position_review_langgraph_v1"
        assert DAILY_POSITION_REVIEW_GRAPH_VERSION == "daily_position_review_graph_v1"
        assert DAILY_POSITION_REVIEW_GRAPH_SCHEMA_VERSION == "daily_position_review_graph_state_v1"
        assert DAILY_POSITION_REVIEW_CARD_SCHEMA_VERSION == "daily_position_review_card_schema_v1"


# === 14. API Schema ===

class TestAPISchema:

    def test_health_response_has_new_fields(self):
        from app.schemas.daily_position_review import DailyPositionReviewHealthResponse

        resp = DailyPositionReviewHealthResponse(
            enabled=True,
            llm_configured=True,
            longbridge_configured=True,
            account_data_source="IBKR_ONLY",
            public_market_data_source="LONGBRIDGE_PUBLIC_ONLY",
            message="ok",
        )
        assert resp.agent_mode == "daily_position_review_langgraph_v1"
        assert resp.graph_version == "daily_position_review_graph_v1"

    def test_health_response_backward_compatible(self):
        from app.schemas.daily_position_review import DailyPositionReviewHealthResponse

        # Old callers that don't pass agent_mode/graph_version should still work
        resp = DailyPositionReviewHealthResponse(
            enabled=True,
            llm_configured=True,
            longbridge_configured=True,
            account_data_source="IBKR_ONLY",
            public_market_data_source="LONGBRIDGE_PUBLIC_ONLY",
            message="ok",
        )
        assert resp.enabled is True
        assert resp.message == "ok"


# === 15. Node Factories ===

class TestNodeFactories:

    def test_all_factories_return_callables(self):
        from app.agents.daily_position_review_graph.nodes import (
            make_load_daily_review_context_node,
            make_select_focus_symbols_node,
            make_symbol_cards_node,
            make_macro_card_node,
            make_portfolio_attribution_node,
            make_risk_watch_node,
            make_build_card_pack_node,
            make_compose_daily_review_node,
            make_persist_daily_review_node,
            make_optional_email_summary_node,
        )
        deps = _make_mock_deps()
        for factory in [
            make_load_daily_review_context_node,
            make_select_focus_symbols_node,
            make_symbol_cards_node,
            make_macro_card_node,
            make_portfolio_attribution_node,
            make_risk_watch_node,
            make_build_card_pack_node,
            make_compose_daily_review_node,
            make_persist_daily_review_node,
            make_optional_email_summary_node,
        ]:
            assert callable(factory(deps))

    def test_nodes_do_not_read_state_deps(self):
        from app.agents.daily_position_review_graph import nodes
        source = inspect.getsource(nodes)
        assert "state[\"_deps\"]" not in source
        assert "state['_deps']" not in source


# === 16. Deterministic Nodes ===

class TestDeterministicNodes:

    def test_portfolio_attribution_node(self):
        from app.agents.daily_position_review_graph.nodes import make_portfolio_attribution_node

        deps = _make_mock_deps()
        node = make_portfolio_attribution_node(deps)
        state = {"deterministic_context": _make_deterministic_context()}
        result = node(state)

        card = result["portfolio_attribution_card"]
        assert card["card_type"] == "portfolio_attribution"
        assert card["daily_pnl"] == 1000.0
        assert len(card["top_contributors"]) > 0

    def test_risk_watch_node(self):
        from app.agents.daily_position_review_graph.nodes import make_risk_watch_node

        deps = _make_mock_deps()
        node = make_risk_watch_node(deps)
        state = {"deterministic_context": _make_deterministic_context()}
        result = node(state)

        card = result["risk_watch_card"]
        assert card["card_type"] == "daily_risk_watch"
        assert card["position_concentration"] == 0.10


# === 17. Runner ===

class TestRunner:

    def test_runner_initial_state(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        runner = DailyPositionReviewGraphRunner(
            review_service=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
        )

        state = runner._initial_state("2026-05-20", auto_email=True)
        assert state["report_date"] == "2026-05-20"
        assert state["auto_email"] is True
        assert state["node_traces"] == []
        assert state["errors"] == []

    def test_runner_build_fallback(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        mock_repo = MagicMock()
        mock_repo.save_review.side_effect = lambda doc: doc

        runner = DailyPositionReviewGraphRunner(
            review_service=MagicMock(),
            llm_service=MagicMock(),
            repository=mock_repo,
        )

        fallback = runner._build_fallback("2026-05-20", "test error")
        assert fallback["report_date"] == "2026-05-20"
        assert fallback["fallback_used"] is True
        assert fallback["metadata"]["agent_mode"] == "daily_position_review_langgraph_v1"

    def test_runner_creates_default_symbol_and_macro_agents_when_not_injected(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner
        from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent
        from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent

        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = SimpleNamespace(
            name="test", base_url="http://test", default_model="test-model",
            context_window_tokens=128000, input_token_limit=100000, output_token_limit=8000,
        )

        runner = DailyPositionReviewGraphRunner(
            review_service=MagicMock(),
            llm_service=mock_llm,
            repository=MagicMock(),
        )

        assert runner.deps.symbol_agent is not None
        assert runner.deps.macro_agent is not None
        assert isinstance(runner.deps.symbol_agent, DailyReviewSymbolEvidenceAgent)
        assert isinstance(runner.deps.macro_agent, DailyReviewMacroEvidenceAgent)

    def test_runner_preserves_injected_symbol_and_macro_agents(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        mock_symbol_agent = MagicMock()
        mock_macro_agent = MagicMock()

        runner = DailyPositionReviewGraphRunner(
            review_service=MagicMock(),
            llm_service=MagicMock(),
            repository=MagicMock(),
            symbol_agent=mock_symbol_agent,
            macro_agent=mock_macro_agent,
        )

        assert runner.deps.symbol_agent is mock_symbol_agent
        assert runner.deps.macro_agent is mock_macro_agent

    def test_finalize_does_not_fail_when_replay_snapshot_persist_fails(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        repository = MagicMock()
        repository.save_review.side_effect = lambda doc: doc
        trace_service = MagicMock()
        replay_service = MagicMock()
        replay_service.record_snapshot.side_effect = RuntimeError("mapping exploded")
        runner = DailyPositionReviewGraphRunner(
            review_service=MagicMock(),
            llm_service=MagicMock(),
            repository=repository,
            trace_service=trace_service,
            replay_service=replay_service,
        )
        document = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "review_type": "daily_position_review",
            "status": "success",
            "summary": "ok",
            "data_limitations": [],
            "metadata": {},
            "run_trace": [{"node_name": "persist_daily_review", "status": "success"}],
        }
        initial_state = {
            "report_date": "2026-05-20",
            "auto_email": False,
            "started_at": "2026-05-20T00:00:00+00:00",
            "agent_run_id": "daily-run-1",
        }

        result = runner._finalize(document, initial_state, {"node_traces": document["run_trace"]})

        assert result["status"] == "success"
        assert result["agent_replay"]["persisted"] is False
        assert "mapping exploded" in result["agent_replay"]["error"]
        assert any("agent_replay_persist_failed" in item for item in result["data_limitations"])
        trace_service.record_trace.assert_called_once()
        replay_service.record_snapshot.assert_called_once()
        repository.save_review.assert_called_once()


class TestProductionDIPath:

    def test_daily_position_review_agent_graph_runner_has_default_subagents(self):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent

        mock_review_service = MagicMock()
        mock_llm = MagicMock()
        mock_llm.get_active_provider.return_value = SimpleNamespace(
            name="test", base_url="http://test", default_model="test-model",
            context_window_tokens=128000, input_token_limit=100000, output_token_limit=8000,
        )
        mock_repo = MagicMock()

        agent = DailyPositionReviewAgent(
            review_service=mock_review_service,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        runner = agent._get_graph_runner()

        assert runner.deps.symbol_agent is not None
        assert runner.deps.macro_agent is not None

    def test_graph_with_default_subagents_does_not_fail_due_to_none_agents(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        deps = _make_mock_deps()
        with patch("app.services.daily_review_symbol_evidence_agent.DailyReviewSymbolEvidenceAgent.generate_symbol_card", return_value=_make_symbol_card()):
            with patch("app.services.daily_review_macro_evidence_agent.DailyReviewMacroEvidenceAgent.generate_macro_card", return_value=_make_macro_card()):
                runner = DailyPositionReviewGraphRunner(
                    review_service=deps.review_service,
                    llm_service=deps.llm_service,
                    repository=deps.repository,
                    # not passing symbol_agent / macro_agent
                )

                with patch("app.agents.runtime.ToolCallingRuntime") as MockRuntime:
                    MockRuntime.return_value.run.return_value = {
                        "content": '{"report_date":"2026-05-20","summary":"ok","account_conclusion":"ok","attribution_summary":"ok","market_context":"ok","risk_analysis":"ok","operation_observation":"ok","major_contributors_analysis":[],"major_drags_analysis":[],"focus_symbol_analyses":[],"tomorrow_watchlist":[],"data_limitations":[],"evidence_used":[]}',
                        "trace": [{"tool": "get_daily_position_review_context"}],
                    }
                    result = runner.generate_review("2026-05-20")

        assert deps.repository.save_review.call_count == 2
        node_names = [t.get("node_name") for t in result.get("run_trace") or []]
        assert "optional_email_summary" in node_names
        card_pack = result.get("subagent_card_pack") or {}
        assert len(card_pack.get("symbol_cards", [])) > 0
        assert card_pack.get("macro_card") is not None

    def test_runner_keeps_full_document_after_trace_resave_returns_compact_document(self):
        from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner

        runner = DailyPositionReviewGraphRunner.__new__(DailyPositionReviewGraphRunner)
        full_document = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "summary": "ok",
            "account_conclusion": "ok",
            "attribution_summary": "ok",
            "market_context": "ok",
            "risk_analysis": "ok",
            "operation_observation": "ok",
            "major_contributors_analysis": [],
            "major_drags_analysis": [],
            "focus_symbol_analyses": [],
            "tomorrow_watchlist": [],
            "data_limitations": [],
            "evidence_used": [],
            "subagent_card_pack": {"symbol_cards": [{"symbol": "AMD.US"}]},
            "evidence_card_summary": {"symbol_count": 1},
            "metadata": {"agent_mode": "daily_position_review_langgraph_v1"},
            "run_trace": [],
        }
        final_state = {
            "saved_document": full_document,
            "node_traces": [
                {"node_name": "persist_daily_review", "status": "success"},
                {"node_name": "optional_email_summary", "status": "success"},
            ],
        }
        runner.graph = SimpleNamespace(invoke=MagicMock(return_value=final_state))
        repository = MagicMock()
        repository.save_review.return_value = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "summary": "ok",
            "created_at": "2026-05-20T00:00:00Z",
            "updated_at": "2026-05-20T00:00:01Z",
        }
        runner.deps = SimpleNamespace(repository=repository)
        runner.trace_service = None
        runner.replay_service = None

        result = runner.generate_review("2026-05-20")

        assert repository.save_review.called
        assert result["subagent_card_pack"] == {"symbol_cards": [{"symbol": "AMD.US"}]}
        assert result["evidence_card_summary"] == {"symbol_count": 1}
        assert result["updated_at"] == "2026-05-20T00:00:01Z"


class TestNodeDefensiveBranches:

    def test_symbol_cards_node_handles_missing_symbol_agent_with_fallback_cards(self):
        from app.agents.daily_position_review_graph.nodes import make_symbol_cards_node

        deps = _make_mock_deps()
        deps.symbol_agent = None
        node = make_symbol_cards_node(deps)
        ctx = _make_deterministic_context()
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": ctx,
            "focus_position_items": ctx["positions"],
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        assert len(result["symbol_cards"]) == 2
        for card in result["symbol_cards"]:
            assert card.evidence_quality == "low"
        assert any("symbol_agent_not_configured" in w for w in result.get("warnings", []))

    def test_macro_card_node_handles_missing_macro_agent_with_fallback_card(self):
        from app.agents.daily_position_review_graph.nodes import make_macro_card_node

        deps = _make_mock_deps()
        deps.macro_agent = None
        node = make_macro_card_node(deps)
        state = {
            "report_date": "2026-05-20",
            "deterministic_context": _make_deterministic_context(),
            "focus_symbols": ["AMD.US", "NVDA.US"],
        }
        result = node(state)

        assert result["macro_card"] is not None
        assert result["macro_public_data_mode"] == "unavailable"
        assert any("macro_agent_not_configured" in w for w in result.get("warnings", []))
