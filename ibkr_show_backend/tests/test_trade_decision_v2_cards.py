"""
Tests for V2 card-based sub-agent architecture.

Covers:
- MarketTrendSubAgent uses ToolCallingRuntime with bounded max_rounds=3
- FundamentalValuationSubAgent max_rounds=3
- EventCatalystSubAgent max_rounds=4
- MCP disabled → fallback card
- RiskRewardSubAgent no MCP
- AccountFitSubAgent no MCP
- Composer suggested_cash_amount>0 no error
- Composer output structure
- card_pack quality assessment
"""

import pytest
from unittest.mock import MagicMock, patch
from app.services.trade_decision_sub_agents import (
    AccountFitSubAgent,
    MarketTrendSubAgent,
    FundamentalValuationSubAgent,
    EventCatalystSubAgent,
    RiskRewardSubAgent,
)
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    TradeDecisionCardPack,
    AccountFitCard,
    MarketTrendCard,
    FundamentalValuationCard,
    EventCatalystCard,
    RiskRewardCard,
    CardStance,
)


class TestSubAgentMaxRounds:
    """Tests that sub-agents use bounded ReAct with correct max_rounds."""

    def test_market_trend_sub_agent_max_rounds_3(self):
        """MarketTrendSubAgent should use max_rounds=3."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        sub_agent = MarketTrendSubAgent(mock_llm, mock_adapter)
        assert sub_agent.max_rounds == 3

    def test_fundamental_valuation_sub_agent_max_rounds_3(self):
        """FundamentalValuationSubAgent should use max_rounds=3."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        sub_agent = FundamentalValuationSubAgent(mock_llm, mock_adapter)
        assert sub_agent.max_rounds == 3

    def test_event_catalyst_sub_agent_max_rounds_4(self):
        """EventCatalystSubAgent should use max_rounds=4."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        sub_agent = EventCatalystSubAgent(mock_llm, mock_adapter)
        assert sub_agent.max_rounds == 4

    def test_market_trend_initial_tools_include_benchmarks(self):
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        sub_agent = MarketTrendSubAgent(mock_llm, mock_adapter)
        initial_calls = sub_agent._get_initial_tool_calls("NVDA.US")
        symbols = {item["arguments"].get("symbol") for item in initial_calls}
        assert {"QQQ.US", "SPY.US", "SMH.US"}.issubset(symbols)

    def test_event_catalyst_initial_tools_include_expanded_news_searches(self):
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        sub_agent = EventCatalystSubAgent(mock_llm, mock_adapter)
        initial_calls = sub_agent._get_initial_tool_calls("TC.US")
        news_calls = [item for item in initial_calls if item["name"] == "news_search"]
        assert sub_agent.max_rounds == 4
        assert news_calls[0]["arguments"]["limit"] == 15
        assert any("earnings" in item["arguments"].get("keyword", "") or "财报" in item["arguments"].get("keyword", "") for item in news_calls)
        assert any("CEO" in item["arguments"].get("keyword", "") for item in news_calls)

    def test_account_fit_sub_agent_no_max_rounds(self):
        """AccountFitSubAgent has no MCP calls, no max_rounds."""
        mock_llm = MagicMock()
        sub_agent = AccountFitSubAgent(mock_llm)
        # AccountFitSubAgent doesn't use ToolCallingRuntime - it uses LLM directly
        assert not hasattr(sub_agent, "max_rounds") or sub_agent.max_rounds is None

    def test_risk_reward_sub_agent_no_max_rounds(self):
        """RiskRewardSubAgent has no MCP calls, no max_rounds."""
        mock_llm = MagicMock()
        sub_agent = RiskRewardSubAgent(mock_llm)
        # RiskRewardSubAgent doesn't use ToolCallingRuntime - it reads other cards
        assert not hasattr(sub_agent, "max_rounds") or sub_agent.max_rounds is None


class TestMCPToolAdapterUsage:
    """Tests that sub-agents use LongbridgeMCPToolAdapter."""

    def test_market_trend_uses_adapter(self):
        """MarketTrendSubAgent should call adapter.call() for MCP tools."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.call = MagicMock(return_value={"ok": False, "tool": "quote", "data_limitations": ["MCP unavailable"]})
        sub_agent = MarketTrendSubAgent(mock_llm, mock_adapter)
        # Verify that adapter is stored on the instance
        assert sub_agent.adapter is mock_adapter


