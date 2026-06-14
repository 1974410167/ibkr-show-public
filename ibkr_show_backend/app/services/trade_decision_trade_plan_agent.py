"""LLM-powered trade plan agent for trade decision graph.

The agent translates asset-level debate output plus account facts into a draft
portfolio action. It never calls tools and its draft is still gated by the
deterministic Risk Gate inside TradeDecisionComposer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output import StructuredOutputRuntime
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    CardStance,
    DebateJudgeCard,
    TradeDecisionCardPack,
    TradeDecisionSubAgentTrace,
    TradePlanCard,
    build_fallback_trade_plan_card,
)
from app.agents.trade_decision_structured_outputs import build_trade_plan_contract
from app.services.trade_decision_composer import normalize_action


ALLOWED_TRADE_PLAN_ACTIONS = {
    "add",
    "add_small",
    "add_batch",
    "hold",
    "reduce",
    "reduce_batch",
    "sell",
    "wait",
    "avoid",
    "watchlist",
    "hold_no_add",
    "add_on_pullback",
    "add_right_side",
    "trim_on_rebound",
    "reduce_now",
    "sell_thesis_broken",
    "panic_blocked",
}
ADD_ACTIONS = {"add", "add_small", "add_batch", "add_on_pullback", "add_right_side"}
REDUCE_ACTIONS = {"reduce", "reduce_batch", "reduce_now", "trim_on_rebound"}
SELL_ACTIONS = {"sell", "sell_thesis_broken"}
PASSIVE_ACTIONS = {"hold", "hold_no_add", "wait", "watchlist", "avoid", "panic_blocked"}
VALID_STANCES = {"bullish", "neutral", "bearish", "insufficient_data"}
VALID_REASON_TYPES = {
    "asset_view",
    "asset_view_and_account_fit",
    "portfolio_risk_constraint",
    "insufficient_data",
    "event_risk_window",
    "thesis_broken",
    "panic_blocked",
    "no_action",
}


class TradeDecisionTradePlanAgent:
    max_tokens = 1800

    def __init__(
        self,
        llm_service: Any,
        monitoring_service: Any | None = None,
        prompt_service: Any | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.monitoring_service = monitoring_service
        self.prompt_service = prompt_service
        self.run_id = run_id
        self.task_id = task_id
        self._last_prompt_metadata: dict[str, Any] | None = None
        self.runtime = StructuredOutputRuntime(
            llm_service,
            monitoring_service=monitoring_service,
            default_temperature=0.0,
            default_max_tokens=self.max_tokens,
        )

    def generate(
        self,
        card_pack: TradeDecisionCardPack,
        debate_judge_card: DebateJudgeCard | dict | None,
    ) -> tuple[TradePlanCard, TradeDecisionSubAgentTrace]:
        context = self._build_context(card_pack, debate_judge_card)
        contract = build_trade_plan_contract()
        system_prompt = self._resolve_system_prompt()
        result = self.runtime.generate(
            self._messages(system_prompt, context),
            contract,
            temperature=0.0,
            max_tokens=self.max_tokens,
            context=context,
            run_id=self.run_id,
            task_id=self.task_id,
        )
        if not result.ok or result.payload is None:
            reason = f"{result.error_code or 'structured_output_failed'}: {result.error_message or ''}".strip()
            card = build_fallback_trade_plan_card(card_pack.symbol, card_pack.account_fact_snapshot, debate_judge_card, reason)
            return card, self._trace_from_result("fallback", result, reason, context)

        card = self._payload_to_card(card_pack, debate_judge_card, result.payload)
        return card, self._trace_from_result("completed", result, None, context, card)

    def _build_context(self, card_pack: TradeDecisionCardPack, debate_judge_card: DebateJudgeCard | dict | None) -> dict:
        snapshot = card_pack.account_fact_snapshot
        snapshot_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else (snapshot or {})
        account_context = snapshot_dict.get("account_context", {}) if isinstance(snapshot_dict, dict) else {}
        position_context = snapshot_dict.get("position_context", {}) if isinstance(snapshot_dict, dict) else {}
        trade_history = snapshot_dict.get("trade_history_context", {}) if isinstance(snapshot_dict, dict) else {}
        review_context = snapshot_dict.get("review_context", {}) if isinstance(snapshot_dict, dict) else {}

        account = {
            "is_holding": _get_snapshot_value(snapshot, "is_holding") or position_context.get("is_holding"),
            "quantity": _get_snapshot_value(snapshot, "quantity") or position_context.get("quantity"),
            "current_position_pct": _position_pct(snapshot),
            "market_value": _get_snapshot_value(snapshot, "market_value") or position_context.get("market_value"),
            "avg_cost": _get_snapshot_value(snapshot, "avg_cost") or position_context.get("avg_cost"),
            "unrealized_pnl": _get_snapshot_value(snapshot, "unrealized_pnl") or position_context.get("unrealized_pnl"),
            "cash": _get_snapshot_value(snapshot, "cash") or account_context.get("cash"),
            "net_liquidation": _get_snapshot_value(snapshot, "net_liquidation") or account_context.get("net_liquidation"),
            "deployable_liquidity": _get_snapshot_value(snapshot, "deployable_liquidity") or account_context.get("deployable_liquidity"),
            "deployable_liquidity_ratio": _get_snapshot_value(snapshot, "deployable_liquidity_ratio") or account_context.get("deployable_liquidity_ratio"),
            "top_positions": _compact_value(account_context.get("top_positions", _get_snapshot_value(snapshot, "top_positions", [])), list_limit=10),
            "position_concentration": _get_snapshot_value(snapshot, "position_concentration") or account_context.get("position_concentration"),
            "risk_concentration": _get_snapshot_value(snapshot, "risk_concentration") or account_context.get("risk_position_concentration_ex_cash_equivalents"),
            "global_mistake_tags": _compact_value(review_context.get("global_mistake_summary", _get_snapshot_value(snapshot, "global_mistake_tags", [])), list_limit=8),
            "latest_review": _compact_value(review_context.get("latest_review", _get_snapshot_value(snapshot, "latest_review", {}))),
            "recent_trades": _compact_value(trade_history.get("recent_trades", _get_snapshot_value(snapshot, "recent_trades", [])), list_limit=5),
        }

        return {
            "symbol": card_pack.symbol,
            "decision_type": card_pack.decision_type,
            "asset_debate": _compact_value(_card_dict(debate_judge_card) or {}),
            "ai_policy_assessment": _compact_value(card_pack.ai_policy_assessment or {}),
            "account": _compact_value(account),
            "evidence_cards": {
                "account_fit_card": _compact_card(card_pack.account_fit_card),
                "market_trend_card": _compact_card(card_pack.market_trend_card),
                "fundamental_valuation_card": _compact_card(card_pack.fundamental_valuation_card),
                "event_catalyst_card": _compact_card(card_pack.event_catalyst_card),
                "market_event_context_card": _compact_card(card_pack.market_event_context_card),
            },
            "allowed_actions": sorted(ALLOWED_TRADE_PLAN_ACTIONS),
        }

    def _payload_to_card(
        self,
        card_pack: TradeDecisionCardPack,
        debate_judge_card: DebateJudgeCard | dict | None,
        payload: dict[str, Any],
    ) -> TradePlanCard:
        snapshot = card_pack.account_fact_snapshot
        judge = _card_dict(debate_judge_card) or {}
        asset_stance = str(payload.get("asset_stance") or judge.get("asset_stance") or "insufficient_data").lower()
        if asset_stance not in VALID_STANCES:
            asset_stance = "insufficient_data"
        portfolio_action = normalize_action(str(payload.get("portfolio_action") or "watchlist"))
        if portfolio_action not in ALLOWED_TRADE_PLAN_ACTIONS:
            portfolio_action = "watchlist"
        reason_type = str(payload.get("action_reason_type") or "no_action").strip().lower()
        if reason_type not in VALID_REASON_TYPES:
            reason_type = "no_action"

        current_pct = _position_pct(snapshot)
        is_holding = bool(_get_snapshot_value(snapshot, "is_holding"))
        if not is_holding:
            current_pct = 0.0

        max_pct = self._resolve_max_position_pct(card_pack, current_pct, is_holding)
        target_pct = _to_float(payload.get("target_position_pct"), current_pct if is_holding else 0.0)
        target_pct = max(0.0, target_pct)
        notes: list[str] = []
        if target_pct > max_pct:
            target_pct = max_pct
            notes.append("target_position_pct_truncated_to_max_position_pct")

        ai_assessment = card_pack.ai_policy_assessment or {}
        ai_bias = str(ai_assessment.get("recommended_action_bias") or "").lower()
        ai_stance = str(ai_assessment.get("ai_position_stance") or "").lower()
        ai_target = _to_float(ai_assessment.get("ai_recommended_target_position_pct"), None)
        ai_range = ai_assessment.get("ai_recommended_target_position_range_pct")
        if portfolio_action in ADD_ACTIONS and ai_stance in {"overweight", "over_limit", "forbidden"}:
            portfolio_action = "hold_no_add" if is_holding else "watchlist"
            target_pct = current_pct if is_holding else 0.0
            reason_type = "portfolio_risk_constraint"
            notes.append(f"ai_policy_stance_{ai_stance}_downgraded_add")
        if portfolio_action in ADD_ACTIONS and ai_bias in {"hold_no_add", "avoid", "prefer_reduce"}:
            portfolio_action = "hold_no_add" if is_holding else "watchlist"
            target_pct = current_pct if is_holding else 0.0
            reason_type = "portfolio_risk_constraint"
            notes.append(f"ai_policy_bias_{ai_bias}_downgraded_add")
        elif portfolio_action in {"add", "add_batch", "add_right_side"} and ai_bias == "prefer_pullback_add":
            portfolio_action = "add_on_pullback"
            notes.append("ai_policy_bias_prefer_pullback_add_downgraded_strong_add")

        ai_supports_add = _ai_policy_supports_add(ai_assessment, current_pct) and _evidence_allows_ai_add(card_pack, asset_stance)
        if portfolio_action in PASSIVE_ACTIONS and ai_supports_add:
            portfolio_action = "add_on_pullback" if ai_bias == "prefer_pullback_add" else "add_small"
            reason_type = "asset_view_and_account_fit"
            notes.append("ai_policy_underweight_supports_action_promoted_from_hold_like")
        if portfolio_action in ADD_ACTIONS and ai_supports_add:
            calibrated_target = _ai_calibrated_target(current_pct, max_pct, ai_target, ai_range)
            if calibrated_target is not None and calibrated_target > target_pct:
                target_pct = calibrated_target
                notes.append("target_position_pct_aligned_to_ai_policy_range")

        if not is_holding and portfolio_action in REDUCE_ACTIONS | SELL_ACTIONS:
            portfolio_action = "avoid" if asset_stance == "bearish" else "watchlist"
            target_pct = 0.0
            reason_type = "no_action" if reason_type == "asset_view" else reason_type
            notes.append("non_holding_reduce_or_sell_downgraded")

        if asset_stance == "insufficient_data" and portfolio_action in ADD_ACTIONS:
            portfolio_action = "hold_no_add" if is_holding else "watchlist"
            target_pct = current_pct if is_holding else 0.0
            reason_type = "insufficient_data"
            notes.append("insufficient_data_add_downgraded")

        if asset_stance == "bearish" and is_holding and portfolio_action in ADD_ACTIONS:
            portfolio_action = "hold_no_add"
            target_pct = current_pct
            notes.append("bearish_holding_add_downgraded")

        if portfolio_action in ADD_ACTIONS and target_pct <= current_pct:
            portfolio_action = "hold_no_add" if is_holding else "watchlist"
            target_pct = current_pct if is_holding else 0.0
            notes.append("add_action_without_position_increase_downgraded")
        elif portfolio_action in REDUCE_ACTIONS and target_pct >= current_pct:
            portfolio_action = "hold_no_add" if is_holding else "watchlist"
            target_pct = current_pct if is_holding else 0.0
            notes.append("reduce_action_without_position_decrease_downgraded")
        elif portfolio_action in SELL_ACTIONS:
            target_pct = 0.0

        adjustment_pct = round(target_pct - current_pct, 6)
        suggested_cash = self._suggested_cash(snapshot, adjustment_pct, portfolio_action)
        assessment = self._risk_reward_assessment(card_pack, payload.get("risk_reward_assessment") or {}, notes)
        data_limitations = _list(payload.get("data_limitations"))
        data_limitations.extend(f"sanitized:{note}" for note in notes)

        return TradePlanCard(
            symbol=card_pack.symbol,
            asset_stance=asset_stance,
            portfolio_action=portfolio_action,
            action_reason_type=reason_type,
            current_position_pct=round(current_pct, 6),
            target_position_pct=round(target_pct, 6),
            adjustment_pct=adjustment_pct,
            suggested_cash_amount=suggested_cash,
            max_position_pct=round(max_pct, 6),
            execution_conditions=_list(payload.get("execution_conditions"), 8),
            invalidation_conditions=_list(payload.get("invalidation_conditions"), 8),
            recheck_triggers=_list(payload.get("recheck_triggers"), 8),
            risk_reward_assessment=assessment,
            data_limitations=_dedupe(data_limitations),
            summary=strip_thinking_tags(str(payload.get("summary") or "交易计划草案已生成，需经 Risk Gate 校验。"))[:1200],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _resolve_max_position_pct(self, card_pack: TradeDecisionCardPack, current_pct: float, is_holding: bool) -> float:
        ai_assessment = card_pack.ai_policy_assessment or {}
        ai_status = str(ai_assessment.get("status") or "")
        ai_max = _to_float(ai_assessment.get("ai_recommended_max_position_pct"), None)
        if ai_status == "evaluated" and ai_max is not None and ai_max >= 0:
            return ai_max
        thesis = card_pack.investment_thesis or {}
        thesis_role = str(thesis.get("role") or "unknown") if isinstance(thesis, dict) else "unknown"
        thesis_max = _to_float(thesis.get("max_position_pct") if isinstance(thesis, dict) else None, None)
        if thesis_role != "unknown" and thesis_max is not None and thesis_max >= 0:
            return thesis_max
        acc_max = _to_float(getattr(card_pack.account_fit_card, "max_suggested_position_pct", None), None)
        for value in (acc_max,):
            if value is not None and value >= 0:
                return value
        return current_pct if is_holding else 0.0

    def _suggested_cash(self, snapshot: AccountFactSnapshot | dict | None, adjustment_pct: float, action: str) -> float:
        net_liq = _to_float(_get_snapshot_value(snapshot, "net_liquidation"), 0.0) or 0.0
        if net_liq <= 0:
            return 0.0
        if action in ADD_ACTIONS:
            return round(max(adjustment_pct, 0.0) * net_liq, 2)
        if action in REDUCE_ACTIONS | SELL_ACTIONS:
            return round(abs(adjustment_pct) * net_liq, 2)
        return 0.0

    def _risk_reward_assessment(self, card_pack: TradeDecisionCardPack, raw: dict[str, Any], notes: list[str]) -> dict[str, Any]:
        market_event = card_pack.market_event_context_card
        assessment = dict(raw) if isinstance(raw, dict) else {}
        assessment.setdefault("entry_quality", "unknown")
        assessment.setdefault("upside_scenario", "")
        assessment.setdefault("downside_scenario", "")
        assessment["reward_risk_ratio"] = assessment.get("reward_risk_ratio")
        assessment["wait_for_pullback"] = bool(assessment.get("wait_for_pullback", False))
        assessment["pullback_entry_level"] = assessment.get("pullback_entry_level")
        assessment["invalidation_level"] = assessment.get("invalidation_level")
        assessment["trim_level"] = assessment.get("trim_level")
        risk_level = str(getattr(market_event, "risk_level", "") or "").lower()
        assessment["event_risk_window"] = risk_level if risk_level in {"high", "medium", "low"} else "unknown"
        existing_notes = _list(assessment.get("sanitization_notes"))
        assessment["sanitization_notes"] = _dedupe(existing_notes + notes)
        return assessment

    def _trace_from_result(
        self,
        status: str,
        result: Any | None,
        fallback_reason: str | None,
        context: dict,
        card: TradePlanCard | None = None,
    ) -> TradeDecisionSubAgentTrace:
        structured_output = _result_trace_payload(result) if result is not None else None
        llm_meta = ((result.metadata or {}).get("llm_call_metadata") if result is not None else {}) or {}
        token_usage = llm_meta.get("token_usage") if isinstance(llm_meta, dict) else {}
        prompt_metadata = {
            **(self._last_prompt_metadata or {}),
            "contract_name": "trade_decision_trade_plan",
            "context_card_count": sum(1 for value in (context.get("evidence_cards") or {}).values() if value),
            "asset_stance": card.asset_stance if card else (context.get("asset_debate") or {}).get("asset_stance"),
            "input_tokens": (token_usage or {}).get("prompt_tokens") or llm_meta.get("prompt_tokens") if isinstance(llm_meta, dict) else None,
            "output_tokens": (token_usage or {}).get("completion_tokens") or llm_meta.get("completion_tokens") if isinstance(llm_meta, dict) else None,
        }
        return TradeDecisionSubAgentTrace(
            sub_agent_name="trade_plan",
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=0,
            status=status,
            error=fallback_reason if status == "fallback" else None,
            rounds_used=1,
            tools_called=[],
            tool_call_count=0,
            tool_calls=[],
            runtime_trace=(structured_output or {}).get("trace", []),
            fallback_used=status == "fallback",
            fallback_reason=fallback_reason,
            prompt_metadata={key: value for key, value in prompt_metadata.items() if value is not None},
            structured_output=structured_output,
        )

    def _messages(self, system_prompt: str, context: dict) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]

    def _resolve_system_prompt(self) -> str:
        prompt, metadata = resolve_runtime_prompt(
            self.prompt_service,
            "trade_decision_trade_plan",
            TRADE_PLAN_PROMPT,
        )
        self._last_prompt_metadata = metadata
        return prompt


def _card_dict(card: Any) -> dict | None:
    if card is None:
        return None
    if hasattr(card, "to_dict"):
        return card.to_dict()
    if isinstance(card, dict):
        return card
    return None


def _ai_policy_supports_add(ai_assessment: dict[str, Any], current_pct: float) -> bool:
    if not isinstance(ai_assessment, dict) or ai_assessment.get("status") != "evaluated":
        return False
    stance = str(ai_assessment.get("ai_position_stance") or "").lower()
    bias = str(ai_assessment.get("recommended_action_bias") or "").lower()
    target = _to_float(ai_assessment.get("ai_recommended_target_position_pct"), None)
    if stance not in {"underweight", "no_position"}:
        return False
    if bias not in {"allow_add", "prefer_pullback_add"}:
        return False
    return target is not None and target > current_pct + 1e-6


def _evidence_allows_ai_add(card_pack: TradeDecisionCardPack, asset_stance: str) -> bool:
    if asset_stance not in {"bullish", "neutral"}:
        return False
    fund_status = str(getattr(card_pack.fundamental_valuation_card, "fundamental_status", None) or "unknown")
    trend_break = str(getattr(card_pack.market_trend_card, "trend_break_level", None) or "unknown")
    if fund_status in {"red", "orange"}:
        return False
    if trend_break in {"severe", "broken"}:
        return False
    fallback_count = 0
    for card in (
        card_pack.market_trend_card,
        card_pack.fundamental_valuation_card,
        card_pack.event_catalyst_card,
    ):
        if card is None or getattr(card, "stance", None) == CardStance.INSUFFICIENT_DATA:
            fallback_count += 1
    return fallback_count < 2


def _ai_calibrated_target(
    current_pct: float,
    max_pct: float,
    ai_target: float | None,
    ai_range: Any,
) -> float | None:
    target = ai_target
    if isinstance(ai_range, list) and len(ai_range) >= 2:
        low = _to_float(ai_range[0], None)
        high = _to_float(ai_range[1], None)
        if low is not None and high is not None:
            if target is None:
                target = low if current_pct < low else high
            else:
                target = min(max(target, low), high)
    if target is None or target <= current_pct + 1e-6:
        return None
    return round(min(target, max_pct), 6)


def _compact_card(card: Any) -> dict | None:
    value = _card_dict(card)
    if not value:
        return None
    return _compact_value(value)


def _compact_value(value: Any, *, max_text: int = 1200, list_limit: int = 8) -> Any:
    if isinstance(value, str):
        return strip_thinking_tags(value)[:max_text]
    if isinstance(value, list):
        return [_compact_value(item, max_text=max_text, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in list(value.items())[:30]:
            limit = 5 if key in {"upcoming_events", "macro_events", "symbol_events", "recent_trades"} else list_limit
            compact[str(key)] = _compact_value(item, max_text=max_text, list_limit=limit)
        return compact
    return value


def _get_snapshot_value(snapshot: AccountFactSnapshot | dict | None, key: str, default: Any = None) -> Any:
    if snapshot is None:
        return default
    if isinstance(snapshot, dict):
        if key in snapshot:
            return snapshot.get(key)
        for section in ("account_context", "position_context", "trade_history_context", "review_context"):
            sub = snapshot.get(section) or {}
            if isinstance(sub, dict) and key in sub:
                return sub.get(key)
        if key == "position_pct":
            return _get_snapshot_value(snapshot, "current_position_pct", default)
        return default
    if hasattr(snapshot, key):
        return getattr(snapshot, key)
    if key == "current_position_pct" and hasattr(snapshot, "position_pct"):
        return getattr(snapshot, "position_pct")
    return default


def _position_pct(snapshot: AccountFactSnapshot | dict | None) -> float:
    value = _get_snapshot_value(snapshot, "position_pct")
    if value is None:
        value = _get_snapshot_value(snapshot, "current_position_pct")
    return _to_float(value, 0.0) or 0.0


def _to_float(value: Any, default: float | None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _list(value: Any, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = [str(value)]
    return [strip_thinking_tags(str(item))[:1200] for item in items if item is not None][:limit]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _result_trace_payload(result: Any) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "repaired": result.repaired,
        "repair_attempts": result.repair_attempts,
        "fallback_used": result.fallback_used,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "metadata": result.metadata,
        "trace": [
            {
                "event": item.get("event"),
                "contract": item.get("contract"),
                "ok": item.get("ok"),
                "error_code": item.get("error_code"),
                "repair_attempt": item.get("repair_attempt"),
                "created_at": item.get("created_at"),
            }
            for item in (result.trace or [])
        ],
    }


TRADE_PLAN_PROMPT = """你是交易计划 Agent。你的任务是把“标的级观点”结合“真实账户上下文”翻译成“账户动作草案”。
风险收益评估由你基于多空裁判、账户事实、市场趋势、基本面、事件催化和重点事件生成；不要依赖独立 risk_reward 节点或风险收益卡。

