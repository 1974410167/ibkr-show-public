"""AI investment policy assessment agent for trade decisions.

This sub-agent consumes the already-built card pack only. It does not call
external tools, repositories, MCP, or market-data APIs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.agents.graph.node_utils import strip_thinking_tags
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output import StructuredOutputRuntime
from app.agents.trade_decision_cards import TradeDecisionCardPack, TradeDecisionSubAgentTrace
from app.agents.trade_decision_structured_outputs import (
    AiPolicyAssessmentOutput,
    build_ai_policy_assessment_contract,
)


AI_POLICY_ASSESSMENT_PROMPT_KEY = "trade_decision_ai_policy_assessment"
AI_POLICY_ASSESSMENT_FAILURE_LIMITATION = "AI 投资策略评估失败，未使用 AI 仓位建议"


class TradeDecisionPolicyAssessmentAgent:
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

    def generate(self, card_pack: TradeDecisionCardPack) -> tuple[dict[str, Any], TradeDecisionSubAgentTrace]:
        context = self._build_context(card_pack)
        prompt = self._resolve_system_prompt()
        contract = build_ai_policy_assessment_contract()
        result = self.runtime.generate(
            self._messages(prompt, context),
            contract,
            temperature=0.0,
            max_tokens=self.max_tokens,
            context=context,
            run_id=self.run_id,
            task_id=self.task_id,
        )
        if not result.ok or result.payload is None:
            reason = f"{result.error_code or 'structured_output_failed'}: {result.error_message or ''}".strip()
            assessment = self._fallback_assessment(context, reason)
            return assessment, self._trace_from_result("fallback", result, reason, context, assessment)

        try:
            assessment = self._sanitize_payload(result.payload, context)
        except Exception as exc:
            reason = f"ai_policy_assessment_sanitize_failed: {str(exc)[:160]}"
            assessment = self._fallback_assessment(context, reason)
            return assessment, self._trace_from_result("fallback", result, reason, context, assessment)
        return assessment, self._trace_from_result("completed", result, None, context, assessment)

    def _build_context(self, card_pack: TradeDecisionCardPack) -> dict[str, Any]:
        pack = card_pack.to_dict() if hasattr(card_pack, "to_dict") else {}
        snapshot = _dict(pack.get("account_fact_snapshot"))
        policy = _dict(pack.get("user_investment_policy"))
        current_pct = _current_position_pct(card_pack, snapshot)
        user_summary = _build_user_policy_summary(policy, current_pct)
        return {
            "symbol": card_pack.symbol,
            "decision_type": card_pack.decision_type,
            "user_question": snapshot.get("user_question"),
            "current_position_pct": current_pct,
            "user_investment_policy_summary": user_summary,
            "user_investment_policy": _compact(policy),
            "account_fact_snapshot": _compact(snapshot),
            "account_fit_card": _compact(pack.get("account_fit_card")),
            "market_trend_card": _compact(pack.get("market_trend_card")),
            "fundamental_valuation_card": _compact(pack.get("fundamental_valuation_card")),
            "event_catalyst_card": _compact(pack.get("event_catalyst_card")),
            "market_event_context_card": _compact(pack.get("market_event_context_card")),
            "risk_reward_card": _compact(pack.get("risk_reward_card")),
            "review_warnings": _compact(snapshot.get("review_warnings") or snapshot.get("global_mistake_tags") or []),
            "historical_mistake_flags": _compact(snapshot.get("global_mistake_tags") or []),
            "output_rules": {
                "position_pct_unit": "0_to_1_decimal",
                "prompt_key": AI_POLICY_ASSESSMENT_PROMPT_KEY,
                "prompt_source": _public_prompt_source((self._last_prompt_metadata or {}).get("source")),
                "do_not_treat_user_preferred_max_as_risk_gate_cap": True,
                "do_not_emit_real_order_instruction": True,
            },
        }

    def _sanitize_payload(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        current_pct = _safe_float(context.get("current_position_pct"), 0.0) or 0.0
        data["status"] = "evaluated" if data.get("status") not in {"fallback", "not_evaluated"} else data.get("status")
        data["current_position_pct"] = round(max(0.0, min(1.0, current_pct)), 6)
        data["prompt_key"] = AI_POLICY_ASSESSMENT_PROMPT_KEY
        data["prompt_source"] = _public_prompt_source((self._last_prompt_metadata or {}).get("source"))
        data["prompt_version"] = (self._last_prompt_metadata or {}).get("version")
        data["prompt_content_hash"] = (self._last_prompt_metadata or {}).get("content_hash")
        data["prompt_template_name"] = (self._last_prompt_metadata or {}).get("prompt_key") or AI_POLICY_ASSESSMENT_PROMPT_KEY

        target = _safe_float(data.get("ai_recommended_target_position_pct"), None)
        max_pct = _safe_float(data.get("ai_recommended_max_position_pct"), None)
        data["gap_to_ai_target_pct"] = round(target - current_pct, 6) if target is not None else None
        data["gap_to_ai_max_pct"] = round(max_pct - current_pct, 6) if max_pct is not None else None

        user_role = str((_dict(context.get("user_investment_policy_summary")).get("asset_role") or "")).lower()
        if user_role == "forbidden" and data.get("recommended_action_bias") in {"allow_add", "prefer_pullback_add"}:
            data["recommended_action_bias"] = "avoid"
            data["challenge_level"] = "risk_warning"
            risks = list(data.get("key_risks") or [])
            risks.append("用户策略将该标的标记为 forbidden，AI 不能静默允许买入。")
            data["key_risks"] = _dedupe_text(risks)

        try:
            model = AiPolicyAssessmentOutput.model_validate(data)
        except ValidationError:
            raise
        return model.model_dump()

    def _fallback_assessment(self, context: dict[str, Any], reason: str) -> dict[str, Any]:
        current_pct = _safe_float(context.get("current_position_pct"), 0.0) or 0.0
        prompt_metadata = self._last_prompt_metadata or {}
        return AiPolicyAssessmentOutput(
            status="fallback",
            ai_assessed_asset_role="unknown",
            ai_role_confidence="low",
            ai_position_stance="unknown",
            current_position_pct=round(max(0.0, min(1.0, current_pct)), 6),
            challenge_level="not_evaluated",
            challenge_reason=AI_POLICY_ASSESSMENT_FAILURE_LIMITATION,
            preference_alignment_summary="未完成 AI 独立仓位评估，交易计划不得使用 AI 仓位建议。",
            recommended_action_bias="unknown",
            risk_budget={"reason": "未评估"},
            data_limitations=[AI_POLICY_ASSESSMENT_FAILURE_LIMITATION, reason[:200]],
            prompt_key=AI_POLICY_ASSESSMENT_PROMPT_KEY,
            prompt_source=_public_prompt_source(prompt_metadata.get("source")),
            prompt_version=prompt_metadata.get("version"),
            prompt_content_hash=prompt_metadata.get("content_hash"),
            prompt_template_name=prompt_metadata.get("prompt_key") or AI_POLICY_ASSESSMENT_PROMPT_KEY,
        ).model_dump()

    def _trace_from_result(
        self,
        status: str,
        result: Any | None,
        fallback_reason: str | None,
        context: dict[str, Any],
        assessment: dict[str, Any],
    ) -> TradeDecisionSubAgentTrace:
        structured_output = _result_trace_payload(result) if result is not None else None
        llm_meta = ((result.metadata or {}).get("llm_call_metadata") if result is not None else {}) or {}
        token_usage = llm_meta.get("token_usage") if isinstance(llm_meta, dict) else {}
        prompt_metadata = {
            **(self._last_prompt_metadata or {}),
            "prompt_key": AI_POLICY_ASSESSMENT_PROMPT_KEY,
            "prompt_source": assessment.get("prompt_source"),
            "contract_name": "trade_decision_ai_policy_assessment",
            "context_card_count": sum(
                1
                for key in (
                    "account_fit_card",
                    "market_trend_card",
                    "fundamental_valuation_card",
                    "event_catalyst_card",
                    "market_event_context_card",
                    "risk_reward_card",
                )
                if context.get(key)
            ),
            "input_tokens": (token_usage or {}).get("prompt_tokens") or llm_meta.get("prompt_tokens") if isinstance(llm_meta, dict) else None,
            "output_tokens": (token_usage or {}).get("completion_tokens") or llm_meta.get("completion_tokens") if isinstance(llm_meta, dict) else None,
        }
        return TradeDecisionSubAgentTrace(
            sub_agent_name="ai_policy_assessment",
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
            AI_POLICY_ASSESSMENT_PROMPT_KEY,
            AI_POLICY_ASSESSMENT_PROMPT,
        )
        metadata["prompt_source"] = _public_prompt_source(metadata.get("source"))
        self._last_prompt_metadata = metadata
        return prompt


def _build_user_policy_summary(policy: dict[str, Any], current_pct: float) -> dict[str, Any]:
    preference = _dict(policy.get("user_investment_preference")) or policy
    target = _safe_float(preference.get("user_preferred_target_position_pct"), None)
    max_pct = _safe_float(preference.get("user_preferred_max_position_pct"), None)
    min_pct = _safe_float(preference.get("user_preferred_min_position_pct"), None)
    return {
        "source": policy.get("source") or "unknown",
        "asset_role": preference.get("asset_role") or policy.get("role") or "unknown",
        "conviction": preference.get("conviction") or policy.get("risk_class") or "low",
        "user_preferred_min_position_pct": min_pct,
        "user_preferred_target_position_pct": target,
        "user_preferred_max_position_pct": max_pct,
        "current_position_pct": current_pct,
        "gap_to_user_preferred_target_pct": round(target - current_pct, 6) if target is not None else None,
        "gap_to_user_preferred_max_pct": round(max_pct - current_pct, 6) if max_pct is not None else None,
        "add_rules": _list_text(preference.get("add_rules")),
        "no_add_triggers": _list_text(preference.get("no_add_triggers")),
        "sell_triggers": _list_text(preference.get("sell_triggers")),
        "hard_constraints": _list_text(preference.get("hard_constraints")),
        "soft_preferences": _list_text(preference.get("soft_preferences")),
        "notes": str(preference.get("notes") or ""),
        "disclaimer": "这是用户主观偏好，不是 AI 最终仓位建议。",
    }


def _current_position_pct(card_pack: TradeDecisionCardPack, snapshot: dict[str, Any]) -> float:
    value = snapshot.get("position_pct")
    if value is None:
        value = snapshot.get("current_position_pct")
    if value is None:
        raw = getattr(card_pack.account_fact_snapshot, "position_pct", None)
        value = raw if raw is not None else getattr(card_pack.account_fact_snapshot, "current_position_pct", None)
    return max(0.0, min(1.0, _safe_float(value, 0.0) or 0.0))


def _public_prompt_source(source: Any) -> str:
    return "admin_config" if str(source or "") == "admin_active" else "default_fallback"


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {}


def _list_text(value: Any, limit: int = 12) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [strip_thinking_tags(str(item))[:1000] for item in items if str(item or "").strip()][:limit]


def _compact(value: Any, *, max_text: int = 1200, list_limit: int = 8) -> Any:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, str):
        return strip_thinking_tags(value)[:max_text]
    if isinstance(value, list):
        return [_compact(item, max_text=max_text, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in list(value.items())[:35]:
            compact[str(key)] = _compact(item, max_text=max_text, list_limit=list_limit)
        return compact
    return value


def _safe_float(value: Any, default: float | None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = strip_thinking_tags(str(value or "")).strip()
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


AI_POLICY_ASSESSMENT_PROMPT = """你是 AI 投资策略评估 Agent。
你的任务不是复述用户偏好，也不是直接给买卖指令。
你的任务是：在尊重用户偏好的前提下，结合当前账户、市场趋势、基本面估值、事件催化、风险收益和历史复盘，判断用户偏好是否合理，并给出 AI 自己独立形成的仓位建议。