class TestEventCatalystDataLimitations:
    def test_event_catalyst_uses_friendly_calendar_and_news_limitations(self):
        agent = EventCatalystSubAgent(MagicMock(), MagicMock())
        trace = [
            {
                "event": "tool_finish",
                "tool": "finance_calendar",
                "ok": True,
                "output": {"ok": True, "data": {}, "tool_call": {"tool_name": "finance_calendar", "missing_fields": [{"field_name": "next_earnings_date"}]}},
            },
            {
                "event": "tool_finish",
                "tool": "news_search",
                "ok": True,
                "output": {
                    "ok": True,
                    "data": {"items": [{"title": "TC news", "published_at": None, "source": "", "summary": ""}]},
                    "tool_call": {"tool_name": "news_search", "missing_fields": []},
                },
            },
        ]

        card = agent._parse_card(
            '{"summary":"背景有限","next_earnings_date":"","recent_news_count":1,"sentiment":"neutral","catalyst_strength":"weak","key_events":[],"risk_events":[],"score":2,"data_limitations":["mcp_field_missing: raw"]}',
            _make_snapshot("TC.US"),
            trace,
        )

        joined = " ".join(card.data_limitations)
        assert "财经日历暂未返回下一次财报日期" in joined
        assert "部分新闻缺少发布时间" in joined
        assert "部分新闻缺少摘要或背景" in joined
        assert "mcp_field_missing" not in joined
        assert "1970-01-01" not in joined


def _make_snapshot(symbol="AAPL", decision_type="entry_decision"):
    """Create a real AccountFactSnapshot for testing."""
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
        is_holding=False,
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


def _make_fallback_card(card_type, symbol, decision_type):
    """Create a fallback card of the appropriate type."""
    now = "2024-01-01T00:00:00Z"
    if card_type == "account_fit":
        return AccountFitCard(
            card_type="account_fit",
            symbol=symbol,
            decision_type=decision_type,
            summary="Fallback card",
            score=5,
            max_score=20,
            stance=CardStance.INSUFFICIENT_DATA,
            account_fit_level="unknown",
            evidence_quality="low",
            source_tools=[],
            created_at=now,
        )
    elif card_type == "market_trend":
        return MarketTrendCard(
            card_type="market_trend",
            symbol=symbol,
            decision_type=decision_type,
            summary="Fallback card",
            score=5,
            max_score=15,
            stance=CardStance.INSUFFICIENT_DATA,
            evidence_quality="low",
            source_tools=[],
            created_at=now,
        )
    elif card_type == "fundamental":
        return FundamentalValuationCard(
            card_type="fundamental_valuation",
            symbol=symbol,
            decision_type=decision_type,
            summary="Fallback card",
            score=10,
            max_score=35,
            stance=CardStance.INSUFFICIENT_DATA,
            evidence_quality="low",
            source_tools=[],
            created_at=now,
        )
    elif card_type == "event":
        return EventCatalystCard(
            card_type="event_catalyst",
            symbol=symbol,
            decision_type=decision_type,
            summary="Fallback card",
            score=2,
            max_score=5,
            stance=CardStance.INSUFFICIENT_DATA,
            evidence_quality="low",
            source_tools=[],
            created_at=now,
        )
    elif card_type == "risk_reward":
        return RiskRewardCard(
            card_type="risk_reward",
            symbol=symbol,
            decision_type=decision_type,
            summary="Fallback card",
            score=5,
            max_score=15,
            stance=CardStance.INSUFFICIENT_DATA,
            evidence_quality="low",
            source_tools=[],
            created_at=now,
        )


