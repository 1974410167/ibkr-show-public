from app.agents.trade_decision_cards import CardStance, TradePlanCard
from app.services.trade_decision_risk_reward_compat import build_risk_reward_card_from_trade_plan


def _plan(**overrides):
    base = dict(
        symbol="AAPL.US",
        asset_stance="bullish",
        portfolio_action="add_on_pullback",
        action_reason_type="asset_view_and_account_fit",
        summary="等待回调后小仓位建仓。",
        current_position_pct=0.0,
        target_position_pct=0.06,
        adjustment_pct=0.06,
        suggested_cash_amount=3000.0,
        max_position_pct=0.08,
        execution_conditions=["回调企稳后分批建仓"],
        invalidation_conditions=["跌破关键支撑"],
        recheck_triggers=["回调到计划区域"],
        risk_reward_assessment={
            "entry_quality": "medium",
            "upside_scenario": "上行空间改善",
            "downside_scenario": "跌破支撑后下行风险扩大",
            "reward_risk_ratio": 2.5,
            "wait_for_pullback": True,
            "pullback_entry_level": 120,
            "invalidation_level": 105,
            "trim_level": 160,
            "event_risk_window": "high",
        },
        data_limitations=[],
    )
    base.update(overrides)
    return TradePlanCard(**base)


def test_build_risk_reward_card_from_trade_plan_maps_core_fields():
    plan = _plan()

    card = build_risk_reward_card_from_trade_plan("AAPL.US", "trade_decision", plan)

    assert card.reward_risk_ratio == 2.5
    assert card.wait_for_pullback is True
    assert card.pullback_entry_level == 120
    assert card.invalidation_level == 105
    assert card.trim_level == 160
    assert card.action_guidance == plan.portfolio_action
    assert card.position_size_label == "small"
    assert "risk_reward_derived_from_trade_plan" in card.data_limitations
    assert card.data_quality["source"] == "trade_plan"


def test_score_falls_back_to_entry_quality_when_ratio_missing():
    scores = {
        quality: build_risk_reward_card_from_trade_plan(
            "AAPL.US",
            "trade_decision",
            _plan(risk_reward_assessment={"entry_quality": quality}),
        ).score
        for quality in ("high", "medium", "low", "unknown")
    }

    assert scores == {"high": 12, "medium": 8, "low": 4, "unknown": 0}


def test_asset_stance_mapping_is_not_over_positive():
    bearish = build_risk_reward_card_from_trade_plan("AAPL.US", "trade_decision", _plan(asset_stance="bearish"))
    insufficient = build_risk_reward_card_from_trade_plan("AAPL.US", "trade_decision", _plan(asset_stance="insufficient_data"))

    assert bearish.stance == CardStance.BEARISH
    assert insufficient.stance == CardStance.INSUFFICIENT_DATA


def test_builder_handles_invalid_assessment_without_throwing():
    card = build_risk_reward_card_from_trade_plan(
        "AAPL.US",
        "trade_decision",
        _plan(risk_reward_assessment="not-a-dict", target_position_pct="bad"),
    )

    assert card.card_type == "risk_reward"
    assert "risk_reward_derived_from_trade_plan" in card.data_limitations
