import json
from types import SimpleNamespace

from app.agents.trade_decision_cards import DebateJudgeCard
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.trade_decision_graph.graph import TradeDecisionGraphDeps
from app.agents.trade_decision_graph.nodes import make_event_catalyst_node, make_fundamental_valuation_node, make_market_trend_node
from app.agents.daily_position_review_graph.graph import DailyPositionReviewGraphDeps
from app.agents.daily_position_review_graph.nodes import make_compose_daily_review_node
from app.agents.trade_review_graph.graph import TradeReviewGraphDeps
from app.agents.trade_review_graph.nodes import (
    make_behavior_pattern_node,
    make_compose_trade_review_node,
    make_opportunity_cost_node,
)
from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent
from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent
from app.services.trade_decision_sub_agents import MARKET_TREND_SYSTEM_PROMPT, MarketTrendSubAgent
from app.services.trade_decision_debate_agents import BullThesisAgent
from app.services.trade_decision_trade_plan_agent import TradeDecisionTradePlanAgent
from tests.test_account_copilot_react_runtime import FakeLLMService, action, base_state, make_registry
from tests.test_trade_decision_langgraph import _make_card_pack


class FakePromptService:
    def __init__(self, prompts: dict[str, str] | None = None, fail: bool = False) -> None:
        self.prompts = prompts or {}
        self.fail = fail

    def get_runtime_prompt(self, prompt_key: str, fallback: str | None = None) -> dict:
        if self.fail:
            raise RuntimeError("prompt store down")
        content = self.prompts.get(prompt_key) or fallback or ""
        return {
            "content": content,
            "metadata": {
                "prompt_key": prompt_key,
                "version": "v9" if prompt_key in self.prompts else None,
                "content_hash": f"hash-{prompt_key}",
                "source": "admin_active" if prompt_key in self.prompts else "code_default",
            },
        }


class CaptureLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.response


def test_resolve_runtime_prompt_fallbacks_and_active() -> None:
    content, metadata = resolve_runtime_prompt(None, "k", "DEFAULT")
    assert content == "DEFAULT"
    assert metadata["source"] == "fallback"

    content, metadata = resolve_runtime_prompt(FakePromptService(fail=True), "k", "DEFAULT")
    assert content == "DEFAULT"
    assert metadata["source"] == "fallback"
    assert "prompt store down" in metadata["error"]

    content, metadata = resolve_runtime_prompt(FakePromptService({"k": "ACTIVE"}), "k", "DEFAULT")
    assert content == "ACTIVE"
    assert metadata["source"] == "admin_active"
    assert metadata["version"] == "v9"


def test_account_copilot_planner_uses_custom_prompt() -> None:
    llm = FakeLLMService([action("final_answer", final_answer="done")])
    runtime = AccountCopilotRuntime(
        llm,
        make_registry(),
        prompt_service=FakePromptService({"account_copilot_planner": "CUSTOM_ACCOUNT_COPILOT_PROMPT"}),
    )

    result = runtime.run(base_state())

    assert llm.calls[0][0]["content"] == "CUSTOM_ACCOUNT_COPILOT_PROMPT"
    assert result["metadata"]["prompt_metadata"]["account_copilot_planner"]["source"] == "admin_active"


def test_daily_symbol_and_macro_agents_use_custom_prompts() -> None:
    symbol_response = json.dumps(
        {
            "symbol": "AMD",
            "normalized_symbol": "AMD.US",
            "report_date": "2026-05-20",
            "account_impact": {},
            "price_action": {},
            "news_summary": {},
            "valuation_summary": {},
            "earnings_summary": {},
            "technical_summary": {},
            "cross_asset_summary": {},
            "likely_drivers": [],
            "watch_points": [],
            "evidence_quality": "low",
            "data_limitations": [],
            "source_trace": [],
        }
    )
    macro_response = json.dumps(
        {
            "report_date": "2026-05-20",
            "benchmark_context": {},
            "market_regime": "mixed",
            "sector_context": "",
            "macro_events": [],
            "rate_fx_context": "",
            "risk_sentiment": "neutral",
            "tech_sentiment": "neutral",
            "data_limitations": [],
            "source_trace": [],
        }
    )
    symbol_llm = CaptureLLM(symbol_response)
    macro_llm = CaptureLLM(macro_response)

    DailyReviewSymbolEvidenceAgent(
        symbol_llm,
        prompt_service=FakePromptService({"daily_symbol_evidence_card": "CUSTOM_SYMBOL_PROMPT"}),
    ).generate_symbol_card("2026-05-20", "AMD", "AMD.US", {}, {}, {})
    DailyReviewMacroEvidenceAgent(
        macro_llm,
        prompt_service=FakePromptService({"daily_macro_evidence_card": "CUSTOM_MACRO_PROMPT"}),
    ).generate_macro_card("2026-05-20", {}, [], None)

    assert symbol_llm.calls[0]["messages"][0]["content"] == "CUSTOM_SYMBOL_PROMPT"
    assert macro_llm.calls[0]["messages"][0]["content"] == "CUSTOM_MACRO_PROMPT"


