"""Tests for LLM-powered trade decision debate agents."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agents.trade_decision_cards import (
    DebateJudgeCard,
    TradeDecisionSubAgentTrace,
)
from app.agents.trade_decision_graph.nodes import make_debate_judge_node
from app.services.trade_decision_debate_agents import (
    BearThesisAgent,
    BullRebuttalAgent,
    BullThesisAgent,
    DebateJudgeAgent,
)
from tests.test_trade_decision_langgraph import _make_card_pack, _make_fallback_card


class FakeLLMService:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.error:
            raise self.error
        return self.responses.pop(0)


def test_bull_thesis_agent_structured_output():
    llm = FakeLLMService([
        """
        {
          "agent_name": "bull_thesis",
          "stance": "bullish",
          "conviction": "medium",
          "summary": "trend and fundamentals support a constructive asset view",
          "core_claims": ["trend improved"],
          "evidence_refs": ["market_trend_card", "fake_card", "fundamental_valuation_card"],
          "weak_points": ["valuation still matters"],
          "risk_flags": ["event risk"],
          "data_limitations": []
        }
        """
    ])

    card, sub_trace = BullThesisAgent(llm).generate(_make_card_pack())

    assert card.agent_name == "bull_thesis"
    assert card.stance == "bullish"
    assert card.conviction == "medium"
    assert card.evidence_refs == ["market_trend_card", "fundamental_valuation_card"]
    assert sub_trace.status == "completed"
    assert sub_trace.structured_output is not None
    assert sub_trace.tools_called == []


def test_bear_thesis_agent_forces_agent_name_and_stance_from_payload():
    agent = BearThesisAgent(FakeLLMService())
    agent.runtime.generate = MagicMock(return_value=SimpleNamespace(
        ok=True,
        payload={
            "agent_name": "wrong",
            "stance": "bullish",
            "conviction": "high",
            "summary": "risks deserve attention",
            "core_claims": ["valuation risk"],
            "evidence_refs": ["risk_reward_card"],
            "weak_points": [],
            "risk_flags": [],
            "data_limitations": [],
        },
        repaired=False,
        repair_attempts=0,
        fallback_used=False,
        error_code=None,
        error_message=None,
        metadata={"contract_name": "trade_decision_bear_thesis"},
        trace=[],
    ))

    card, sub_trace = agent.generate(_make_card_pack())

    assert card.agent_name == "bear_thesis"
    assert card.stance == "bearish"
    assert card.conviction == "high"
    assert card.evidence_refs == []
    assert sub_trace.status == "completed"


def test_rebuttal_agent_structured_output():
    card_pack = _make_card_pack()
    bull = card_pack.bull_thesis_card or BullThesisAgent(FakeLLMService([
        '{"agent_name":"bull_thesis","stance":"bullish","conviction":"low","summary":"bull","core_claims":[],"evidence_refs":[],"weak_points":[],"risk_flags":[],"data_limitations":[]}'
    ])).generate(card_pack)[0]
    bear = BearThesisAgent(FakeLLMService([
        '{"agent_name":"bear_thesis","stance":"bearish","conviction":"low","summary":"bear","core_claims":[],"evidence_refs":[],"weak_points":[],"risk_flags":[],"data_limitations":[]}'
    ])).generate(card_pack)[0]
    llm = FakeLLMService([
        """
        {
          "agent_name": "bull_rebuttal",
          "summary": "bear risks are real but not decisive",
          "accepted_opponent_points": ["macro risk"],
          "rejected_opponent_points": ["trend is broken"],
          "reinforced_arguments": ["trend evidence remains constructive"],
          "final_conviction": "medium",
          "data_limitations": []
        }
        """
    ])

    card, sub_trace = BullRebuttalAgent(llm).generate(card_pack, bull, bear)

    assert card.agent_name == "bull_rebuttal"
    assert card.accepted_opponent_points == ["macro risk"]
    assert card.rejected_opponent_points == ["trend is broken"]
    assert card.reinforced_arguments == ["trend evidence remains constructive"]
    assert sub_trace.structured_output is not None


def test_debate_judge_agent_structured_output_has_no_portfolio_action():
    card_pack = _make_card_pack()
    bull = BullThesisAgent(FakeLLMService([
        '{"agent_name":"bull_thesis","stance":"bullish","conviction":"low","summary":"bull","core_claims":[],"evidence_refs":[],"weak_points":[],"risk_flags":[],"data_limitations":[]}'
    ])).generate(card_pack)[0]
    bear = BearThesisAgent(FakeLLMService([
        '{"agent_name":"bear_thesis","stance":"bearish","conviction":"low","summary":"bear","core_claims":[],"evidence_refs":[],"weak_points":[],"risk_flags":[],"data_limitations":[]}'
    ])).generate(card_pack)[0]
    rebuttal = BullRebuttalAgent(FakeLLMService([
        '{"agent_name":"bull_rebuttal","summary":"rebuttal","accepted_opponent_points":[],"rejected_opponent_points":[],"reinforced_arguments":[],"final_conviction":"low","data_limitations":[]}'
    ])).generate(card_pack, bull, bear)[0]
    llm = FakeLLMService([
        """
        {
          "asset_stance": "bullish",
          "conviction": "medium",
          "winner": "bull",
          "accepted_bull_points": ["trend"],
          "accepted_bear_points": ["valuation risk"],
          "key_uncertainties": ["earnings"],
          "reasoning_summary": "bull evidence is stronger",
          "data_limitations": []
        }
        """
    ])

    card, sub_trace = DebateJudgeAgent(llm).generate(card_pack, bull, bear, rebuttal, rebuttal)

    assert card.asset_stance == "bullish"
    assert card.winner == "bull"
    assert "portfolio_action" not in card.to_dict()
    assert sub_trace.status == "completed"


def test_invalid_payload_is_sanitized():
    agent = BullThesisAgent(FakeLLMService())
    agent.runtime.generate = MagicMock(return_value=SimpleNamespace(
        ok=True,
        payload={
            "agent_name": "wrong",
            "stance": "bearish",
            "conviction": "extreme",
            "summary": "<think>x</think>ok",
            "core_claims": "claim",
            "evidence_refs": ["fake_card", "account_fit_card"],
            "weak_points": None,
            "risk_flags": "risk",
            "data_limitations": [],
        },
        repaired=False,
        repair_attempts=0,
        fallback_used=False,
        error_code=None,
        error_message=None,
        metadata={"contract_name": "trade_decision_bull_thesis"},
        trace=[],
    ))

    card, _ = agent.generate(_make_card_pack())

    assert card.agent_name == "bull_thesis"
    assert card.stance == "bullish"
    assert card.conviction == "low"
    assert card.evidence_refs == ["account_fit_card"]
    assert card.core_claims == ["claim"]
    assert card.summary == "ok"


def test_llm_failure_returns_fallback_card():
    card, sub_trace = BullThesisAgent(FakeLLMService(error=RuntimeError("provider down"))).generate(_make_card_pack())

    assert card.agent_name == "bull_thesis"
    assert sub_trace.status == "fallback"
    assert sub_trace.fallback_used is True
    assert sub_trace.structured_output is not None


def test_debate_judge_node_forces_insufficient_data_when_public_data_fallbacks():
    state = {
        "symbol": "AAPL",
        "decision_type": "entry_decision",
        "card_pack": _make_card_pack(all_fallback=True),
        "market_trend_card": _make_fallback_card("market_trend"),
        "fundamental_valuation_card": _make_fallback_card("fundamental_valuation"),
        "event_catalyst_card": _make_fallback_card("event_catalyst"),
    }
    llm_card = DebateJudgeCard(
        symbol="AAPL",
        asset_stance="bullish",
        conviction="high",
        winner="bull",
        reasoning_summary="bullish",
    )
    sub_trace = TradeDecisionSubAgentTrace(
        sub_agent_name="debate_judge",
        status="completed",
        rounds_used=1,
        structured_output={"ok": True},
    )

    with patch("app.services.trade_decision_debate_agents.DebateJudgeAgent.generate", return_value=(llm_card, sub_trace)):
        result = make_debate_judge_node(SimpleNamespace(llm_service=MagicMock(), monitoring_service=None))(state)

    card = result["debate_judge_card"]
    assert card.asset_stance == "insufficient_data"
    assert card.conviction == "low"
    assert card.winner == "insufficient_data"
    assert "公开市场数据不足，辩论裁判已降级" in card.data_limitations