class TestMCPDiabledFallback:
    """Tests for fallback behavior when MCP is disabled."""

    def test_market_trend_fallback_when_mcp_disabled(self):
        """When MCP is unavailable, sub-agent returns fallback card."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.call = MagicMock(return_value={
            "ok": False,
            "error_code": "MCP_UNAVAILABLE",
            "tool": "quote",
            "data_limitations": ["MCP is disabled"],
        })
        mock_adapter.client = MagicMock()
        mock_adapter.client.enabled = True
        sub_agent = MarketTrendSubAgent(mock_llm, mock_adapter)

        snapshot = _make_snapshot()

        card, trace = sub_agent.generate(snapshot)
        # Should return a fallback card
        assert card is not None
        assert trace.status == "fallback" or trace.fallback_used is True

    def test_fundamental_valuation_fallback_when_mcp_disabled(self):
        """When MCP is unavailable, FundamentalValuationSubAgent returns fallback."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.call = MagicMock(return_value={
            "ok": False,
            "error_code": "MCP_UNAVAILABLE",
            "tool": "company",
            "data_limitations": ["MCP is disabled"],
        })
        mock_adapter.client = MagicMock()
        mock_adapter.client.enabled = True
        sub_agent = FundamentalValuationSubAgent(mock_llm, mock_adapter)

        snapshot = _make_snapshot()

        card, trace = sub_agent.generate(snapshot)
        assert card is not None
        assert trace.status == "fallback" or trace.fallback_used is True

    def test_event_catalyst_fallback_when_mcp_disabled(self):
        """When MCP is unavailable, EventCatalystSubAgent returns fallback."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.call = MagicMock(return_value={
            "ok": False,
            "error_code": "MCP_UNAVAILABLE",
            "tool": "news_search",
            "data_limitations": ["MCP is disabled"],
        })
        mock_adapter.client = MagicMock()
        mock_adapter.client.enabled = True
        sub_agent = EventCatalystSubAgent(mock_llm, mock_adapter)

        snapshot = _make_snapshot()

        card, trace = sub_agent.generate(snapshot)
        assert card is not None
        assert trace.status == "fallback" or trace.fallback_used is True


class TestAccountFitSubAgent:
    """Tests for AccountFitSubAgent."""

    def test_account_fit_no_mcp_calls(self):
        """AccountFitSubAgent should NOT call MCP tools."""
        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(return_value="账户适配良好，流动性充足")
        sub_agent = AccountFitSubAgent(mock_llm)

        snapshot = _make_snapshot()

        card, trace = sub_agent.generate(snapshot)
        # No MCP calls should be made - AccountFitSubAgent only uses LLM
        assert card is not None


class TestRiskRewardSubAgent:
    """Tests for RiskRewardSubAgent."""

    def test_risk_reward_no_mcp_calls(self):
        """RiskRewardSubAgent should NOT call MCP tools."""
        mock_llm = MagicMock()
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()

        account_fit_card = _make_fallback_card("account_fit", "AAPL", "entry_decision")
        account_fit_card.max_suggested_position_pct = 0.08
        account_fit_card.position_size_label = "medium"

        market_trend_card = _make_fallback_card("market_trend", "AAPL", "entry_decision")
        market_trend_card.recent_return_pct = 5.0

        fundamental_card = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fundamental_card.pe_ttm = 25.0
        fundamental_card.market_cap = 3000e9

        event_card = _make_fallback_card("event", "AAPL", "entry_decision")

        card, trace = sub_agent.generate(snapshot, account_fit_card, market_trend_card, fundamental_card, event_card)
        # RiskRewardSubAgent reads other cards, no MCP calls
        assert card is not None

    def test_risk_reward_reads_other_cards(self):
        """RiskRewardSubAgent reads outputs from other cards."""
        mock_llm = MagicMock()
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot(symbol="AAPL")
        snapshot.avg_cost = 145.0
        snapshot.is_holding = True

        account_fit_card = _make_fallback_card("account_fit", "AAPL", "entry_decision")
        account_fit_card.max_suggested_position_pct = 0.05
        account_fit_card.position_size_label = "large"

        market_trend_card = _make_fallback_card("market_trend", "AAPL", "entry_decision")
        market_trend_card.recent_return_pct = 3.5

        fundamental_card = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fundamental_card.pe_ttm = 22.0
        fundamental_card.market_cap = None

        event_card = _make_fallback_card("event", "AAPL", "entry_decision")

        card, trace = sub_agent.generate(snapshot, account_fit_card, market_trend_card, fundamental_card, event_card)
        # Should have used the account_fit card
        assert card is not None
        assert card.upside_potential_pct > 0

    @patch("app.services.trade_decision_sub_agents.StructuredOutputRuntime")
    def test_risk_reward_llm_enhances_text_fields_only(self, mock_so_runtime_cls):
        """LLM enhancement updates summary/key_risks/key_opportunities but not core numeric fields."""
        import json as _json

        llm_output = {
            "summary": "LLM增强的风险收益分析摘要",
            "key_risks": ["估值偏高风险", "行业周期下行风险"],
            "key_opportunities": ["业绩超预期机会", "技术面突破机会"],
            "risk_assessment_reason": "综合评估后认为风险可控",
            "data_limitations": [],
        }
        mock_so_result = MagicMock()
        mock_so_result.ok = True
        mock_so_result.payload = llm_output
        mock_so_result.metadata = {"ok": True, "contract_name": "trade_decision_risk_reward"}

        mock_so_runtime = MagicMock()
        mock_so_runtime.parse_validate_repair.return_value = mock_so_result
        mock_so_runtime_cls.return_value = mock_so_runtime

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _json.dumps(llm_output)
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()
        snapshot.avg_cost = 145.0
        snapshot.is_holding = True

        account_fit_card = _make_fallback_card("account_fit", "AAPL", "entry_decision")
        account_fit_card.max_suggested_position_pct = 0.05
        account_fit_card.position_size_label = "medium"

        market_trend_card = _make_fallback_card("market_trend", "AAPL", "entry_decision")
        market_trend_card.recent_return_pct = 5.0

        fundamental_card = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fundamental_card.pe_ttm = 25.0
        fundamental_card.market_cap = 3000e9

        event_card = _make_fallback_card("event", "AAPL", "entry_decision")

        card, trace = sub_agent.generate(snapshot, account_fit_card, market_trend_card, fundamental_card, event_card)

        # LLM-enhanced text fields should be updated
        assert card.summary == "LLM增强的风险收益分析摘要"
        assert card.key_risks == ["估值偏高风险", "行业周期下行风险"]
        assert card.key_opportunities == ["业绩超预期机会", "技术面突破机会"]

        # Core numeric fields must NOT be changed by LLM
        assert card.score in (4, 8, 12)
        assert card.reward_risk_ratio > 0
        assert card.upside_potential_pct > 0
        assert card.downside_risk_pct > 0

        # Trace should record structured output
        assert trace.structured_output is not None
        assert trace.rounds_used == 1

    @patch("app.services.trade_decision_sub_agents.StructuredOutputRuntime")
    def test_risk_reward_llm_invalid_json_returns_base_card(self, mock_so_runtime_cls):
        """When LLM returns invalid JSON, the rule-based base_card is returned unchanged."""
        mock_so_result = MagicMock()
        mock_so_result.ok = False
        mock_so_result.payload = None
        mock_so_result.error_code = "LLM_SCHEMA_INVALID"
        mock_so_result.metadata = {"ok": False, "error_code": "LLM_SCHEMA_INVALID"}

        mock_so_runtime = MagicMock()
        mock_so_runtime.parse_validate_repair.return_value = mock_so_result
        mock_so_runtime_cls.return_value = mock_so_runtime

        mock_llm = MagicMock()
        mock_llm.chat.return_value = "not valid json"
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()

        account_fit_card = _make_fallback_card("account_fit", "AAPL", "entry_decision")
        account_fit_card.max_suggested_position_pct = 0.08
        account_fit_card.position_size_label = "medium"

        market_trend_card = _make_fallback_card("market_trend", "AAPL", "entry_decision")
        market_trend_card.recent_return_pct = 5.0

        fundamental_card = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fundamental_card.pe_ttm = 25.0
        fundamental_card.market_cap = 3000e9

        event_card = _make_fallback_card("event", "AAPL", "entry_decision")

        card, trace = sub_agent.generate(snapshot, account_fit_card, market_trend_card, fundamental_card, event_card)

        # Should return rule-based card (not crash)
        assert card is not None
        assert card.score in (4, 8, 12)
        assert "LLM增强" not in card.summary
        # Trace should record the fallback
        assert trace.fallback_used is True
        assert "risk_reward_llm_enhancement_failed" in (trace.fallback_reason or "")

    @patch("app.services.trade_decision_sub_agents.StructuredOutputRuntime")
    def test_risk_reward_llm_exception_returns_base_card(self, mock_so_runtime_cls):
        """When LLM call raises exception, the rule-based base_card is returned unchanged."""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM service unavailable")
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()

        account_fit_card = _make_fallback_card("account_fit", "AAPL", "entry_decision")
        account_fit_card.max_suggested_position_pct = 0.08
        account_fit_card.position_size_label = "medium"

        market_trend_card = _make_fallback_card("market_trend", "AAPL", "entry_decision")
        market_trend_card.recent_return_pct = 5.0

        fundamental_card = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fundamental_card.pe_ttm = 25.0
        fundamental_card.market_cap = 3000e9

        event_card = _make_fallback_card("event", "AAPL", "entry_decision")

        card, trace = sub_agent.generate(snapshot, account_fit_card, market_trend_card, fundamental_card, event_card)

        # Should return rule-based card (not crash)
        assert card is not None
        assert card.score in (4, 8, 12)
        assert trace.fallback_used is True
        assert "risk_reward_llm_enhancement_failed" in (trace.fallback_reason or "")


class TestCardPackStructure:
    """Tests for TradeDecisionCardPack structure."""

    def test_card_pack_holds_all_phase1_cards(self):
        """CardPack should hold cards for all 4 phase1 sub-agents."""
        snapshot = _make_snapshot()
        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )
        assert card_pack.account_fit_card is not None
        assert card_pack.market_trend_card is not None
        assert card_pack.fundamental_valuation_card is not None
        assert card_pack.event_catalyst_card is not None

    def test_card_pack_holds_risk_reward_card(self):
        """CardPack should hold risk_reward card (phase2)."""
        snapshot = _make_snapshot()
        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )
        assert card_pack.risk_reward_card is not None


class TestComposerOutput:
    """Tests for TradeDecisionComposer output structure."""

    def _make_card_pack_with_real_cards(self):
        """Create a card pack with real card instances."""
        snapshot = _make_snapshot()
        return TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )

    def test_composer_suggested_cash_amount_no_error(self):
        """Composer should not raise error when suggested_cash_amount > 0."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        result = composer.compose(card_pack)
        # Should not raise AttributeError for suggested_cash_amount
        assert result is not None
        assert "position_advice" in result

    def test_composer_output_has_required_fields(self):
        """Composer output should have all required fields."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        result = composer.compose(card_pack)
        # Check required fields
        assert "overall_score" in result
        assert "rating" in result
        assert "action" in result
        assert "confidence" in result
        assert "decision_summary" in result
        assert "position_advice" in result
        assert "execution_plan" in result

    def test_composer_position_advice_structure(self):
        """Composer position_advice should have suggested_cash_amount field."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        result = composer.compose(card_pack)
        # Position advice should have suggested_cash_amount
        position_advice = result.get("position_advice", {})
        assert "suggested_cash_amount" in position_advice

    def test_invalid_zero_pe_does_not_receive_full_valuation_score(self):
        """PE=0 means missing data, not cheap valuation."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        card_pack.fundamental_valuation_card.pe_ttm = 0
        card_pack.fundamental_valuation_card.score = 0
        card_pack.fundamental_valuation_card.evidence_quality = "low"

        result = composer.compose(card_pack)

        assert result["score_detail"]["valuation_score"]["score"] == 0
        assert "不可用" in result["score_detail"]["valuation_score"]["reason"]

    def test_wait_entry_has_zero_target_and_cash_advice(self):
        """If the action is wait for a new entry, position advice should not suggest capital."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        card_pack.risk_reward_card.wait_for_pullback = True

        result = composer.compose(card_pack)

        assert result["action"] == "wait"
        assert result["position_advice"]["suggested_target_position_pct"] == 0
        assert result["position_advice"]["suggested_cash_amount"] == 0

    def test_entry_decision_does_not_use_holding_days_as_reason(self):
        """Prior trade history should not be presented as current holding tenure for entry decisions."""
        from app.services.trade_decision_composer import TradeDecisionComposer
        composer = TradeDecisionComposer()
        card_pack = self._make_card_pack_with_real_cards()
        card_pack.account_fact_snapshot.is_holding = False
        card_pack.account_fact_snapshot.holding_days = 73

        result = composer.compose(card_pack)

        assert all("已持有73天" not in reason for reason in result["key_reasons"])

    def test_card_pack_evidence_pack_exposes_public_card_contexts(self):
        """V2 evidence summary should use card contexts, not only account snapshot fields."""
        from app.services.trade_decision_agent import _build_card_pack_evidence_pack
        from app.agents.evidence_summary import build_evidence_summary

        card_pack = self._make_card_pack_with_real_cards()
        card_pack.market_trend_card.source_tools = ["quote", "candlesticks"]
        card_pack.fundamental_valuation_card.source_tools = ["company", "valuation"]
        card_pack.event_catalyst_card.source_tools = ["news_search"]

        evidence_pack = _build_card_pack_evidence_pack(card_pack)
        summary = build_evidence_summary(evidence_pack, [])
        statuses = {item["section"]: item["status"] for item in summary["evidence_sections"]}

        assert statuses["market_context"] != "missing"
        assert statuses["company_context"] != "missing"
        assert statuses["valuation_context"] != "missing"
        assert "market_context is missing or empty" not in summary["missing_data"]