你必须先区分：
1. 标的观点 asset_stance: bullish | neutral | bearish | insufficient_data
2. 账户动作 portfolio_action: 建仓、加仓、持有、持有不加仓、减仓、清仓、等待、观察、回避
3. 动作原因 action_reason_type: asset_view | asset_view_and_account_fit | portfolio_risk_constraint | insufficient_data | event_risk_window | thesis_broken | panic_blocked | no_action
4. AI 仓位评估 ai_policy_assessment: 这是 AI 独立仓位建议，不是用户偏好；若 status=evaluated，max_position_pct 和 target_position_pct 应优先参考它。

禁止：
- 编造账户数据、行情、财报、新闻、宏观事件
- 调用工具、MCP、repository 或外部数据
- 输出 Markdown 或真实下单指令
- 暗示系统会自动交易
- 无持仓时输出 reduce / sell / reduce_now / sell_thesis_broken
- 数据不足时输出激进加仓
- 目标仓位超过 max_position_pct
- ai_policy_assessment.status=evaluated 时，目标仓位超过 ai_recommended_max_position_pct
- ai_policy_assessment.recommended_action_bias=hold_no_add/avoid/prefer_reduce 时仍输出激进加仓
- ai_policy_assessment 显示 underweight/no_position 且 allow_add/prefer_pullback_add 时，无明确阻断原因却输出 hold/watchlist
- asset_stance=bearish 且已有持仓时建议加仓
- asset_stance=insufficient_data 时给出强方向动作