必须遵守：
- 用户投资偏好是输入，不是结论。
- 用户不是成熟交易员，不能盲从用户偏好。
- AI 可以认可、部分反驳或强烈反驳用户偏好。
- 如果用户偏好明显过激，必须指出风险。
- 如果用户偏好合理，但当前估值、趋势或事件风险不适合立即加仓，应给阶段性较低目标。
- 如果用户偏好过低，而标的质量高且账户明显低配，可以温和建议提高目标仓位。
- 如果数据不足，不能输出 high confidence。
- 不输出真实下单指令，不暗示系统会自动交易。
- 不承诺收益，禁止“保证收益”“必涨”“一定盈利”等表达。
- 不把 user_preferred_max_position_pct 当硬上限。
- AI 推荐仓位必须基于证据独立形成，使用 0-1 小数，例如 0.2 表示 20%。
- 若用户配置 asset_role=forbidden，AI 可以说明不同意，但不能静默输出允许买入或加仓。

你只能使用用户消息中的 JSON 上下文，不得调用工具、MCP、repository、Longbridge 或外部数据。
只输出严格 JSON object，字段必须符合 schema。
"""


__all__ = [
    "AI_POLICY_ASSESSMENT_FAILURE_LIMITATION",
    "AI_POLICY_ASSESSMENT_PROMPT",
    "AI_POLICY_ASSESSMENT_PROMPT_KEY",
    "TradeDecisionPolicyAssessmentAgent",
]