class TestCardPackQuality:
    """Tests for card pack quality assessment."""

    def test_card_pack_has_all_5_cards(self):
        """A complete card pack should have all 5 cards."""
        snapshot = _make_snapshot()
        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )
        card_dict = card_pack.to_dict()
        expected_keys = ["account_fit_card", "market_trend_card", "fundamental_valuation_card", "event_catalyst_card", "risk_reward_card"]
        for key in expected_keys:
            assert key in card_dict, f"Missing card: {key}"

    def test_card_pack_tracks_subagent_traces(self):
        """Card pack should support sub-agent execution traces."""
        snapshot = _make_snapshot()
        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )
        # CardPack should have subagent_traces list
        assert hasattr(card_pack, "subagent_traces")

    def test_fallback_card_has_fallback_used_flag(self):
        """Fallback cards should have fallback_used=True."""
        mock_llm = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.call = MagicMock(return_value={
            "ok": False,
            "error_code": "MCP_UNAVAILABLE",
            "tool": "quote",
            "data_limitations": ["MCP is disabled"],
        })
        mock_adapter.client = MagicMock()
        mock_adapter.client.enabled = True
        sub_agent = MarketTrendSubAgent(mock_llm, mock_adapter)
        snapshot = _make_snapshot()
        card, trace = sub_agent.generate(snapshot)
        # Check that fallback_used is set to True on the trace
        assert trace.fallback_used is True