必须：
- 只输出 JSON object
- portfolio_action 必须来自 allowed_actions
- 给出 current_position_pct、target_position_pct、adjustment_pct、max_position_pct、suggested_cash_amount
- 给出 execution_conditions、invalidation_conditions、recheck_triggers
- 给出 risk_reward_assessment，至少包含 entry_quality、upside_scenario、downside_scenario、reward_risk_ratio、wait_for_pullback、pullback_entry_level、invalidation_level、trim_level、event_risk_window、sanitization_notes
- 如果输出 hold_no_add，summary 或 risk_reward_assessment.sanitization_notes 必须说明明确阻断原因
- 如果输出 watchlist，summary 必须说明缺少哪些条件才能变成 add_small
- 不得绕过 Risk Gate；你的输出是 draft action，最终动作仍由 Risk Gate 校验

动作映射：
- add_small：证据支持小幅提高仓位，适合 underweight 且风险收益合格但不需要追涨。
- add_on_pullback：AI 支持加仓但催化偏弱、趋势 warning、估值或事件窗口需要更好买点；这是有条件动作，不等同于 hold。
- add_right_side：趋势突破/右侧确认强，且基本面、风险收益、仓位空间都支持。
- bullish 无持仓：账户适配良好且置信度中高可 add_small/add_batch/add_on_pullback/add_right_side；事件高风险优先 add_on_pullback/watchlist；现金不足 watchlist/avoid。
- bullish 已持仓：低于上限才可加仓；接近或超过上限、集中度高或事件风险高时 hold_no_add。
- 若 AI 仓位评估 recommended_action_bias=prefer_pullback_add，加仓只能使用 add_on_pullback 或更保守动作；若为 hold_no_add/avoid/prefer_reduce，禁止加仓。
- 若 AI 仓位评估 ai_position_stance=underweight/no_position 且 recommended_action_bias=allow_add/prefer_pullback_add，且 asset_stance=bullish 或 neutral、基本面非 red/orange、趋势非 severe/broken、公开数据非大面积 fallback，则不应默认 hold/watchlist；优先 add_small 或 add_on_pullback。
- 若 AI 仓位评估 ai_position_stance=near_target，可以 hold，但必须说明“接近 AI 建议仓位，不需要新增资金”。
- 若 AI 仓位评估 ai_position_stance=overweight/over_limit，禁止 add_like，按风险输出 hold_no_add、trim_on_rebound 或 reduce_now。
- target_position_pct 优先落在 ai_recommended_target_position_range_pct 内，且不得超过 ai_recommended_max_position_pct；如现金或 Risk Gate 约束导致不能达到 AI target，需要在 summary 或 sanitization_notes 说明。
- neutral 无持仓：watchlist/wait/avoid；已持仓：hold/hold_no_add，仓位过高且风险明显可 trim_on_rebound/reduce_batch，原因应是 portfolio_risk_constraint。
- bearish 无持仓：avoid/watchlist；已持仓：reduce_batch/reduce_now/sell_thesis_broken/trim_on_rebound。
- insufficient_data 无持仓：watchlist/wait/avoid 且 target_position_pct=0；已持仓：hold_no_add，仓位过高可 reduce_batch，但原因必须是 portfolio_risk_constraint 或 insufficient_data。

