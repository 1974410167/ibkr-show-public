from app.services.trade_decision_quality_evaluator import TradeDecisionQualityEvaluator


def _trace(node_name: str, *, status: str = "success", tools_called=None, fallback_used=False, structured_output=None) -> dict:
    return {
        "event": f"node_{status}",
        "node_name": node_name,
        "status": status,
        "elapsed_ms": 1,
        "tools_called": tools_called or [],
        "tool_call_count": len(tools_called or []),
        "fallback_used": fallback_used,
        "structured_output": structured_output,
    }


def _base_document() -> dict:
    run_trace = [
        _trace("build_account_facts"),
        _trace("account_fit"),
        _trace("market_trend"),
        _trace("fundamental_valuation"),
        _trace("event_catalyst"),
        _trace("market_event_context"),
        _trace("build_card_pack"),
        _trace("bull_thesis"),
        _trace("bear_thesis"),
        _trace("bull_rebuttal"),
        _trace("bear_rebuttal"),
        _trace("debate_judge"),
        _trace("trade_plan"),
        _trace("compose_decision"),
        _trace("persist_decision"),
    ]
    card_pack = {
        "account_fact_snapshot": {"is_holding": False},
        "account_fit_card": {"summary": "account"},
        "market_trend_card": {"summary": "market"},
        "fundamental_valuation_card": {"summary": "fundamental"},
        "event_catalyst_card": {"summary": "event"},
        "market_event_context_card": {"summary": "events"},
        "bull_thesis_card": {"summary": "bull"},
        "bear_thesis_card": {"summary": "bear"},
        "bull_rebuttal_card": {"summary": "bull rebuttal"},
        "bear_rebuttal_card": {"summary": "bear rebuttal"},
        "debate_judge_card": {"asset_stance": "bullish", "conviction": "medium"},
        "trade_plan_card": {
            "portfolio_action": "add_on_pullback",
            "action_reason_type": "asset_view_and_account_fit",
            "risk_reward_assessment": {"entry_quality": "medium"},
        },
        "risk_reward_card": {
            "summary": "derived",
            "data_limitations": ["risk_reward_derived_from_trade_plan"],
        },
    }
    return {
        "id": "decision-1",
        "decision_type": "trade_decision",
        "symbol": "AAPL.US",
        "overall_score": 70,
        "rating": "positive",
        "action": "hold_no_add",
        "confidence": "medium",
        "decision_summary": "summary",
        "score_detail": {},
        "position_advice": {
            "current_position_pct": 0.0,
            "suggested_target_position_pct": 0.0,
            "max_position_pct": 0.08,
            "suggested_cash_amount": 0.0,
            "position_size_label": "none",
        },
        "execution_plan": {"should_act_now": False, "plan": [], "invalid_conditions": [], "recheck_triggers": []},
        "key_reasons": ["ok"],
        "major_risks": [],
        "review_warnings": [],
        "data_limitations": ["仓位上限约束"],
        "evidence_used": [],
        "card_pack": card_pack,
        "run_trace": run_trace,
        "metadata": {
            "account_data_source": "IBKR_ONLY",
            "trade_data_source": "IBKR_ONLY",
            "position_data_source": "IBKR_ONLY",
            "public_market_data_source": "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
            "risk_reward": {
                "source": "trade_plan",
                "standalone_node_enabled": False,
                "compat_card_enabled": True,
            },
        },
        "asset_debate": {"asset_stance": "bullish", "conviction": "medium"},
        "trade_plan": {
            "portfolio_action": "add_on_pullback",
            "action_reason_type": "asset_view_and_account_fit",
            "risk_reward_assessment": {"entry_quality": "medium"},
        },
        "risk_gate": {
            "original_action": "add_on_pullback",
            "final_action": "hold_no_add",
            "downgraded": True,
            "blocked": False,
            "gate_reasons": ["仓位上限约束"],
            "risk_flags": ["position_limit_reached"],
            "action_constraints": {"max_position_pct": 0.08},
        },
        "created_at": "2026-05-20T00:00:00+00:00",
        "updated_at": "2026-05-20T00:00:00+00:00",
    }


def test_complete_document_passes_quality_checks():
    result = TradeDecisionQualityEvaluator().evaluate(_base_document())

    assert result["passed"] is True
    assert result["score"] >= 75
    assert result["checks"]["risk_reward_source_integrity"]["passed"] is True
    assert "risk_reward" not in result["checks"]["graph_integrity"]["unexpected_nodes"]


def test_risk_reward_node_in_run_trace_is_hard_failure():
    doc = _base_document()
    doc["run_trace"].append(_trace("risk_reward"))

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert result["passed"] is False
    assert any("risk_reward" in item for item in result["hard_failures"])
    assert "unexpected_risk_reward_node" in result["flags"]


def test_tool_free_debate_and_trade_plan_nodes_calling_tools_is_hard_failure():
    doc = _base_document()
    for item in doc["run_trace"]:
        if item["node_name"] in {"bull_thesis", "trade_plan"}:
            item["tools_called"] = ["quote"]
            item["tool_call_count"] = 1

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert result["checks"]["data_source_integrity"]["passed"] is False
    assert result["hard_failures"]


def test_insufficient_data_with_add_batch_is_hard_failure():
    doc = _base_document()
    doc["asset_debate"]["asset_stance"] = "insufficient_data"
    doc["action"] = "add_batch"
    doc["risk_gate"]["final_action"] = "add_batch"

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert result["checks"]["asset_action_consistency"]["passed"] is False
    assert "insufficient_data_add_like" in result["hard_failures"]


def test_no_position_sell_or_reduce_is_hard_failure():
    doc = _base_document()
    doc["action"] = "sell"
    doc["risk_gate"]["final_action"] = "sell"

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert result["checks"]["position_consistency"]["passed"] is False
    assert "no_position_sell_or_reduce" in result["hard_failures"]


def test_target_exceeds_max_position_is_flagged():
    doc = _base_document()
    doc["position_advice"]["suggested_target_position_pct"] = 0.2
    doc["position_advice"]["max_position_pct"] = 0.1

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert "target_exceeds_max_position" in result["flags"]
    assert result["checks"]["position_consistency"]["passed"] is False


def test_missing_risk_gate_is_hard_failure():
    doc = _base_document()
    doc.pop("risk_gate")

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert result["checks"]["risk_gate_integrity"]["passed"] is False
    assert "risk_gate_missing" in result["hard_failures"]


def test_risk_gate_final_action_mismatch_is_hard_failure():
    doc = _base_document()
    doc["action"] = "add_batch"
    doc["risk_gate"]["final_action"] = "hold_no_add"

    result = TradeDecisionQualityEvaluator().evaluate(doc)

    assert "risk_gate_final_action_mismatch" in result["hard_failures"]