def test_daily_compose_node_uses_custom_main_prompt(monkeypatch) -> None:
    captured = []

    class FakeAgentHelper:
        def __init__(self, llm_service):
            pass

        def build_tool_user_prompt_subagent_cards(self, report_date, card_pack, compact_positions):
            return "user"

        def build_tools_subagent_cards(self, card_pack, compact_positions, report_date):
            return []

    class FakeRuntime:
        def __init__(self, llm_service, **kwargs):
            pass

        def run(self, messages, **kwargs):
            captured.append(messages[0]["content"])
            return {"content": "{}", "trace": []}

    monkeypatch.setattr("app.agents.daily_position_review_graph.nodes._AgentHelper", FakeAgentHelper)
    monkeypatch.setattr("app.agents.runtime.ToolCallingRuntime", FakeRuntime)
    monkeypatch.setattr(
        "app.agents.daily_position_review_graph.nodes._validate_or_repair_llm_response",
        lambda **kwargs: ({"summary": "ok"}, "{}", None),
    )
    deps = DailyPositionReviewGraphDeps(
        review_service=None,
        llm_service=None,
        repository=None,
        prompt_service=FakePromptService({"daily_position_review_main": "CUSTOM_DAILY_MAIN_PROMPT"}),
    )

    result = make_compose_daily_review_node(deps)(
        {
            "report_date": "2026-05-20",
            "card_pack": object(),
            "compact_positions": [],
            "deterministic_context": {},
        }
    )

    assert captured == ["CUSTOM_DAILY_MAIN_PROMPT"]
    assert result["prompt_metadata"]["daily_position_review_main"]["source"] == "admin_active"


def test_trade_decision_subagent_prompt_resolution() -> None:
    agent = MarketTrendSubAgent(None, None, prompt_service=FakePromptService({"trade_decision_market_trend": "CUSTOM_MARKET_PROMPT"}))
    assert agent._build_system_prompt() == "CUSTOM_MARKET_PROMPT"
    assert agent._last_prompt_metadata["source"] == "admin_active"

    failing = MarketTrendSubAgent(None, None, prompt_service=FakePromptService(fail=True))
    assert failing._build_system_prompt() == MARKET_TREND_SYSTEM_PROMPT
    assert failing._last_prompt_metadata["source"] == "fallback"
    assert failing._last_prompt_metadata["error"]


def test_trade_review_nodes_use_custom_prompts(monkeypatch) -> None:
    captured = []

    class FakeRuntime:
        def __init__(self, llm_service, **kwargs):
            pass

        def run(self, messages, **kwargs):
            captured.append(messages[0]["content"])
            return {"content": "{}", "trace": []}

    monkeypatch.setattr("app.agents.trade_review_graph.nodes.ToolCallingRuntime", FakeRuntime)
    monkeypatch.setattr("app.agents.trade_review_graph.nodes.extract_json_object", lambda raw: {})
    monkeypatch.setattr("app.agents.trade_review_graph.nodes._validate_review_output", lambda parsed, context: {"summary": "ok"})

    deps = TradeReviewGraphDeps(
        evidence_builder=None,
        llm_service=None,
        repository=None,
        prompt_service=FakePromptService(
            {
                "trade_review_behavior_pattern": "CUSTOM_BEHAVIOR_PROMPT",
                "trade_review_opportunity_cost": "CUSTOM_OPPORTUNITY_PROMPT",
                "trade_review_main": "CUSTOM_TRADE_REVIEW_PROMPT",
            }
        ),
    )
    state = {"merged_review_context": {}, "review_type": "symbol_level_review", "symbol": "AMD.US", "node_traces": []}
    state.update(make_behavior_pattern_node(deps)(state))
    state.update(make_opportunity_cost_node(deps)(state))
    state.update(make_compose_trade_review_node(deps)(state))

    assert captured == ["CUSTOM_BEHAVIOR_PROMPT", "CUSTOM_OPPORTUNITY_PROMPT", "CUSTOM_TRADE_REVIEW_PROMPT"]
    assert state["prompt_metadata"]["trade_review_main"]["source"] == "admin_active"