输出示例（无持仓观察）:
{"asset_stance":"neutral","portfolio_action":"watchlist","action_reason_type":"no_action","current_position_pct":0.0,"target_position_pct":0.0,"adjustment_pct":0.0,"suggested_cash_amount":0.0,"max_position_pct":0.05,"execution_conditions":["等待财报或关键事件落地","价格回撤后风险收益改善再复查"],"invalidation_conditions":["标的级观点转为 bearish","公开数据继续不足"],"recheck_triggers":["下一次财报发布","事件风险解除","趋势相对基准重新转强"],"risk_reward_assessment":{"entry_quality":"unknown","upside_scenario":"催化兑现且趋势延续时再评估小仓位试探","downside_scenario":"催化不及预期或估值压缩导致继续回撤","reward_risk_ratio":null,"wait_for_pullback":true,"pullback_entry_level":null,"invalidation_level":null,"trim_level":null,"event_risk_window":"medium","sanitization_notes":[]},"data_limitations":[],"summary":"无持仓且标的观点中性，当前不生成买入动作，先纳入观察并等待更清晰的催化或回撤机会。"}

输出示例（已持仓但不加仓）:
{"asset_stance":"bullish","portfolio_action":"hold_no_add","action_reason_type":"portfolio_risk_constraint","current_position_pct":0.08,"target_position_pct":0.08,"adjustment_pct":0.0,"suggested_cash_amount":0.0,"max_position_pct":0.08,"execution_conditions":["继续持有但不加仓","若价格回撤且仓位上限提高再复查"],"invalidation_conditions":["asset_stance 降为 bearish","核心基本面或趋势证据失效"],"recheck_triggers":["仓位占比下降","财报确认增长","事件风险解除"],"risk_reward_assessment":{"entry_quality":"fair","upside_scenario":"趋势延续且财报兑现时保留已有仓位收益","downside_scenario":"估值压缩或事件风险触发回撤","reward_risk_ratio":1.4,"wait_for_pullback":true,"pullback_entry_level":null,"invalidation_level":null,"trim_level":null,"event_risk_window":"medium","sanitization_notes":[]},"data_limitations":[],"summary":"标的观点偏多但当前仓位已达到建议上限，因此动作应为持有不加仓，而不是继续提高敞口。"}
"""