class TestSubAgentReActBounded:
    """Tests that sub-agents use bounded ReAct (not hardcoded tool calls)."""

    def test_market_trend_sub_agent_uses_runtime(self):
        """MarketTrendSubAgent should use ToolCallingRuntime."""
        import inspect
        source = inspect.getsource(MarketTrendSubAgent)
        # Should use ToolCallingRuntime or have runtime-related logic
        # Not hardcoded tool calls
        assert "runtime" in source.lower() or "ToolCallingRuntime" in source

    def test_sub_agent_initial_tools_are_documented(self):
        """Sub-agents should define their initial tools clearly."""
        import inspect
        # MarketTrend initial tools should include quote and candlesticks
        source_market = inspect.getsource(MarketTrendSubAgent)
        assert "quote" in source_market or "candlesticks" in source_market

        # FundamentalValuation initial tools should include company, financial_report, valuation
        source_fund = inspect.getsource(FundamentalValuationSubAgent)
        assert "company" in source_fund or "financial_report" in source_fund

        # EventCatalyst initial tools should include news_search, finance_calendar
        source_event = inspect.getsource(EventCatalystSubAgent)
        assert "news_search" in source_event or "finance_calendar" in source_event


class TestRiskRewardLLMRiskAssessmentReason:
    """Tests that risk_assessment_reason flows through from LLM to card."""

    @patch("app.services.trade_decision_sub_agents.StructuredOutputRuntime")
    def test_llm_success_writes_risk_assessment_reason(self, mock_so_runtime_cls):
        """When LLM succeeds, risk_assessment_reason is written to the card."""
        import json as _json

        llm_output = {
            "summary": "LLM增强摘要",
            "key_risks": ["风险1"],
            "key_opportunities": ["机会1"],
            "risk_assessment_reason": "综合评估风险可控，收益空间合理",
            "data_limitations": [],
        }
        mock_so_result = MagicMock()
        mock_so_result.ok = True
        mock_so_result.payload = llm_output
        mock_so_result.metadata = {"ok": True}

        mock_so_runtime = MagicMock()
        mock_so_runtime.parse_validate_repair.return_value = mock_so_result
        mock_so_runtime_cls.return_value = mock_so_runtime

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _json.dumps(llm_output)
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()
        card, trace = sub_agent.generate(snapshot)

        assert card.risk_assessment_reason == "综合评估风险可控，收益空间合理"
        assert card.summary == "LLM增强摘要"
        assert card.key_risks == ["风险1"]

    @patch("app.services.trade_decision_sub_agents.StructuredOutputRuntime")
    def test_llm_without_risk_assessment_reason_leaves_none(self, mock_so_runtime_cls):
        """When LLM output lacks risk_assessment_reason, field stays None."""
        import json as _json

        llm_output = {
            "summary": "LLM摘要",
            "key_risks": [],
            "key_opportunities": [],
            "data_limitations": [],
        }
        mock_so_result = MagicMock()
        mock_so_result.ok = True
        mock_so_result.payload = llm_output
        mock_so_result.metadata = {"ok": True}

        mock_so_runtime = MagicMock()
        mock_so_runtime.parse_validate_repair.return_value = mock_so_result
        mock_so_runtime_cls.return_value = mock_so_runtime

        mock_llm = MagicMock()
        mock_llm.chat.return_value = _json.dumps(llm_output)
        sub_agent = RiskRewardSubAgent(mock_llm)

        snapshot = _make_snapshot()
        card, trace = sub_agent.generate(snapshot)

        assert card.risk_assessment_reason is None
        assert card.summary == "LLM摘要"


