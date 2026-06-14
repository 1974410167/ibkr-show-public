import json

import pytest
from pydantic import ValidationError

from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    TradeDecisionCardPack,
)
from app.agents.trade_decision_structured_outputs import AiPolicyAssessmentOutput
from app.services.trade_decision_policy_assessment_agent import (
    AI_POLICY_ASSESSMENT_FAILURE_LIMITATION,
    TradeDecisionPolicyAssessmentAgent,
)


class FakeLLM:
    def __init__(self, payload=None, *, fail=False):
        self.payload = payload
        self.fail = fail
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages.append(messages)
        if self.fail:
            raise RuntimeError("llm boom")
        return json.dumps(self.payload, ensure_ascii=False)


class FakePromptService:
    def __init__(self, *, content="ADMIN PROMPT", source="admin_active", fail=False):
        self.content = content
        self.source = source
        self.fail = fail
        self.calls = []

    def get_runtime_prompt(self, prompt_key, fallback=None):
        self.calls.append((prompt_key, fallback))
        if self.fail:
            raise RuntimeError("prompt boom")
        return {
            "content": self.content,
            "metadata": {
                "prompt_key": prompt_key,
                "version": "v-admin",
                "content_hash": "hash-admin",
                "source": self.source,
            },
        }


def _snapshot(position_pct=0.06):
    return AccountFactSnapshot(
        decision_type="entry_decision",
        symbol="AMD",
        normalized_symbol="AMD",
        user_question="是否加仓 AMD",
        net_liquidation=100000.0,
        cash=30000.0,
        deployable_liquidity=30000.0,
        deployable_liquidity_ratio=0.3,
        total_position_value=6000.0,
        top_positions=[],
        position_concentration=None,
        risk_concentration=None,
        margin_info=None,
        is_holding=True,
        quantity=10,
        avg_cost=100,
        current_price=120,
        market_value=position_pct * 100000,
        position_pct=position_pct,
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


def _card_pack(position_pct=0.06):
    snapshot = _snapshot(position_pct)
    return TradeDecisionCardPack(
        decision_type="entry_decision",
        symbol="AMD",
        account_fact_snapshot=snapshot,
        account_fit_card=AccountFitCard(
            card_type="account_fit",
            symbol="AMD",
            decision_type="entry_decision",
            summary="good",
            score=16,
            max_score=20,
            stance=CardStance.BULLISH,
            account_fit_level="good",
            max_suggested_position_pct=0.18,
        ),
        market_trend_card=MarketTrendCard(
            card_type="market_trend",
            symbol="AMD",
            decision_type="entry_decision",
            summary="trend ok",
            score=12,
            max_score=15,
            stance=CardStance.BULLISH,
            price_trend="bullish",
        ),
        fundamental_valuation_card=FundamentalValuationCard(
            card_type="fundamental_valuation",
            symbol="AMD",
            decision_type="entry_decision",
            summary="valuation rich",
            score=22,
            max_score=35,
            stance=CardStance.BULLISH,
        ),
        event_catalyst_card=EventCatalystCard(
            card_type="event_catalyst",
            symbol="AMD",
            decision_type="entry_decision",
            summary="earnings ahead",
            score=3,
            max_score=5,
            stance=CardStance.NEUTRAL,
            sentiment="neutral",
            catalyst_strength="moderate",
        ),
        user_investment_policy={
            "source": "user_config",
            "user_investment_preference": {
                "asset_role": "core_growth",
                "conviction": "high",
                "user_preferred_target_position_pct": 0.2,
                "user_preferred_max_position_pct": 0.28,
            },
        },
    )


def _payload(**overrides):
    payload = {
        "status": "evaluated",
        "ai_assessed_asset_role": "core_growth",
        "ai_role_confidence": "medium",
        "ai_recommended_min_position_pct": 0.08,
        "ai_recommended_target_position_pct": 0.14,
        "ai_recommended_max_position_pct": 0.2,
        "ai_recommended_target_position_range_pct": [0.12, 0.16],
        "ai_position_stance": "underweight",
        "current_position_pct": 0.99,
        "gap_to_ai_target_pct": 0.99,
        "gap_to_ai_max_pct": 0.99,
        "challenge_level": "mild_disagreement",
        "challenge_reason": "用户最大仓位偏高。",
        "preference_alignment_summary": "认可定位，但建议阶段性目标更低。",
        "recommended_action_bias": "prefer_pullback_add",
        "risk_budget": {"estimated_downside_pct": 0.18, "max_account_loss_pct": 0.036, "reason": "downside budget"},
        "key_reasons": ["证据支持持有"],
        "key_risks": ["估值压缩"],
        "data_limitations": [],
        "prompt_key": "ignored",
        "prompt_source": "default_fallback",
    }
    payload.update(overrides)
    return payload


def test_ai_policy_assessment_success_uses_admin_prompt_and_forces_current_pct():
    llm = FakeLLM(_payload())
    prompt_service = FakePromptService(content="ADMIN POLICY PROMPT")

    assessment, trace = TradeDecisionPolicyAssessmentAgent(llm, prompt_service=prompt_service).generate(_card_pack(position_pct=0.06))

    assert trace.status == "completed"
    assert prompt_service.calls[0][0] == "trade_decision_ai_policy_assessment"
    assert llm.messages[0][0]["content"] == "ADMIN POLICY PROMPT"
    assert assessment["prompt_source"] == "admin_config"
    assert assessment["prompt_version"] == "v-admin"
    assert assessment["current_position_pct"] == pytest.approx(0.06)
    assert assessment["gap_to_ai_target_pct"] == pytest.approx(0.08)


def test_ai_policy_assessment_uses_default_fallback_when_no_prompt_service():
    llm = FakeLLM(_payload())

    assessment, trace = TradeDecisionPolicyAssessmentAgent(llm).generate(_card_pack())

    assert trace.status == "completed"
    assert assessment["prompt_source"] == "default_fallback"
    assert "AI 投资策略评估 Agent" in llm.messages[0][0]["content"]


def test_ai_policy_assessment_prompt_service_exception_falls_back_to_default_prompt():
    llm = FakeLLM(_payload())
    prompt_service = FakePromptService(fail=True)

    assessment, trace = TradeDecisionPolicyAssessmentAgent(llm, prompt_service=prompt_service).generate(_card_pack())

    assert trace.status == "completed"
    assert assessment["prompt_source"] == "default_fallback"
    assert trace.prompt_metadata["source"] == "fallback"
    assert "error" in trace.prompt_metadata


def test_ai_policy_assessment_llm_failure_returns_fallback():
    assessment, trace = TradeDecisionPolicyAssessmentAgent(FakeLLM(fail=True)).generate(_card_pack())

    assert trace.status == "fallback"
    assert assessment["status"] == "fallback"
    assert assessment["challenge_level"] == "not_evaluated"
    assert AI_POLICY_ASSESSMENT_FAILURE_LIMITATION in assessment["data_limitations"]


def test_ai_policy_output_validation_rejects_bad_position_order_and_high_confidence_with_limitations():
    with pytest.raises(ValidationError):
        AiPolicyAssessmentOutput.model_validate(_payload(ai_recommended_min_position_pct=0.2, ai_recommended_target_position_pct=0.1))

    with pytest.raises(ValidationError):
        AiPolicyAssessmentOutput.model_validate(_payload(ai_role_confidence="high", data_limitations=["缺少估值数据"]))


def test_user_forbidden_role_prevents_silent_allow_add():
    pack = _card_pack()
    pack.user_investment_policy["user_investment_preference"]["asset_role"] = "forbidden"
    llm = FakeLLM(_payload(recommended_action_bias="allow_add", challenge_level="agree"))

    assessment, trace = TradeDecisionPolicyAssessmentAgent(llm).generate(pack)

    assert trace.status == "completed"
    assert assessment["recommended_action_bias"] == "avoid"
    assert assessment["challenge_level"] == "risk_warning"
