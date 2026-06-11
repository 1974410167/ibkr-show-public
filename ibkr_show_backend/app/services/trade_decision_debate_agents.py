"""LLM-powered bull/bear debate agents for trade decision analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.structured_output import StructuredOutputRuntime
from app.agents.trade_decision_cards import (
    DebateJudgeCard,
    DebateRebuttalCard,
    DebateThesisCard,
    TradeDecisionCardPack,
    TradeDecisionSubAgentTrace,
    build_fallback_debate_judge_card,
    build_fallback_debate_rebuttal_card,
    build_fallback_debate_thesis_card,
)
from app.agents.trade_decision_structured_outputs import (
    build_debate_judge_contract,
    build_debate_rebuttal_contract,
    build_debate_thesis_contract,
)

ALLOWED_EVIDENCE_REFS = {
    "account_fit_card",
    "market_trend_card",
    "fundamental_valuation_card",
    "event_catalyst_card",
    "market_event_context_card",
    "account_fact_snapshot",
}
_VALID_CONVICTIONS = {"high", "medium", "low"}
_VALID_ASSET_STANCES = {"bullish", "neutral", "bearish", "insufficient_data"}
_VALID_WINNERS = {"bull", "bear", "balanced", "insufficient_data"}


class TradeDecisionDebateAgentBase:
    """Base helper for non-tool structured-output debate agents."""

    max_tokens = 1400

    def __init__(
        self,
        llm_service: Any,
        *,
        monitoring_service: Any | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.monitoring_service = monitoring_service
        self.run_id = run_id
        self.task_id = task_id
        self.runtime = StructuredOutputRuntime(
            llm_service,
            monitoring_service=monitoring_service,
            default_temperature=0.0,
            default_max_tokens=self.max_tokens,
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _safe_card_dict(self, card: Any) -> dict | None:
        if card is None:
            return None
        if hasattr(card, "to_dict"):
            value = card.to_dict()
        elif isinstance(card, dict):
            value = card
        else:
            return None
        return _compact_dict(value)

    def _card_pack_context(self, card_pack: TradeDecisionCardPack) -> dict:
        snapshot = card_pack.account_fact_snapshot
        snapshot_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else (snapshot or {})
        account_context = snapshot_dict.get("account_context", {}) if isinstance(snapshot_dict, dict) else {}
        position_context = snapshot_dict.get("position_context", {}) if isinstance(snapshot_dict, dict) else {}
        trade_history = snapshot_dict.get("trade_history_context", {}) if isinstance(snapshot_dict, dict) else {}
        review_context = snapshot_dict.get("review_context", {}) if isinstance(snapshot_dict, dict) else {}

        return {
            "symbol": card_pack.symbol,
            "decision_type": card_pack.decision_type,
            "account_fact_snapshot": {
                "is_holding": position_context.get("is_holding", _get(snapshot, "is_holding")),
                "current_position_pct": position_context.get("position_pct", _get(snapshot, "position_pct")),
                "unrealized_pnl": position_context.get("unrealized_pnl", _get(snapshot, "unrealized_pnl")),
                "cash": account_context.get("cash", _get(snapshot, "cash")),
                "top_positions": _limit_list(account_context.get("top_positions", _get(snapshot, "top_positions", [])), 8),
                "global_mistake_tags": _limit_list(review_context.get("global_mistake_summary", _get(snapshot, "global_mistake_tags", [])), 8),
                "recent_trades": _limit_list(trade_history.get("recent_trades", _get(snapshot, "recent_trades", [])), 5),
            },
            "cards": {
                "account_fit_card": self._safe_card_dict(card_pack.account_fit_card),
                "market_trend_card": self._safe_card_dict(card_pack.market_trend_card),
                "fundamental_valuation_card": self._safe_card_dict(card_pack.fundamental_valuation_card),
                "event_catalyst_card": self._safe_card_dict(card_pack.event_catalyst_card),
                "market_event_context_card": self._safe_card_dict(card_pack.market_event_context_card),
            },
            "allowed_evidence_refs": sorted(ALLOWED_EVIDENCE_REFS),
        }

    def _build_common_context(self, card_pack: TradeDecisionCardPack, **extra: Any) -> dict:
        context = self._card_pack_context(card_pack)
        context.update(extra)
        return context

    def _result_to_trace_payload(self, result: Any) -> dict:
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

    def _trace_from_result(self, agent_name: str, status: str, result: Any | None, fallback_reason: str | None = None) -> TradeDecisionSubAgentTrace:
        structured_output = self._result_to_trace_payload(result) if result is not None else None
        return TradeDecisionSubAgentTrace(
            sub_agent_name=agent_name,
            started_at=self._now(),
            finished_at=self._now(),
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
            structured_output=structured_output,
            prompt_metadata={"contract_name": (result.metadata.get("contract_name") if result is not None else None)},
        )

    def _messages(self, system_prompt: str, context: dict) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]


class BullThesisAgent(TradeDecisionDebateAgentBase):
    max_tokens = 1600

    def generate(self, card_pack: TradeDecisionCardPack) -> tuple[DebateThesisCard, TradeDecisionSubAgentTrace]:
        return _generate_thesis(
            self,
            card_pack,
            node_name="bull_thesis",
            stance="bullish",
            system_prompt=BULL_THESIS_PROMPT,
        )


class BearThesisAgent(TradeDecisionDebateAgentBase):
    max_tokens = 1600

    def generate(self, card_pack: TradeDecisionCardPack) -> tuple[DebateThesisCard, TradeDecisionSubAgentTrace]:
        return _generate_thesis(
            self,
            card_pack,
            node_name="bear_thesis",
            stance="bearish",
            system_prompt=BEAR_THESIS_PROMPT,
        )


class BullRebuttalAgent(TradeDecisionDebateAgentBase):
    max_tokens = 1300

    def generate(
        self,
        card_pack: TradeDecisionCardPack,
        bull_thesis: DebateThesisCard,
        bear_thesis: DebateThesisCard,
    ) -> tuple[DebateRebuttalCard, TradeDecisionSubAgentTrace]:
        return _generate_rebuttal(
            self,
            card_pack,
            bull_thesis,
            bear_thesis,
            node_name="bull_rebuttal",
            system_prompt=BULL_REBUTTAL_PROMPT,
        )


class BearRebuttalAgent(TradeDecisionDebateAgentBase):
    max_tokens = 1300

    def generate(
        self,
        card_pack: TradeDecisionCardPack,
        bull_thesis: DebateThesisCard,
        bear_thesis: DebateThesisCard,
    ) -> tuple[DebateRebuttalCard, TradeDecisionSubAgentTrace]:
        return _generate_rebuttal(
            self,
            card_pack,
            bull_thesis,
            bear_thesis,
            node_name="bear_rebuttal",
            system_prompt=BEAR_REBUTTAL_PROMPT,
        )


class DebateJudgeAgent(TradeDecisionDebateAgentBase):
    max_tokens = 1600

    def generate(
        self,
        card_pack: TradeDecisionCardPack,
        bull_thesis: DebateThesisCard,
        bear_thesis: DebateThesisCard,
        bull_rebuttal: DebateRebuttalCard,
        bear_rebuttal: DebateRebuttalCard,
    ) -> tuple[DebateJudgeCard, TradeDecisionSubAgentTrace]:
        context = self._build_common_context(
            card_pack,
            bull_thesis=self._safe_card_dict(bull_thesis),
            bear_thesis=self._safe_card_dict(bear_thesis),
            bull_rebuttal=self._safe_card_dict(bull_rebuttal),
            bear_rebuttal=self._safe_card_dict(bear_rebuttal),
        )
        contract = build_debate_judge_contract()
        result = self.runtime.generate(
            self._messages(DEBATE_JUDGE_PROMPT, context),
            contract,
            temperature=0.0,
            max_tokens=self.max_tokens,
            context=context,
            run_id=self.run_id,
            task_id=self.task_id,
        )
        if not result.ok or result.payload is None:
            reason = f"{result.error_code or 'structured_output_failed'}: {result.error_message or ''}".strip()
            return build_fallback_debate_judge_card(card_pack.symbol, reason, insufficient_data=True), self._trace_from_result("debate_judge", "fallback", result, reason)
        card = _payload_to_judge_card(card_pack.symbol, result.payload)
        return card, self._trace_from_result("debate_judge", "completed", result)


def _generate_thesis(
    agent: TradeDecisionDebateAgentBase,
    card_pack: TradeDecisionCardPack,
    *,
    node_name: str,
    stance: str,
    system_prompt: str,
) -> tuple[DebateThesisCard, TradeDecisionSubAgentTrace]:
    context = agent._build_common_context(card_pack)
    contract = build_debate_thesis_contract(node_name)
    result = agent.runtime.generate(
        agent._messages(system_prompt, context),
        contract,
        temperature=0.0,
        max_tokens=agent.max_tokens,
        context=context,
        run_id=agent.run_id,
        task_id=agent.task_id,
    )
    if not result.ok or result.payload is None:
        reason = f"{result.error_code or 'structured_output_failed'}: {result.error_message or ''}".strip()
        return build_fallback_debate_thesis_card(card_pack.symbol, node_name, reason), agent._trace_from_result(node_name, "fallback", result, reason)
    card = _payload_to_thesis_card(card_pack.symbol, result.payload, node_name=node_name, stance=stance)
    return card, agent._trace_from_result(node_name, "completed", result)


def _generate_rebuttal(
    agent: TradeDecisionDebateAgentBase,
    card_pack: TradeDecisionCardPack,
    bull_thesis: DebateThesisCard,
    bear_thesis: DebateThesisCard,
    *,
    node_name: str,
    system_prompt: str,
) -> tuple[DebateRebuttalCard, TradeDecisionSubAgentTrace]:
    context = agent._build_common_context(
        card_pack,
        bull_thesis=agent._safe_card_dict(bull_thesis),
        bear_thesis=agent._safe_card_dict(bear_thesis),
    )
    contract = build_debate_rebuttal_contract(node_name)
    result = agent.runtime.generate(
        agent._messages(system_prompt, context),
        contract,
        temperature=0.0,
        max_tokens=agent.max_tokens,
        context=context,
        run_id=agent.run_id,
        task_id=agent.task_id,
    )
    if not result.ok or result.payload is None:
        reason = f"{result.error_code or 'structured_output_failed'}: {result.error_message or ''}".strip()
        return build_fallback_debate_rebuttal_card(card_pack.symbol, node_name, reason), agent._trace_from_result(node_name, "fallback", result, reason)
    card = _payload_to_rebuttal_card(card_pack.symbol, result.payload, node_name=node_name)
    return card, agent._trace_from_result(node_name, "completed", result)


def _payload_to_thesis_card(symbol: str, payload: dict, *, node_name: str, stance: str) -> DebateThesisCard:
    return DebateThesisCard(
        symbol=symbol,
        agent_name=node_name,
        stance=stance,
        conviction=_valid_choice(payload.get("conviction"), _VALID_CONVICTIONS, "low"),
        summary=strip_thinking_tags(str(payload.get("summary") or "")),
        core_claims=_list(payload.get("core_claims")),
        evidence_refs=[ref for ref in _list(payload.get("evidence_refs")) if ref in ALLOWED_EVIDENCE_REFS],
        weak_points=_list(payload.get("weak_points")),
        risk_flags=_list(payload.get("risk_flags")),
        data_limitations=_list(payload.get("data_limitations")),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _payload_to_rebuttal_card(symbol: str, payload: dict, *, node_name: str) -> DebateRebuttalCard:
    return DebateRebuttalCard(
        symbol=symbol,
        agent_name=node_name,
        summary=strip_thinking_tags(str(payload.get("summary") or "")),
        accepted_opponent_points=_list(payload.get("accepted_opponent_points")),
        rejected_opponent_points=_list(payload.get("rejected_opponent_points")),
        reinforced_arguments=_list(payload.get("reinforced_arguments")),
        final_conviction=_valid_choice(payload.get("final_conviction"), _VALID_CONVICTIONS, "low"),
        data_limitations=_list(payload.get("data_limitations")),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _payload_to_judge_card(symbol: str, payload: dict) -> DebateJudgeCard:
    return DebateJudgeCard(
        symbol=symbol,
        asset_stance=_valid_choice(payload.get("asset_stance"), _VALID_ASSET_STANCES, "insufficient_data"),
        conviction=_valid_choice(payload.get("conviction"), _VALID_CONVICTIONS, "low"),
        winner=_valid_choice(payload.get("winner"), _VALID_WINNERS, "balanced"),
        accepted_bull_points=_list(payload.get("accepted_bull_points")),
        accepted_bear_points=_list(payload.get("accepted_bear_points")),
        key_uncertainties=_list(payload.get("key_uncertainties")),
        reasoning_summary=strip_thinking_tags(str(payload.get("reasoning_summary") or "")),
        data_limitations=_list(payload.get("data_limitations")),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _valid_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").lower()
    return text if text in allowed else default


def _list(value: Any, limit: int = 10) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = [str(value)]
    return [strip_thinking_tags(str(item))[:1200] for item in items if item is not None][:limit]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _compact_dict(value: dict, *, max_text: int = 1200) -> dict:
    keep = {
        "summary", "score", "max_score", "stance", "key_points", "risks", "opportunities",
        "data_limitations", "evidence_quality", "source_tools", "account_fit_level",
        "price_trend", "relative_to_benchmark", "recent_return_pct", "volatility_summary",
        "company_name", "pe_ttm", "forward_pe", "market_cap", "valuation_summary",
        "revenue_growth_summary", "profitability_summary", "sentiment", "catalyst_strength",
        "key_events", "risk_events", "risk_level", "upcoming_events", "macro_events",
        "symbol_events", "key_risks", "key_opportunities", "risk_assessment_reason",
        "reward_risk_ratio", "agent_name", "conviction", "core_claims", "evidence_refs",
        "weak_points", "risk_flags", "accepted_opponent_points", "rejected_opponent_points",
        "reinforced_arguments", "final_conviction", "asset_stance", "winner",
        "accepted_bull_points", "accepted_bear_points", "key_uncertainties",
        "reasoning_summary",
    }
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if key not in keep:
            continue
        compact[key] = _compact_value(item, max_text=max_text, event_limit=5 if key in {"upcoming_events", "macro_events", "symbol_events"} else 8)
    return compact


def _compact_value(value: Any, *, max_text: int, event_limit: int) -> Any:
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, list):
        return [_compact_value(item, max_text=max_text, event_limit=event_limit) for item in value[:event_limit]]
    if isinstance(value, dict):
        return {str(k): _compact_value(v, max_text=max_text, event_limit=event_limit) for k, v in list(value.items())[:20]}
    return value


def _limit_list(value: Any, limit: int) -> list:
    return value[:limit] if isinstance(value, list) else []


BULL_THESIS_PROMPT = """你是多头研究员。只基于输入证据构建标的级看多论证，不给交易建议。
规则：不得调用工具，不得编造事实，不得输出 Markdown，只输出 JSON object。
禁止输出建仓、加仓、减仓、清仓、目标仓位、建议金额。账户上下文只作背景。
必须引用 evidence_refs，且只能来自 allowed_evidence_refs。证据不足时降低 conviction 并写入 data_limitations。"""

BEAR_THESIS_PROMPT = """你是空头/谨慎派研究员。只基于输入证据构建为什么不应轻易看多的最强论证，不给交易建议。
规则：不得调用工具，不得编造不存在的坏消息，不得输出 Markdown，只输出 JSON object。
禁止输出减仓、清仓、卖出、目标仓位、建议金额。必须承认证据中的正面事实。
必须引用 evidence_refs，且只能来自 allowed_evidence_refs。证据不足时降低 conviction 并写入 data_limitations。"""

BULL_REBUTTAL_PROMPT = """你是多头研究员，已经看到空头立论。只基于输入证据和双方立论反驳，不新增证据。
承认成立的风险，反驳被夸大的部分，强化仍支持看多的证据，给出 final_conviction。
不得调用工具、不得编造事实、不得输出交易动作、不得输出 Markdown，只输出 JSON object。"""

BEAR_REBUTTAL_PROMPT = """你是空头/谨慎派研究员，已经看到多头立论。只基于输入证据和双方立论反驳，不新增证据。
承认成立的机会，反驳证据不足或过度乐观的部分，强化仍需谨慎的风险，给出 final_conviction。
不得调用工具、不得编造事实、不得输出交易动作或目标仓位、不得输出 Markdown，只输出 JSON object。"""

DEBATE_JUDGE_PROMPT = """你是辩论裁判。基于证据卡、多头立论、空头立论、多头反驳、空头反驳，判断标的级观点。
只输出 asset_stance、conviction、winner、accepted_bull_points、accepted_bear_points、key_uncertainties、reasoning_summary、data_limitations。
禁止输出是否建仓、加仓、减仓、清仓、目标仓位、建议金额。不得调用工具、不得编造事实、不得输出 Markdown，只输出 JSON object。
如果公开市场数据大面积 fallback 或证据质量低，asset_stance 必须 insufficient_data 或 neutral，conviction 必须 low。
多空证据都强时倾向 neutral 和 balanced；账户仓位过高不等于标的 bearish；宏观事件高风险应降低 conviction。"""
