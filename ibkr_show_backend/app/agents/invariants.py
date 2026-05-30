from __future__ import annotations

import re
from math import isfinite
from typing import Any


DECISION_SCORE_DIMENSIONS = {
    "fundamental_quality_score": 20,
    "valuation_score": 15,
    "trend_score": 15,
    "account_fit_score": 20,
    "risk_reward_score": 15,
    "review_constraint_score": 10,
    "event_catalyst_score": 5,
}
TRADE_REVIEW_SCORE_DIMENSIONS = {
    "return_result_score": 20,
    "relative_performance_score": 15,
    "entry_quality_score": 15,
    "exit_quality_score": 15,
    "position_sizing_score": 15,
    "holding_period_score": 5,
    "risk_control_score": 10,
    "decision_attribution_score": 5,
}
_SCORE_DIMENSION_LABELS = {
    "return_result_score": "收益结果",
    "relative_performance_score": "相对收益",
    "entry_quality_score": "买点质量",
    "exit_quality_score": "卖点质量",
    "position_sizing_score": "仓位质量",
    "holding_period_score": "持仓周期",
    "risk_control_score": "风险控制",
    "decision_attribution_score": "决策归因",
}
ALLOWED_DECISION_TYPES = {"holding_decision", "entry_decision"}
ALLOWED_ACTIONS = {
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
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_DECISION_RATINGS = {"strong_buy_or_hold", "positive", "neutral", "negative"}
ALLOWED_REVIEW_RATINGS = {"excellent", "good", "average", "poor"}
ALLOWED_MISTAKE_TAGS = {
    "CHASE_HIGH",
    "SELL_TOO_EARLY",
    "SELL_TOO_LATE",
    "PANIC_SELL",
    "POSITION_TOO_SMALL",
    "POSITION_TOO_LARGE",
    "MISSED_OPPORTUNITY",
    "NO_CLEAR_PLAN",
    "WEAK_RELATIVE_PERFORMANCE",
    "GOOD_ENTRY",
    "GOOD_EXIT",
    "GOOD_POSITION_SIZING",
    "GOOD_TREND_FOLLOW",
    "GOOD_RISK_CONTROL",
}
ACTION_ALIASES = {
    "buy": "add_batch",
    "buy_now": "add",
    "strong_buy": "add",
    "accumulate": "add_batch",
    "increase": "add",
    "add_on_dips": "add_small",
    "add_on_pullback": "add_small",
    "buy_on_dips": "add_small",
    "buy_on_pullback": "add_small",
    "hold_or_add": "add_small",
    "hold_or_add_small": "add_small",
    "hold_and_add": "add_small",
    "hold_add_small": "add_small",
    "wait_for_pullback": "wait",
    "wait_pullback": "wait",
    "do_nothing": "hold",
    "trim": "reduce",
    "partial_sell": "reduce_batch",
    "full_sell": "sell",
    "clear": "sell",
    "exit": "sell",
    "watch": "watchlist",
    "observe": "watchlist",
    "hold_wait": "wait",
    "加仓": "add",
    "小幅加仓": "add_small",
    "少量加仓": "add_small",
    "逢低加仓": "add_small",
    "回调加仓": "add_small",
    "持有并逢低加仓": "add_small",
    "持有并小幅加仓": "add_small",
    "分批加仓": "add_batch",
    "建仓": "add_batch",
    "买入": "add_batch",
    "首笔建仓": "add_batch",
    "持有": "hold",
    "继续持有": "hold",
    "减仓": "reduce",
    "小幅减仓": "reduce",
    "分批减仓": "reduce_batch",
    "清仓": "sell",
    "卖出": "sell",
    "等待": "wait",
    "观望": "wait",
    "暂时等待": "wait",
    "等待回调": "wait",
    "等待更好买点": "wait",
    "不操作": "hold",
    "回避": "avoid",
    "避免": "avoid",
    "不建议": "avoid",
    "观察": "watchlist",
    "加入观察": "watchlist",
    "观察列表": "watchlist",
}
ACTION_CONTAINS_ALIASES = [
    ("wait_for_pullback", "wait"),
    ("wait_pullback", "wait"),
    ("add_on_pullback", "add_small"),
    ("add_on_dips", "add_small"),
    ("buy_on_pullback", "add_small"),
    ("buy_on_dips", "add_small"),
    ("hold_or_add_small", "add_small"),
    ("hold_or_add", "add_small"),
    ("hold_and_add", "add_small"),
    ("reduce_batch", "reduce_batch"),
    ("add_batch", "add_batch"),
    ("watchlist", "watchlist"),
    ("add_small", "add_small"),
    ("reduce", "reduce"),
    ("sell", "sell"),
    ("avoid", "avoid"),
    ("wait", "wait"),
    ("hold", "hold"),
    ("add", "add"),
    ("等待回调", "wait"),
    ("等待更好买点", "wait"),
    ("逢低加仓", "add_small"),
    ("回调加仓", "add_small"),
    ("小幅加仓", "add_small"),
    ("少量加仓", "add_small"),
    ("分批加仓", "add_batch"),
    ("继续持有", "hold"),
    ("不操作", "hold"),
    ("观察列表", "watchlist"),
    ("加入观察", "watchlist"),
    ("清仓", "sell"),
    ("卖出", "sell"),
    ("减仓", "reduce"),
    ("回避", "avoid"),
    ("避免", "avoid"),
    ("等待", "wait"),
    ("观望", "wait"),
    ("持有", "hold"),
    ("加仓", "add"),
    ("建仓", "add_batch"),
    ("买入", "add_batch"),
    ("观察", "watchlist"),
]
CONFIDENCE_ALIASES = {
    "高": "high",
    "高置信": "high",
    "中": "medium",
    "中等": "medium",
    "中等置信": "medium",
    "低": "low",
    "低置信": "low",
}
FORCEFUL_TRADE_WORDS = ("必须买入", "立即清仓", "无脑加仓", "必须卖出", "马上买入", "立刻买入", "all in", "ALL IN")


def decision_rating_for_score(score: float) -> str:
    if score >= 85:
        return "strong_buy_or_hold"
    if score >= 70:
        return "positive"
    if score >= 50:
        return "neutral"
    return "negative"


def review_rating_for_score(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "average"
    return "poor"


def normalize_action(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_ACTIONS:
        return normalized
    alias = ACTION_ALIASES.get(normalized) or ACTION_ALIASES.get(raw)
    if alias:
        return alias
    compact = normalized.replace("/", "_").replace("|", "_").replace(",", "_").replace("，", "_")
    for marker, action in ACTION_CONTAINS_ALIASES:
        if marker in compact or marker in raw:
            return action
    return normalized


def normalize_confidence(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_CONFIDENCE:
        return normalized
    return CONFIDENCE_ALIASES.get(normalized) or CONFIDENCE_ALIASES.get(raw) or normalized


def normalize_trade_decision_output(payload: dict, expected_decision_type: str | None = None) -> dict:
    result = dict(payload)
    warnings = _string_list(result.get("data_limitations"))
    decision_type = str(result.get("decision_type") or expected_decision_type or "")
    if decision_type not in ALLOWED_DECISION_TYPES:
        raise ValueError("decision_type is invalid")
    if expected_decision_type and decision_type != expected_decision_type:
        raise ValueError("decision_type does not match request")
    result["decision_type"] = decision_type

    score_detail, total = _normalize_score_detail(result.get("score_detail"), DECISION_SCORE_DIMENSIONS, fill_missing=False)
    result["score_detail"] = score_detail
    result["overall_score"] = round(total, 2)
    result["rating"] = decision_rating_for_score(result["overall_score"])

    action = normalize_action(result.get("action"))
    if action not in ALLOWED_ACTIONS:
        raise ValueError("action is invalid")
    confidence = normalize_confidence(result.get("confidence"))
    if confidence not in ALLOWED_CONFIDENCE:
        raise ValueError("confidence is invalid")
    result["action"] = action
    result["confidence"] = confidence

    if not result.get("decision_summary"):
        raise ValueError("decision_summary is required")
    result["position_advice"], pct_warnings = _normalize_position_advice(result.get("position_advice"))
    warnings.extend(pct_warnings)
    result["execution_plan"] = _normalize_execution_plan(result.get("execution_plan"))
    result["action"] = _reconcile_decision_action(result["action"], result["position_advice"], result["execution_plan"])

    if len(warnings) >= 4 and result["confidence"] == "high":
        result["confidence"] = "medium"
        warnings.append("confidence downgraded because data_limitations are material")
    if _longbridge_critical_missing(warnings) and result["rating"] == "strong_buy_or_hold":
        result["rating"] = "positive"
        warnings.append("rating capped because critical Longbridge public data is missing")
    result["data_limitations"] = warnings
    for key in ("key_reasons", "major_risks", "review_warnings", "evidence_used"):
        result[key] = _string_list(result.get(key))
    return result


def normalize_trade_review_output(payload: dict, *, review_context: dict | None = None) -> dict:
    result = dict(payload)
    not_applicable: set[str] = set()
    has_sell_trades = _has_sell_trades(result, review_context)
    if not has_sell_trades:
        not_applicable.add("exit_quality_score")
    score_detail, total = _normalize_score_detail(
        result.get("score_detail"), TRADE_REVIEW_SCORE_DIMENSIONS, fill_missing=True, not_applicable=not_applicable,
    )
    if has_sell_trades:
        total = _normalize_reviewable_exit_quality(score_detail, result, review_context)
    if _is_open_buy_single_trade(result, review_context) and total <= 0:
        minimum_reviewable_scores = {
            "entry_quality_score": 5.0,
            "position_sizing_score": 3.0,
            "holding_period_score": 1.0,
            "risk_control_score": 1.0,
        }
        for key, floor in minimum_reviewable_scores.items():
            score_detail[key]["score"] = max(float(score_detail[key].get("score") or 0.0), floor)
        score_detail["entry_quality_score"]["reason"] += "；BUY 且仍持仓时不得仅因没有 SELL 记录整体给 0 分"
        result.setdefault("data_limitations", []).append("Open BUY single-trade review normalized from zero-score output")
        total = sum(float(item.get("score") or 0.0) for item in score_detail.values() if item.get("applicable", True))
    applicable_max = sum(float(item.get("max_score") or 0) for item in score_detail.values() if item.get("applicable", True))
    if applicable_max > 0:
        overall = round(total / applicable_max * 100, 2)
    else:
        overall = 0.0
    result["score_detail"] = score_detail
    result["overall_score"] = overall
    result["rating"] = review_rating_for_score(overall)
    result["raw_applicable_score"] = round(total, 2)
    result["applicable_max_score"] = round(applicable_max, 2)
    excluded = []
    for dim, item in score_detail.items():
        if not item.get("applicable", True):
            excluded.append({"key": dim, "label": _SCORE_DIMENSION_LABELS.get(dim, dim), "max_score": item["max_score"], "reason": item.get("reason", "")})
    result["excluded_score_dimensions"] = excluded

    unknown_tags = []
    cleaned_tags = []
    for tag in result.get("mistake_tags") or []:
        tag_text = str(tag)
        if tag_text in ALLOWED_MISTAKE_TAGS:
            cleaned_tags.append(tag_text)
        else:
            unknown_tags.append(tag_text)
    result["mistake_tags"] = cleaned_tags
    limitations = _string_list(result.get("data_limitations"))
    if unknown_tags:
        limitations.append(f"Unknown mistake tags filtered: {', '.join(unknown_tags)}")
    result["data_limitations"] = limitations
    if not result.get("summary"):
        raise ValueError("summary is required")
    for key in ("strengths", "weaknesses", "improvement_suggestions", "evidence_used"):
        result[key] = _string_list(result.get(key))
    return result


def normalize_daily_position_review_output(
    payload: dict,
    *,
    expected_report_date: str,
    deterministic_context: dict | None = None,
) -> dict:
    result = dict(payload)
    if str(result.get("report_date") or expected_report_date) != expected_report_date:
        raise ValueError("report_date does not match request")
    result["report_date"] = expected_report_date
    overview = (deterministic_context or {}).get("overview") or {}
    fallbacks = {
        "summary": overview.get("summary") or "每日复盘已生成，模型摘要缺失，使用后端确定性概览兜底。",
        "account_conclusion": overview.get("summary") or "账户结论使用后端确定性概览兜底。",
        "attribution_summary": _fallback_attribution_summary(overview),
        "market_context": "公开市场解释不足，未强行归因。",
        "risk_analysis": _fallback_risk_summary((deterministic_context or {}).get("risk") or {}),
        "operation_observation": "仅提供观察条件，不构成自动交易指令。",
    }
    limitations = _string_list(result.get("data_limitations"))
    for key, fallback in fallbacks.items():
        result[key] = str(result.get(key) or fallback)
        if result[key] == fallback:
            limitations.append(f"{key} was filled from deterministic fallback")
    for key in ("major_contributors_analysis", "major_drags_analysis", "focus_symbol_analyses"):
        result[key] = result.get(key) if isinstance(result.get(key), list) else []
    result["tomorrow_watchlist"], watch_warnings = _sanitize_watchlist(result.get("tomorrow_watchlist"))
    limitations.extend(watch_warnings)
    result["data_limitations"] = limitations
    result["evidence_used"] = _string_list(result.get("evidence_used"))
    return result


def _normalize_score_detail(
    value: Any,
    dimensions: dict[str, int],
    *,
    fill_missing: bool,
    not_applicable: set[str] | None = None,
) -> tuple[dict, float]:
    source = value if isinstance(value, dict) else {}
    if not source and not fill_missing:
        raise ValueError("score_detail is required")
    na_set = not_applicable or set()
    result = {}
    total = 0.0
    for dimension, max_score in dimensions.items():
        if dimension in na_set:
            result[dimension] = {
                "score": None,
                "max_score": max_score,
                "reason": str((source.get(dimension) or {}).get("reason") or "尚未卖出，暂不评分，不计入总分。"),
                "applicable": False,
            }
            continue
        item = source.get(dimension)
        if not isinstance(item, dict):
            if not fill_missing:
                raise ValueError(f"{dimension} is required")
            item = {"score": 0, "max_score": max_score, "reason": "模型未提供该维度评分"}
        score = _to_number(item.get("score"))
        if score is None or not isfinite(score):
            score = 0.0
        if score < 0 or score > max_score:
            raise ValueError(f"{dimension} score must be between 0 and {max_score}")
        result[dimension] = {"score": float(score), "max_score": max_score, "reason": str(item.get("reason") or ""), "applicable": True}
        total += float(score)
    return result, total


def _normalize_position_advice(value: Any) -> tuple[dict, list[str]]:
    payload = value if isinstance(value, dict) else {}
    warnings: list[str] = []
    result = {
        "current_position_pct": _normalize_position_pct(payload.get("current_position_pct"), "current_position_pct", warnings),
        "suggested_target_position_pct": _normalize_position_pct(payload.get("suggested_target_position_pct"), "suggested_target_position_pct", warnings),
        "max_position_pct": _normalize_position_pct(payload.get("max_position_pct"), "max_position_pct", warnings),
        "suggested_cash_amount": _to_number(payload.get("suggested_cash_amount")),
        "position_size_label": str(payload.get("position_size_label") or "none"),
    }
    target = result.get("suggested_target_position_pct")
    max_pct = result.get("max_position_pct")
    if target is not None and max_pct is not None and target > max_pct:
        result["suggested_target_position_pct"] = max_pct
        warnings.append("suggested_target_position_pct capped at max_position_pct")
    return result, warnings


def _normalize_position_pct(value: Any, field_name: str, warnings: list[str]) -> float | None:
    number = _to_number(value)
    if number is None:
        return None
    if abs(number) > 1:
        warnings.append(f"{field_name} normalized from percent number to ratio")
        return round(number / 100.0, 6)
    return round(number, 6)


def _normalize_execution_plan(value: Any) -> dict:
    payload = value if isinstance(value, dict) else {}
    return {
        "should_act_now": bool(payload.get("should_act_now", False)),
        "plan": _normalize_execution_steps(payload.get("plan")),
        "invalid_conditions": _string_list(payload.get("invalid_conditions")),
        "recheck_triggers": _string_list(payload.get("recheck_triggers")),
    }


def _normalize_execution_steps(value: Any) -> list[dict]:
    steps = value if isinstance(value, list) else []
    result = []
    for index, item in enumerate(steps, start=1):
        if not isinstance(item, dict):
            result.append({"step": index, "condition": "", "action": "", "amount": None, "note": str(item)})
            continue
        amount_raw = item.get("amount")
        amount = _to_number(amount_raw)
        note = str(item.get("note") or "")
        if amount is None and amount_raw not in (None, ""):
            note = f"{note}；数量/金额：{amount_raw}" if note else f"数量/金额：{amount_raw}"
        result.append(
            {
                "step": int(round(_to_number(item.get("step")) or index)),
                "condition": str(item.get("condition") or ""),
                "action": str(item.get("action") or ""),
                "amount": int(round(amount)) if amount is not None and isfinite(amount) else None,
                "note": note,
            }
        )
    return result


def _reconcile_decision_action(action: str, position_advice: dict, execution_plan: dict) -> str:
    if action not in {"add", "add_small", "add_batch"}:
        return action
    should_act_now = bool(execution_plan.get("should_act_now"))
    suggested_cash = _to_number(position_advice.get("suggested_cash_amount"))
    if should_act_now and suggested_cash is not None and suggested_cash > 0:
        return action
    current_position_pct = _to_number(position_advice.get("current_position_pct")) or 0.0
    return "hold" if current_position_pct > 0 else "watchlist"


def _sanitize_watchlist(value: Any) -> tuple[list[dict], list[str]]:
    items = value if isinstance(value, list) else []
    warnings = []
    sanitized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned = {}
        changed = False
        for key, raw in item.items():
            if isinstance(raw, str):
                text, was_changed = _soften_forceful_language(raw)
                cleaned[key] = text
                changed = changed or was_changed
            elif isinstance(raw, list):
                values = []
                for entry in raw:
                    text, was_changed = _soften_forceful_language(str(entry))
                    values.append(text)
                    changed = changed or was_changed
                cleaned[key] = values
            else:
                cleaned[key] = raw
        if changed:
            warnings.append(f"Forceful trading language softened in tomorrow_watchlist for {cleaned.get('symbol') or 'unknown'}")
        sanitized.append(cleaned)
    return sanitized, warnings


def _soften_forceful_language(text: str) -> tuple[str, bool]:
    changed = False
    result = text
    for word in FORCEFUL_TRADE_WORDS:
        if word in result:
            result = result.replace(word, "观察是否满足预设条件")
            changed = True
    if re.search(r"\b(all in|ALL IN)\b", result):
        result = re.sub(r"\b(all in|ALL IN)\b", "观察是否满足预设条件", result)
        changed = True
    return result, changed


def _longbridge_critical_missing(limitations: list[str]) -> bool:
    text = " ".join(limitations).lower()
    return "longbridge" in text and any(marker in text for marker in ("unavailable", "缺失", "missing", "no usable data"))


def _is_open_buy_single_trade(payload: dict, review_context: dict | None) -> bool:
    if payload.get("review_type") != "single_trade_review":
        return False
    facts = _extract_trade_review_facts(review_context)
    trades = facts.get("trades") or []
    first = trades[0] if trades and isinstance(trades[0], dict) else {}
    return str(first.get("side") or "").upper() == "BUY" and bool(facts.get("is_currently_holding"))


def _has_sell_trades(payload: dict, review_context: dict | None) -> bool:
    facts = _extract_trade_review_facts(review_context)
    if facts.get("has_sell_trades") is True:
        return True
    sell_count = _to_number(facts.get("sell_count"))
    if sell_count is not None and sell_count > 0:
        return True
    for trade in facts.get("trades") or []:
        if isinstance(trade, dict) and _normalize_trade_side(trade.get("side") or trade.get("buy_sell")) == "SELL":
            return True
    for trade in facts.get("related_symbol_trades") or []:
        if isinstance(trade, dict) and _normalize_trade_side(trade.get("side") or trade.get("buy_sell")) == "SELL":
            return True
    return False


def _normalize_reviewable_exit_quality(score_detail: dict, result: dict, review_context: dict | None) -> float:
    exit_score = score_detail.get("exit_quality_score") or {}
    reason = str(exit_score.get("reason") or "")
    facts = _extract_trade_review_facts(review_context)
    limitations = result.setdefault("data_limitations", [])
    if not isinstance(limitations, list):
        limitations = [str(limitations)]
        result["data_limitations"] = limitations

    if _exit_reason_denies_sell(reason) and float(exit_score.get("score") or 0.0) == 0.0:
        exit_score["score"] = 7.5
        exit_score["reason"] = (
            "复盘区间内存在已发生的卖出交易，卖点质量按历史卖出批次进行中性兜底评分；"
            "原始 LLM 理由误判为未退出状态。"
        )
        limitations.append(
            "LLM exit_quality reason contradicted deterministic sell-trade facts; normalized as reviewable historical exit quality."
        )

    if facts.get("has_reopened_position_after_sell") and "当前最新持仓尚未退出" not in str(exit_score.get("reason") or ""):
        exit_score["reason"] = f"{exit_score.get('reason') or '评价历史已发生的卖出批次。'}；当前最新持仓尚未退出，不评价最新持仓的最终退出质量。"

    return sum(float(item.get("score") or 0.0) for item in score_detail.values() if item.get("applicable", True))


def _exit_reason_denies_sell(reason: str) -> bool:
    return bool(re.search(r"(尚未卖出|暂未卖出|未发生卖出|没有卖出|无卖出|无法评价|暂不评价|暂不评分)", reason))


def _normalize_trade_side(value: Any) -> str:
    side = str(value or "").strip().upper().replace(" ", "_")
    if side in {"BUY", "BOT", "BOUGHT"}:
        return "BUY"
    if side in {"SELL", "SLD", "SOLD", "SELL_SHORT", "SSHORT"}:
        return "SELL"
    return side


def _extract_trade_review_facts(review_context: dict | None) -> dict:
    """Extract trade_facts from review_context, supporting both direct evidence pack
    and tool-wrapper structures returned by tool_get_single_trade_review_context.

    Structure A (direct evidence pack):
        {"trade_facts": {...}}

    Structure B (tool wrapper from tool_get_single_trade_review_context):
        {"source": "IBKR + Longbridge", "trade_id": "...", "review_context": {...}}
        where review_context.review_context contains trade_facts
    """
    if not isinstance(review_context, dict):
        return {}
    if "trade_facts" in review_context:
        return review_context["trade_facts"]
    inner = review_context.get("review_context")
    if isinstance(inner, dict) and "trade_facts" in inner:
        return inner["trade_facts"]
    return {}


def _fallback_attribution_summary(overview: dict) -> str:
    return (
        f"当日账户盈亏为 {overview.get('daily_pnl')}，收益率为 {overview.get('daily_return_percent')}%。"
        "贡献、仓位、浮盈亏等确定性数字均来自后端计算。"
    )


def _fallback_risk_summary(risk: dict) -> str:
    flags = [str(item) for item in risk.get("risk_flags") or []]
    return "；".join(flags) if flags else "当前没有明显集中度警报，仍需继续观察风险变化。"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value)]
    return [str(item) for item in value]


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
