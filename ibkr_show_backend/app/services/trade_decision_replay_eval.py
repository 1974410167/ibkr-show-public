"""Trade Decision Replay Eval - offline deterministic re-evaluation of
historical decisions against the current rules.

This module re-runs the composer + risk gate on a saved scenario / card pack
and compares the resulting action / risk_gate reasons against the original
decision. It is intentionally deterministic and does NOT call LLM or IBKR.

Inputs:
  - replay_scenario: a dict or TradeDecisionCardPack with all the cards
    the composer needs to run.
  - original_action: the action that the historical decision produced.
  - original_risk_flags / risk_gate_reasons (optional): what the original
    run surfaced for explainability.

Output:
  ReplayEvalResult with replay_id, original_action, replay_action,
  action_changed, rule_violations, risk_gate_reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    CardStance,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
)
from app.services.trade_decision_composer import TradeDecisionComposer
from app.services.trade_decision_risk_gate import apply_risk_gate


# Hard rules that the replay eval enforces. These are the "must-have" gates
# that any historical decision should have satisfied. A violation means the
# original decision would have been rejected by today's rules.
HARD_RULES = (
    "no_add_without_max_position_pct",
    "no_add_without_invalidation_conditions",
    "no_add_on_insufficient_data",
    "no_add_on_weak_catalyst",
    "no_add_at_position_limit",
    "panic_block_on_panic_sell",
    "no_add_on_severe_trend_break",
    "no_add_on_extreme_risk_without_thesis",
)


@dataclass
class ReplayEvalResult:
    replay_id: str
    symbol: str
    decision_type: str
    original_action: str
    replay_action: str
    action_changed: bool
    rule_violations: list[dict] = field(default_factory=list)
    risk_gate_reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    reward_risk_ratio: float | None = None
    downside_risk_pct: float | None = None
    upside_potential_pct: float | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "symbol": self.symbol,
            "decision_type": self.decision_type,
            "original_action": self.original_action,
            "replay_action": self.replay_action,
            "action_changed": self.action_changed,
            "rule_violations": list(self.rule_violations),
            "risk_gate_reasons": list(self.risk_gate_reasons),
            "risk_flags": list(self.risk_flags),
            "reward_risk_ratio": self.reward_risk_ratio,
            "downside_risk_pct": self.downside_risk_pct,
            "upside_potential_pct": self.upside_potential_pct,
            "summary": self.summary,
        }


class TradeDecisionReplayEval:
    """Offline deterministic re-evaluator for historical trade decisions."""

    def __init__(self, composer: TradeDecisionComposer | None = None) -> None:
        self.composer = composer or TradeDecisionComposer()

    def evaluate(
        self,
        *,
        replay_id: str,
        card_pack: TradeDecisionCardPack,
        original_action: str,
        user_question: str | None = None,
    ) -> ReplayEvalResult:
        # 1. Re-run composer + risk gate on the card pack.
        output = self.composer.compose(card_pack)
        _, gate = apply_risk_gate(output, card_pack, user_question=user_question)

        replay_action = str(output.get("action") or "watchlist")
        original_action_norm = (original_action or "").strip().lower()

        # 2. Diff
        action_changed = original_action_norm != replay_action

        # 3. Rule violations: a violation is a rule that the current gate
        # enforces but the original action would have violated. Concretely,
        # if the original action was more aggressive (add/add_batch) and
        # the current gate produced a downgrade, that's a violation.
        violations: list[dict[str, Any]] = []
        add_like = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
        if original_action_norm in add_like:
            for flag in gate.risk_flags:
                rule = _map_flag_to_rule(flag)
                if rule:
                    violations.append({
                        "rule": rule,
                        "flag": flag,
                        "reason": "; ".join(gate.gate_reasons[:2]) if gate.gate_reasons else flag,
                    })
        # Also flag if the original action was sell but the gate produced panic_blocked
        if original_action_norm in {"sell", "sell_thesis_broken", "reduce"} and "panic_sell_blocked" in gate.risk_flags:
            violations.append({
                "rule": "panic_block_on_panic_sell",
                "flag": "panic_sell_blocked",
                "reason": "原 action 包含 sell，但当前规则将认定为 panic_blocked",
            })

        result = ReplayEvalResult(
            replay_id=replay_id,
            symbol=card_pack.symbol,
            decision_type=card_pack.decision_type,
            original_action=original_action_norm or "unknown",
            replay_action=replay_action,
            action_changed=action_changed,
            rule_violations=violations,
            risk_gate_reasons=list(gate.gate_reasons),
            risk_flags=list(gate.risk_flags),
        )
        # Pull R/R ratio + upside/downside from the card pack's rr card
        rr = card_pack.risk_reward_card
        if rr is not None:
            result.reward_risk_ratio = rr.reward_risk_ratio
            result.upside_potential_pct = rr.upside_potential_pct
            result.downside_risk_pct = rr.downside_risk_pct

        if action_changed:
            result.summary = (
                f"原 action={original_action_norm} → 现 action={replay_action} "
                f"({len(violations)} rule violation)"
            )
        else:
            result.summary = f"原 action={replay_action} 与现规则一致"

        return result

    def evaluate_from_replay_snapshot(
        self,
        *,
        replay_id: str,
        snapshot: dict,
        original_action: str,
        user_question: str | None = None,
    ) -> ReplayEvalResult:
        """Convenience: build a card pack from a dict snapshot and replay it.

        Expected snapshot keys:
          - decision_type, symbol, user_question
          - account_facts: dict for AccountFactSnapshot
          - account_fit, market_trend, fundamental, event_catalyst, risk_reward:
            optional dicts for the corresponding cards
        """
        card_pack = _build_card_pack_from_dict(snapshot)
        return self.evaluate(
            replay_id=replay_id,
            card_pack=card_pack,
            original_action=original_action,
            user_question=user_question or snapshot.get("user_question"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_flag_to_rule(flag: str) -> str | None:
    mapping = {
        "missing_position_limit": "no_add_without_max_position_pct",
        "missing_invalidation_conditions": "no_add_without_invalidation_conditions",
        "insufficient_data": "no_add_on_insufficient_data",
        "weak_catalyst_downgrade": "no_add_on_weak_catalyst",
        "position_limit_reached": "no_add_at_position_limit",
        "trend_break_severe_blocked": "no_add_on_severe_trend_break",
        "thesis_extreme_risk_blocked": "no_add_on_extreme_risk_without_thesis",
    }
    return mapping.get(flag)


def _build_card_pack_from_dict(snapshot: dict) -> TradeDecisionCardPack:
    """Best-effort builder for a TradeDecisionCardPack from a dict."""
    symbol = str(snapshot.get("symbol") or "")
    decision_type = str(snapshot.get("decision_type") or "entry_decision")
    user_question = snapshot.get("user_question")

    # Account fact snapshot
    af = snapshot.get("account_facts") or {}
    acc_snap = AccountFactSnapshot(
        decision_type=decision_type,
        symbol=symbol,
        normalized_symbol=symbol,
        user_question=user_question,
        net_liquidation=af.get("net_liquidation"),
        cash=af.get("cash"),
        deployable_liquidity=af.get("deployable_liquidity"),
        deployable_liquidity_ratio=af.get("deployable_liquidity_ratio"),
        total_position_value=af.get("total_position_value"),
        top_positions=af.get("top_positions", []) or [],
        position_concentration=af.get("position_concentration"),
        risk_concentration=af.get("risk_concentration"),
        margin_info=af.get("margin_info"),
        is_holding=bool(af.get("is_holding")),
        quantity=af.get("quantity"),
        avg_cost=af.get("avg_cost"),
        current_price=af.get("current_price"),
        market_value=af.get("market_value"),
        position_pct=af.get("position_pct"),
        unrealized_pnl=af.get("unrealized_pnl"),
        unrealized_pnl_pct=af.get("unrealized_pnl_pct"),
        realized_pnl=af.get("realized_pnl"),
        recent_trades=af.get("recent_trades", []) or [],
        first_buy_date=af.get("first_buy_date"),
        last_trade_date=af.get("last_trade_date"),
        holding_days=af.get("holding_days"),
        latest_review=af.get("latest_review"),
        global_mistake_tags=af.get("global_mistake_tags", []) or [],
        data_quality=af.get("data_quality", {}) or {},
    )

    def _card_from_dict(card_cls, defaults: dict, data: dict | None) -> Any:
        data = data or {}
        kwargs = dict(defaults)
        kwargs["symbol"] = symbol
        kwargs["decision_type"] = decision_type
        kwargs["summary"] = data.get("summary") or ""
        for k, v in data.items():
            if k in {"symbol", "decision_type", "summary", "to_dict"}:
                continue
            kwargs[k] = v
        return card_cls(**kwargs)

    acc_card = _card_from_dict(
        AccountFitCard,
        {"card_type": "account_fit", "score": 0, "max_score": 20,
         "stance": CardStance.INSUFFICIENT_DATA, "account_fit_level": "unknown",
         "evidence_quality": "low", "source_tools": []},
        snapshot.get("account_fit"),
    )
    mkt_card = _card_from_dict(
        MarketTrendCard,
        {"card_type": "market_trend", "score": 0, "max_score": 15,
         "stance": CardStance.INSUFFICIENT_DATA, "price_trend": "unknown",
         "evidence_quality": "low", "source_tools": [],
         "trend_break_level": "unknown", "support_levels": [], "resistance_levels": []},
        snapshot.get("market_trend"),
    )
    fund_card = _card_from_dict(
        FundamentalValuationCard,
        {"card_type": "fundamental_valuation", "score": 0, "max_score": 35,
         "stance": CardStance.INSUFFICIENT_DATA, "evidence_quality": "low",
         "source_tools": [], "data_limitations": []},
        snapshot.get("fundamental"),
    )
    evt_card = _card_from_dict(
        EventCatalystCard,
        {"card_type": "event_catalyst", "score": 0, "max_score": 5,
         "stance": CardStance.INSUFFICIENT_DATA, "sentiment": "neutral",
         "catalyst_strength": "neutral", "evidence_quality": "low", "source_tools": []},
        snapshot.get("event_catalyst"),
    )
    rr_card = _card_from_dict(
        RiskRewardCard,
        {"card_type": "risk_reward", "score": 0, "max_score": 15,
         "stance": CardStance.INSUFFICIENT_DATA, "wait_for_pullback": False,
         "wait_for_pullback_pct": None, "pullback_entry_level": None,
         "action_guidance": None,
         "position_size_label": "unknown", "evidence_quality": "low",
         "source_tools": [], "key_risks": [], "key_opportunities": [],
         "downside_scenarios": [], "upside_scenarios": []},
        snapshot.get("risk_reward"),
    )

    return TradeDecisionCardPack(
        decision_type=decision_type,
        symbol=symbol,
        account_fact_snapshot=acc_snap,
        account_fit_card=acc_card,
        market_trend_card=mkt_card,
        fundamental_valuation_card=fund_card,
        event_catalyst_card=evt_card,
        risk_reward_card=rr_card,
        investment_thesis=snapshot.get("investment_thesis"),
    )


__all__ = [
    "ReplayEvalResult",
    "TradeDecisionReplayEval",
    "HARD_RULES",
]