def test_trade_decision_graph_nodes_pass_prompt_service(monkeypatch) -> None:
    seen = []

    def fake_generate(self, snapshot):
        seen.append(self._build_system_prompt())
        from app.agents.trade_decision_cards import TradeDecisionSubAgentTrace, build_fallback_market_trend_card

        trace = TradeDecisionSubAgentTrace(sub_agent_name=self._sub_agent_name(), status="fallback", prompt_metadata=self._last_prompt_metadata)
        return build_fallback_market_trend_card(snapshot.symbol, snapshot.decision_type, "test"), trace

    monkeypatch.setattr("app.services.trade_decision_sub_agents.MCPSubAgent.generate", fake_generate)
    deps = TradeDecisionGraphDeps(
        account_facts_builder=None,
        llm_service=None,
        repository=None,
        mcp_adapter=None,
        prompt_service=FakePromptService(
            {
                "trade_decision_market_trend": "CUSTOM_MARKET",
                "trade_decision_fundamental_valuation": "CUSTOM_FUND",
                "trade_decision_event_catalyst": "CUSTOM_EVENT",
            }
        ),
    )
    state = {
        "account_fact_snapshot": {
            "decision_type": "entry_decision",
            "symbol": "AMD.US",
            "normalized_symbol": "AMD.US",
            "user_question": None,
            "net_liquidation": None,
            "cash": None,
            "deployable_liquidity": None,
            "deployable_liquidity_ratio": None,
            "total_position_value": None,
            "top_positions": [],
            "position_concentration": None,
            "risk_concentration": None,
            "margin_info": None,
            "is_holding": False,
            "quantity": None,
            "avg_cost": None,
            "current_price": None,
            "market_value": None,
            "position_pct": None,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
            "realized_pnl": None,
            "recent_trades": [],
            "first_buy_date": None,
            "last_trade_date": None,
            "holding_days": None,
            "latest_review": None,
            "global_mistake_tags": [],
        },
        "symbol": "AMD.US",
        "decision_type": "entry_decision",
        "node_traces": [],
    }

    market = make_market_trend_node(deps)(state)
    fund = make_fundamental_valuation_node(deps)(state)
    event = make_event_catalyst_node(deps)(state)

    assert seen == ["CUSTOM_MARKET", "CUSTOM_FUND", "CUSTOM_EVENT"]
    assert market["market_trend_prompt_metadata"]["source"] == "admin_active"
    assert fund["fundamental_valuation_prompt_metadata"]["source"] == "admin_active"
    assert event["event_catalyst_prompt_metadata"]["source"] == "admin_active"


def test_trade_decision_debate_and_trade_plan_use_custom_prompts() -> None:
    prompt_service = FakePromptService(
        {
            "trade_decision_bull_thesis": "CUSTOM_BULL_THESIS_PROMPT",
            "trade_decision_trade_plan": "CUSTOM_TRADE_PLAN_PROMPT",
        }
    )
    card_pack = _make_card_pack()

    bull = BullThesisAgent(None, prompt_service=prompt_service)
    captured_bull_messages = []

    def fake_bull_generate(messages, *args, **kwargs):
        captured_bull_messages.append(messages)
        return SimpleNamespace(
            ok=True,
            payload={
                "agent_name": "bull_thesis",
                "stance": "bullish",
                "conviction": "medium",
                "summary": "custom bull",
                "core_claims": [],
                "evidence_refs": [],
                "weak_points": [],
                "risk_flags": [],
                "data_limitations": [],
            },
            repaired=False,
            repair_attempts=0,
            fallback_used=False,
            error_code=None,
            error_message=None,
            metadata={"contract_name": "trade_decision_bull_thesis"},
            trace=[],
        )

    bull.runtime.generate = fake_bull_generate

    _, bull_trace = bull.generate(card_pack)

    plan = TradeDecisionTradePlanAgent(None, prompt_service=prompt_service)
    captured_messages = []
    plan.runtime.generate = lambda messages, *args, **kwargs: (
        captured_messages.append(messages)
        or SimpleNamespace(
            ok=True,
            payload={
                "asset_stance": "neutral",
                "portfolio_action": "watchlist",
                "action_reason_type": "no_action",
                "target_position_pct": 0,
                "execution_conditions": [],
                "invalidation_conditions": [],
                "recheck_triggers": [],
                "risk_reward_assessment": {},
                "data_limitations": [],
                "summary": "custom plan",
            },
            repaired=False,
            repair_attempts=0,
            fallback_used=False,
            error_code=None,
            error_message=None,
            metadata={"contract_name": "trade_decision_trade_plan", "llm_call_metadata": {}},
            trace=[],
        )
    )
    judge = DebateJudgeCard(
        symbol=card_pack.symbol,
        asset_stance="neutral",
        conviction="low",
        winner="balanced",
        reasoning_summary="balanced",
    )

    _, plan_trace = plan.generate(card_pack, judge)

    assert bull_trace.prompt_metadata["source"] == "admin_active"
    assert bull_trace.prompt_metadata["prompt_key"] == "trade_decision_bull_thesis"
    assert captured_bull_messages[0][0]["content"] == "CUSTOM_BULL_THESIS_PROMPT"
    assert captured_messages[0][0]["content"] == "CUSTOM_TRADE_PLAN_PROMPT"
    assert plan_trace.prompt_metadata["source"] == "admin_active"
    assert plan_trace.prompt_metadata["prompt_key"] == "trade_decision_trade_plan"