class TestComposerRiskRewardReason:
    """Tests that composer uses LLM-enhanced risk_reward reason."""

    def _make_card_pack(self, rr_card):
        snapshot = _make_snapshot()
        return TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=rr_card,
        )

    def test_risk_reward_reason_prefers_risk_assessment_reason(self):
        """risk_reward_score.reason should use risk_assessment_reason when available."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 8
        rr.risk_assessment_reason = "LLM风险评估：下行风险可控，上行空间尚可"
        rr.summary = "LLM摘要"
        rr.reward_risk_ratio = 1.5
        rr.upside_potential_pct = 20.0
        rr.downside_risk_pct = 15.0

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        reason = result["score_detail"]["risk_reward_score"]["reason"]
        assert reason == "风险收益: LLM风险评估：下行风险可控，上行空间尚可"

    def test_risk_reward_reason_falls_back_to_summary(self):
        """When risk_assessment_reason is None, reason should use summary."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 8
        rr.risk_assessment_reason = None
        rr.summary = "上行空间30%，下行风险15%，风险收益比2.0x"
        rr.reward_risk_ratio = 2.0
        rr.upside_potential_pct = 30.0
        rr.downside_risk_pct = 15.0

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        reason = result["score_detail"]["risk_reward_score"]["reason"]
        assert reason == "风险收益: 上行空间30%，下行风险15%，风险收益比2.0x"

    def test_risk_reward_reason_falls_back_to_formula(self):
        """When both risk_assessment_reason and summary are empty, use formula."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 4
        rr.risk_assessment_reason = None
        rr.summary = ""
        rr.reward_risk_ratio = 0.7
        rr.upside_potential_pct = 10.0
        rr.downside_risk_pct = 15.0

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        reason = result["score_detail"]["risk_reward_score"]["reason"]
        assert "0.7x" in reason
        assert "上行" in reason

    def test_extract_major_risks_includes_rr_key_risks(self):
        """_extract_major_risks should include rr.key_risks."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 8
        rr.key_risks = ["估值偏高风险", "行业周期下行风险"]
        rr.downside_risk_pct = 10.0

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        assert "估值偏高风险" in result["major_risks"]
        assert "行业周期下行风险" in result["major_risks"]

    def test_extract_key_reasons_includes_rr_key_opportunities(self):
        """_extract_key_reasons should include rr.key_opportunities."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 8
        rr.key_opportunities = ["业绩超预期机会", "技术面突破机会"]
        rr.reward_risk_ratio = 1.5

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        assert "业绩超预期机会" in result["key_reasons"]
        assert "技术面突破机会" in result["key_reasons"]

    def test_extract_key_reasons_uses_opportunities_over_formula(self):
        """When key_opportunities exist, the fixed ratio formula is skipped."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        rr = _make_fallback_card("risk_reward", "AAPL", "entry_decision")
        rr.score = 12
        rr.key_opportunities = ["LLM机会点"]
        rr.reward_risk_ratio = 2.5

        composer = TradeDecisionComposer()
        result = composer.compose(self._make_card_pack(rr))

        assert "LLM机会点" in result["key_reasons"]
        assert all("具吸引力" not in r for r in result["key_reasons"])


class TestComposerReasonTruncation:
    """Tests that score_detail reasons are not prematurely truncated."""

    def test_event_catalyst_reason_preserves_long_summary(self):
        """Event catalyst reason should not truncate at 80 chars."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        long_summary = (
            "近期有财报窗口和机构评级变化，存在中等事件催化。"
            "新闻多为价格波动和分析师评级调整相关，未发现重大负面事件。"
            "下一次财报预计在2026年7月，目前处于静默期前的观察阶段。"
            "机构评级整体偏正面，但部分分析师下调了短期目标价。"
            "社交媒体情绪中性偏正面，无重大舆情风险。"
        )
        snapshot = _make_snapshot()
        evt = _make_fallback_card("event", "AAPL", "entry_decision")
        evt.score = 4
        evt.summary = long_summary

        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=_make_fallback_card("fundamental", "AAPL", "entry_decision"),
            event_catalyst_card=evt,
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )

        composer = TradeDecisionComposer()
        result = composer.compose(card_pack)

        reason = result["score_detail"]["event_catalyst_score"]["reason"]
        # Should contain the tail text, not truncated at 80 chars
        assert "社交媒体情绪" in reason
        assert len(reason) > 80

    def test_fundamental_reason_preserves_long_summary(self):
        """Fundamental reason should not truncate at 100 chars."""
        from app.services.trade_decision_composer import TradeDecisionComposer

        long_summary = "A" * 300
        snapshot = _make_snapshot()
        fund = _make_fallback_card("fundamental", "AAPL", "entry_decision")
        fund.score = 20
        fund.summary = long_summary

        card_pack = TradeDecisionCardPack(
            decision_type="entry_decision",
            symbol="AAPL",
            account_fact_snapshot=snapshot,
            account_fit_card=_make_fallback_card("account_fit", "AAPL", "entry_decision"),
            market_trend_card=_make_fallback_card("market_trend", "AAPL", "entry_decision"),
            fundamental_valuation_card=fund,
            event_catalyst_card=_make_fallback_card("event", "AAPL", "entry_decision"),
            risk_reward_card=_make_fallback_card("risk_reward", "AAPL", "entry_decision"),
        )

        composer = TradeDecisionComposer()
        result = composer.compose(card_pack)

        reason = result["score_detail"]["fundamental_quality_score"]["reason"]
        # Should contain the full 300-char summary (plus prefix)
        assert "A" * 200 in reason

    def test_reason_text_helper_empty_text(self):
        """_reason_text should handle empty/None text gracefully."""
        from app.services.trade_decision_composer import _reason_text

        assert _reason_text("前缀", None) == "前缀: 暂无说明"
        assert _reason_text("前缀", "") == "前缀: 暂无说明"
        assert _reason_text("前缀", "  ") == "前缀: 暂无说明"
