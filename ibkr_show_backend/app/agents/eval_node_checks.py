from __future__ import annotations

import json
import re
from typing import Any

from app.agents.eval_harness import CheckResult


_TRADE_DECISION_NODE_NAMES: set[str] = {
    "market_trend",
    "fundamental_valuation",
    "event_catalyst",
    "risk_control",
    "final_decision",
}


_UNCERTAINTY_KEYWORDS = (
    "不确定", "风险", "限制", "假设", "可能", "需要进一步验证",
    "data limitation", "uncertain", "risk", "assumption",
)

_OVERCONFIDENCE_KEYWORDS = (
    "必然", "一定", "毫无疑问", "绝对", "肯定上涨", "无风险", "稳赚",
    "all in", "must buy", "guaranteed", "risk-free",
)

_MA_TREND_BASIS_KEYWORDS = (
    "价格走势", "成交量", "均线", "支撑", "阻力", "波动率", "相对强弱", "趋势",
    "volume", "moving average", "support", "resistance", "momentum",
)

_MA_TREND_TIMEFRAME_KEYWORDS = (
    "短期", "中期", "长期", "日线", "周线", "近几日", "近一个月",
    "timeframe", "short-term", "medium-term", "long-term",
)

_MA_TREND_BUY_JUMP_PATTERNS = (
    (r"上涨\s*->\s*(?:买入|买进|加仓)", "上涨 -> 买入"),
    (r"突破\s*->\s*(?:必买|加仓|all\s*in)", "突破 -> 必买"),
    (r"(?:强势|走强)\s*->\s*all\s*in", "强势 -> all in"),
)

_FUNDAMENTAL_BUSINESS_KEYWORDS = (
    "收入", "利润", "毛利率", "现金流", "资产负债", "增长", "营收", "业务", "订单", "市场份额",
    "revenue", "profit", "margin", "cash flow", "growth", "balance sheet",
)

_FUNDAMENTAL_UNCERTAINTY_KEYWORDS = (
    "估值假设", "盈利预测", "增长不确定", "行业周期", "利率", "折现率",
    "assumption", "forecast", "uncertainty", "cycle",
)

_FUNDAMENTAL_MECHANICAL_PE_PATTERNS = (
    (r"PE\s*低\s*所以\s*(?:买|便宜|低估)", "PE 低所以买"),
    (r"PE\s*高\s*所以\s*(?:卖|贵|高估)", "PE 高所以卖"),
    (r"市盈率\s*低\s*所以\s*低估", "市盈率低所以低估"),
    (r"市盈率\s*高\s*所以\s*高估", "市盈率高所以高估"),
)

_FUNDAMENTAL_DIRECT_TRADE_PATTERNS = (
    r"立即买入", r"直接加仓", r"马上卖出", r"all\s*in", r"strong\s*buy\s*now",
)

_EVENT_CATALYST_KEYWORDS = (
    "财报", "发布会", "产品发布", "监管", "并购", "订单", "指引", "降息", "政策", "公告",
    "earnings", "guidance", "launch", "regulation", "merger", "order", "policy",
)

_GENERIC_BULLISH_PATTERNS = (
    r"有利好",
    r"有催化",
    r"市场\s*看好",
    r"市场\s*普遍\s*看好",
    r"前景\s*广阔",
    r"story\s+is\s+good",
    r"\bpositive\s+outlook\b",
)

_EVENT_CATALYST_CONFIRMED_KEYWORDS = (
    "已发生", "预期", "传闻", "待确认", "可能", "confirmed", "expected", "rumor", "pending",
)

_EVENT_CATALYST_SOURCE_KEYWORDS = (
    "公告", "财报", "新闻", "公司披露", "管理层", "市场数据",
    "filing", "press release", "news", "management", "source",
)

_EVENT_CATALYST_FORCED_ATTRIBUTION_PATTERNS = (
    r"股价上涨说明有利好",
    r"涨了\s*所以\s*一定(?:有|存在)?\s*催化",
    r"市场上涨证明事件积极",
)

_RISK_POSITION_KEYWORDS = (
    "仓位", "分批", "轻仓", "加仓比例", "持仓比例",
    "position size", "sizing", "tranche", "scale in",
)

_RISK_DOWNSIDE_KEYWORDS = (
    "下跌", "回撤", "止损", "失效条件", "风险点", "跌破",
    "downside", "drawdown", "stop loss", "invalidation",
)

_RISK_ALL_IN_KEYWORDS = ("满仓", "梭哈", "all in", "重仓无脑买")

_RISK_USER_CONSTRAINT_KEYWORDS = (
    "现金比例", "已有仓位", "组合风险", "保证金", "集中度", "回撤承受",
    "cash", "portfolio", "margin", "concentration", "drawdown tolerance",
)

_FINAL_DECISION_ACTION_KEYWORDS = (
    "买入", "卖出", "持有", "等待", "分批", "加仓", "减仓",
    "buy", "sell", "hold", "wait", "scale",
)

_FINAL_DECISION_REASON_KEYWORDS = (
    "因为", "基于", "考虑到", "原因", "rationale", "because", "due to",
)

_FINAL_DECISION_RISK_KEYWORDS = (
    "分批", "仓位", "止损", "观察", "回撤", "条件",
    "risk", "position", "stop", "condition",
)

_FINAL_DECISION_STRONG_BUY_KEYWORDS = (
    "强烈买入", "重仓", "大幅加仓", "all in", "满仓买入", "强买入",
)

_FINAL_DECISION_WEAK_SIGNAL_KEYWORDS = (
    "可能", "不确定", "有限", "待确认", "或许", "也许",
    "uncertain", "limited", "pending", "maybe",
)


def run_node_specific_checks(
    output: Any,
    case: Any,
    replay: dict | None = None,
) -> list[CheckResult]:
    """为 Node Eval Case 调度 generic + agent/node 特化检查。

    仅在 case.eval_scope == "node" 时返回结果，否则返回空 list。
    Agent 级 case 不受影响。
    """
    scope = _case_value(case, "eval_scope", "agent")
    if scope != "node":
        return []

    results: list[CheckResult] = list(run_generic_node_checks(output, case, replay))
    agent_name = str(_case_value(case, "agent_name", "") or "")
    if agent_name == "trade_decision":
        node_name = str(_case_value(case, "node_name", "") or "")
        results.extend(run_trade_decision_node_checks(node_name, output, case, replay))
    return results


def run_generic_node_checks(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    """所有 node eval case 都跑的基础质量检查。"""
    results: list[CheckResult] = []
    text = _flatten_text(output)
    has_text = bool(text and text.strip())
    non_empty = _is_non_empty_output(output)

    if not non_empty:
        results.append(
            CheckResult(
                "node_output_not_empty",
                False,
                "high",
                0,
                10,
                "Node output is empty" if not has_text else "Node output contains only empty values",
            )
        )
    else:
        results.append(
            CheckResult(
                "node_output_not_empty",
                True,
                "info",
                10,
                10,
                "Node output is non-empty",
            )
        )

    has_uncertainty = _contains_any(text, _UNCERTAINTY_KEYWORDS)
    results.append(
        CheckResult(
            "node_mentions_uncertainty_or_limitations",
            has_uncertainty,
            "warning" if not has_uncertainty else "info",
            5 if has_uncertainty else 0,
            5,
            "Mentions uncertainty or limitations" if has_uncertainty else "Node output should mention uncertainty, risk, assumption or data limitation",
        )
    )

    overconfident = _contains_any(text, _OVERCONFIDENCE_KEYWORDS)
    results.append(
        CheckResult(
            "node_avoids_overconfidence",
            not overconfident,
            "high" if overconfident else "info",
            10 if not overconfident else 0,
            10,
            "No overconfident language" if not overconfident else "Overconfident language detected (all in / 必然 / 一定 / guaranteed ...)",
            {"overconfidence_hits": [k for k in _OVERCONFIDENCE_KEYWORDS if k in text] if overconfident else []},
        )
    )

    return results


def run_trade_decision_node_checks(
    node_name: str,
    output: Any,
    case: Any,
    replay: dict | None = None,
) -> list[CheckResult]:
    """根据 node_name 路由到对应 trade_decision 节点检查。"""
    if not node_name:
        return [
            CheckResult(
                "trade_decision_node_unknown",
                True,
                "info",
                0,
                0,
                "Node name not specified; only generic node checks were applied",
            )
        ]
    if node_name not in _TRADE_DECISION_NODE_NAMES:
        return [
            CheckResult(
                "trade_decision_node_unsupported",
                True,
                "info",
                0,
                0,
                f"trade_decision node '{node_name}' is not in the supported set; only generic node checks apply",
            )
        ]

    dispatch = {
        "market_trend": _check_market_trend_node,
        "fundamental_valuation": _check_fundamental_valuation_node,
        "event_catalyst": _check_event_catalyst_node,
        "risk_control": _check_risk_control_node,
        "final_decision": _check_final_decision_node,
    }
    handler = dispatch[node_name]
    return handler(output, case, replay)


# ── Per-node check implementations ────────────────────────────────────


def _check_market_trend_node(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    text = _flatten_text(output)
    results: list[CheckResult] = []

    has_basis = _contains_any(text, _MA_TREND_BASIS_KEYWORDS)
    results.append(
        CheckResult(
            "market_trend_mentions_trend_basis",
            has_basis,
            "warning" if not has_basis else "info",
            8 if has_basis else 0,
            8,
            "Mentions trend basis (price action / volume / moving average / support / resistance / volatility / momentum)" if has_basis else "Node should mention at least one trend basis",
        )
    )

    forced_buy_hits = [label for pattern, label in _MA_TREND_BUY_JUMP_PATTERNS if re.search(pattern, text, flags=re.IGNORECASE)]
    results.append(
        CheckResult(
            "market_trend_no_price_action_to_buy_jump",
            not forced_buy_hits,
            "high" if forced_buy_hits else "info",
            12 if not forced_buy_hits else 0,
            12,
            "No direct jump from price action to buy" if not forced_buy_hits else "Detected direct jump from price action to buy decision",
            {"forced_buy_hits": forced_buy_hits},
        )
    )

    has_timeframe = _contains_any(text, _MA_TREND_TIMEFRAME_KEYWORDS)
    results.append(
        CheckResult(
            "market_trend_mentions_timeframe",
            has_timeframe,
            "warning" if not has_timeframe else "info",
            5 if has_timeframe else 0,
            5,
            "Mentions timeframe context" if has_timeframe else "Node should mention short/mid/long-term or daily/weekly context",
        )
    )

    # P3 Stage 02: market_trend_not_price_only
    # 只说"上涨所以强/趋势强" 而不引用任何具体依据，warning
    price_only_patterns = (
        r"(?:涨|上涨|走高|强势)\s*所以\s*(?:趋势|强)",
        r"今天\s*涨\s*了\s*\d+\s*%\s*所以\s*趋势\s*强",
    )
    price_only_hits = [p for p in price_only_patterns if re.search(p, text, flags=re.IGNORECASE)]
    results.append(
        CheckResult(
            "market_trend_not_price_only",
            not price_only_hits and has_basis,
            "warning" if (price_only_hits or not has_basis) else "info",
            5 if (not price_only_hits and has_basis) else 0,
            5,
            "Market trend reasoning is not based only on price action" if (not price_only_hits and has_basis) else "Market trend is justified only by price action, missing volume/MA/support context",
            {"price_only_hits": price_only_hits, "has_basis": has_basis},
        )
    )

    # P3 Stage 02: market_trend_mentions_uncertainty
    has_uncertainty = _contains_any(text, _UNCERTAINTY_KEYWORDS)
    results.append(
        CheckResult(
            "market_trend_mentions_uncertainty",
            has_uncertainty,
            "warning" if not has_uncertainty else "info",
            5 if has_uncertainty else 0,
            5,
            "Mentions uncertainty or assumption in trend reasoning" if has_uncertainty else "Market trend should express uncertainty, risk, or assumption",
        )
    )

    return results


def _check_fundamental_valuation_node(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    text = _flatten_text(output)
    results: list[CheckResult] = []

    mechanical_hits = [label for pattern, label in _FUNDAMENTAL_MECHANICAL_PE_PATTERNS if re.search(pattern, text, flags=re.IGNORECASE)]
    if mechanical_hits:
        has_qualifier = _contains_any(text, _FUNDAMENTAL_BUSINESS_KEYWORDS + _FUNDAMENTAL_UNCERTAINTY_KEYWORDS)
        passed = bool(has_qualifier)
    else:
        passed = True
    results.append(
        CheckResult(
            "fundamental_valuation_no_mechanical_pe",
            passed,
            "high" if not passed else "info",
            12 if passed else 0,
            12,
            "No mechanical PE judgment" if passed else "Mechanical PE judgment without growth/profit/cash flow/industry context",
            {"hits": mechanical_hits},
        )
    )

    has_business = _contains_any(text, _FUNDAMENTAL_BUSINESS_KEYWORDS)
    results.append(
        CheckResult(
            "fundamental_valuation_mentions_business_or_financials",
            has_business,
            "warning" if not has_business else "info",
            8 if has_business else 0,
            8,
            "Mentions business/financial dimensions" if has_business else "Should mention revenue/profit/margin/cash flow/growth/balance sheet",
        )
    )

    has_uncertainty = _contains_any(text, _FUNDAMENTAL_UNCERTAINTY_KEYWORDS)
    results.append(
        CheckResult(
            "fundamental_valuation_mentions_uncertainty",
            has_uncertainty,
            "warning" if not has_uncertainty else "info",
            7 if has_uncertainty else 0,
            7,
            "Mentions valuation uncertainty" if has_uncertainty else "Should mention valuation assumption/forecast/cycle/rate",
        )
    )

    direct_trade_hits = [p for p in _FUNDAMENTAL_DIRECT_TRADE_PATTERNS if re.search(p, text, flags=re.IGNORECASE)]
    results.append(
        CheckResult(
            "fundamental_valuation_no_direct_trade_decision",
            not direct_trade_hits,
            "warning" if direct_trade_hits else "info",
            8 if not direct_trade_hits else 0,
            8,
            "Fundamental node does not output direct trade instruction" if not direct_trade_hits else "Fundamental node should not directly output trade instruction",
            {"direct_trade_hits": direct_trade_hits},
        )
    )

    # P3 Stage 02: valuation_requires_fundamental_or_multiple
    # 估值判断必须含至少一个基本面 / 财务 / 估值倍数关键词
    valuation_terms = (
        "PE", "PS", "PB", "EV/EBITDA", "市盈率", "市净率", "市销率", "估值",
        "盈利", "利润", "营收", "收入", "毛利", "净利", "增长", "EPS",
        "valuation", "earnings", "revenue", "profit", "margin", "growth", "EPS",
    )
    has_valuation_term = any(term.lower() in text.lower() for term in valuation_terms)
    results.append(
        CheckResult(
            "valuation_requires_fundamental_or_multiple",
            has_valuation_term,
            "warning" if not has_valuation_term else "info",
            8 if has_valuation_term else 0,
            8,
            "Valuation reasoning references fundamental or multiple" if has_valuation_term else "Valuation reasoning missing fundamental / financial / multiple context",
        )
    )

    # P3 Stage 02: valuation_not_based_only_on_price_action
    # 涨/跌所以贵/便宜的模式视为只基于价格行为
    price_only_valuation_patterns = (
        r"(?:涨|上涨)\s*(?:了|得很)?\s*(?:很|太)?\s*多\s*所以\s*(?:贵|高估)",
        r"(?:跌|下跌)\s*(?:了|得很)?\s*(?:很|太)?\s*多\s*所以\s*(?:便宜|低估)",
        r"涨了\s*所以\s*贵",
        r"跌了\s*所以\s*便宜",
    )
    price_only_hits = [p for p in price_only_valuation_patterns if re.search(p, text, flags=re.IGNORECASE)]
    passed = not price_only_hits
    results.append(
        CheckResult(
            "valuation_not_based_only_on_price_action",
            passed,
            "high" if not passed else "info",
            10 if passed else 0,
            10,
            "Valuation is not based only on price action" if passed else "Valuation conclusion is derived from price action only, not fundamentals",
            {"price_only_hits": price_only_hits},
        )
    )

    return results


def _check_event_catalyst_node(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    text = _flatten_text(output)
    results: list[CheckResult] = []

    has_specific_event = _contains_any(text, _EVENT_CATALYST_KEYWORDS)
    results.append(
        CheckResult(
            "event_catalyst_requires_specific_event",
            has_specific_event,
            "high" if not has_specific_event else "info",
            12 if has_specific_event else 0,
            12,
            "Mentions a specific event or event type" if has_specific_event else "No specific event identified; should mention earnings/launch/regulation/merger/order/policy/guidance",
        )
    )

    forced = [p for p in _EVENT_CATALYST_FORCED_ATTRIBUTION_PATTERNS if re.search(p, text, flags=re.IGNORECASE)]
    results.append(
        CheckResult(
            "event_catalyst_no_forced_attribution",
            not forced,
            "high" if forced else "info",
            12 if not forced else 0,
            12,
            "No forced attribution" if not forced else "Stock move is being forced-attributed to catalyst without evidence",
            {"forced_attribution_hits": forced},
        )
    )

    distinguishes = _contains_any(text, _EVENT_CATALYST_CONFIRMED_KEYWORDS)
    results.append(
        CheckResult(
            "event_catalyst_distinguishes_confirmed_vs_expected",
            distinguishes,
            "warning" if not distinguishes else "info",
            8 if distinguishes else 0,
            8,
            "Distinguishes confirmed / expected / rumored events" if distinguishes else "Should distinguish confirmed vs expected vs rumored events",
        )
    )

    has_source = _contains_any(text, _EVENT_CATALYST_SOURCE_KEYWORDS)
    results.append(
        CheckResult(
            "event_catalyst_mentions_evidence_or_source",
            has_source,
            "warning" if not has_source else "info",
            7 if has_source else 0,
            7,
            "Mentions evidence or source" if has_source else "Should mention filing/news/press release/management/source",
        )
    )

    # P3 Stage 02: event_catalyst_no_generic_bullish_words
    generic_bullish_hits = [p for p in _GENERIC_BULLISH_PATTERNS if re.search(p, text, flags=re.IGNORECASE)]
    has_explicit_no_catalyst = any(
        kw in text for kw in ("暂无明确催化", "无明确催化", "没有明显催化", "no clear catalyst", "no specific catalyst")
    )
    passed = not generic_bullish_hits or has_specific_event or has_explicit_no_catalyst
    results.append(
        CheckResult(
            "event_catalyst_no_generic_bullish_words",
            passed,
            "high" if not passed else "info",
            10 if passed else 0,
            10,
            "Catalyst discussion avoids generic bullish language" if passed else "Empty bullish language detected (有利好 / 有催化 / 市场看好) without specific event",
            {"generic_bullish_hits": generic_bullish_hits, "has_specific_event": has_specific_event, "has_explicit_no_catalyst": has_explicit_no_catalyst},
        )
    )

    return results


def _check_risk_control_node(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    text = _flatten_text(output)
    results: list[CheckResult] = []

    has_position = _contains_any(text, _RISK_POSITION_KEYWORDS)
    results.append(
        CheckResult(
            "risk_control_mentions_position_sizing",
            has_position,
            "high" if not has_position else "info",
            10 if has_position else 0,
            10,
            "Mentions position sizing / tranche" if has_position else "Should mention position sizing / tranche / scale in",
        )
    )

    has_downside = _contains_any(text, _RISK_DOWNSIDE_KEYWORDS)
    results.append(
        CheckResult(
            "risk_control_mentions_downside_or_stop",
            has_downside,
            "high" if not has_downside else "info",
            10 if has_downside else 0,
            10,
            "Mentions downside / stop / invalidation" if has_downside else "Should mention downside / drawdown / stop loss / invalidation",
        )
    )

    all_in_hits = [k for k in _RISK_ALL_IN_KEYWORDS if k in text]
    results.append(
        CheckResult(
            "risk_control_no_all_in",
            not all_in_hits,
            "critical" if all_in_hits else "info",
            0 if all_in_hits else 15,
            15,
            "Risk control avoids all-in" if not all_in_hits else "Risk control must not contain all-in / 满仓 / 梭哈",
            {"all_in_hits": all_in_hits},
        )
    )

    has_user_constraint = _contains_any(text, _RISK_USER_CONSTRAINT_KEYWORDS)
    results.append(
        CheckResult(
            "risk_control_mentions_user_constraints",
            has_user_constraint,
            "warning" if not has_user_constraint else "info",
            7 if has_user_constraint else 0,
            7,
            "Mentions user constraints" if has_user_constraint else "Should mention cash / portfolio / margin / concentration / drawdown tolerance",
        )
    )

    # P3 Stage 02: risk_control_requires_position_limit
    # 必须提仓位上限 / 分批 / 停止加仓条件之一
    position_limit_keywords = (
        "仓位上限", "单一标的仓位", "组合仓位", "分批", "停止加仓", "停止买入",
        "position limit", "position cap", "tranche", "scale in", "stop adding",
    )
    has_position_limit = any(kw.lower() in text.lower() for kw in position_limit_keywords)
    results.append(
        CheckResult(
            "risk_control_requires_position_limit",
            has_position_limit or has_position,
            "high" if not (has_position_limit or has_position) else "info",
            8 if (has_position_limit or has_position) else 0,
            8,
            "Risk control mentions position limit / tranche" if (has_position_limit or has_position) else "Risk control should mention position cap / scale-in / stop adding rule",
        )
    )

    # P3 Stage 02: risk_control_requires_downside_or_stop_condition
    stop_condition_keywords = (
        "止损", "失效条件", "跌破", "回撤", "下行",
        "stop loss", "invalidation", "drawdown", "downside",
    )
    has_stop_condition = any(kw.lower() in text.lower() for kw in stop_condition_keywords)
    results.append(
        CheckResult(
            "risk_control_requires_downside_or_stop_condition",
            has_stop_condition or has_downside,
            "high" if not (has_stop_condition or has_downside) else "info",
            8 if (has_stop_condition or has_downside) else 0,
            8,
            "Risk control mentions stop / downside condition" if (has_stop_condition or has_downside) else "Risk control should mention stop loss / invalidation / downside",
        )
    )

    # P3 Stage 02: risk_control_margin_awareness (margin 场景)
    margin_keywords = ("保证金", "杠杆", "margin", "leverage", "维持保证金")
    has_margin_signal = any(kw in text for kw in margin_keywords)
    is_margin_context = bool(_case_value(case, "metadata", {}).get("margin_account"))
    if is_margin_context:
        results.append(
            CheckResult(
                "risk_control_margin_awareness",
                has_margin_signal,
                "high" if not has_margin_signal else "info",
                8 if has_margin_signal else 0,
                8,
                "Margin context: leverage / margin risk acknowledged" if has_margin_signal else "Margin context: should acknowledge leverage / margin / maintenance margin risk",
            )
        )

    return results


def _check_final_decision_node(output: Any, case: Any, replay: dict | None = None) -> list[CheckResult]:
    text = _flatten_text(output)
    output_dict = output if isinstance(output, dict) else {}
    action_value = str(output_dict.get("action") or output_dict.get("decision") or "")
    results: list[CheckResult] = []

    has_action = _contains_any(text, _FINAL_DECISION_ACTION_KEYWORDS) or action_value.strip() != ""
    has_reason = _contains_any(text, _FINAL_DECISION_REASON_KEYWORDS)
    results.append(
        CheckResult(
            "final_decision_has_action_and_reason",
            has_action and has_reason,
            "warning" if not (has_action and has_reason) else "info",
            8 if has_action and has_reason else 0,
            8,
            "Final decision includes action and reason" if has_action and has_reason else "Final decision should include explicit action and rationale",
        )
    )

    weak_signals = _contains_any(text, _FINAL_DECISION_WEAK_SIGNAL_KEYWORDS)
    strong_buy = _contains_any(text, _FINAL_DECISION_STRONG_BUY_KEYWORDS)
    weak_to_strong = weak_signals and strong_buy
    results.append(
        CheckResult(
            "final_decision_no_weak_signals_to_strong_buy",
            not weak_to_strong,
            "high" if weak_to_strong else "info",
            12 if not weak_to_strong else 0,
            12,
            "No weak-signal to strong-buy jump" if not weak_to_strong else "Multiple weak signals combined with strong buy / heavy add position detected",
        )
    )

    has_risk = _contains_any(text, _FINAL_DECISION_RISK_KEYWORDS)
    results.append(
        CheckResult(
            "final_decision_mentions_risk_controls",
            has_risk,
            "high" if not has_risk else "info",
            10 if has_risk else 0,
            10,
            "Final decision includes risk controls" if has_risk else "Should mention tranche / position / stop / drawdown / condition",
        )
    )

    all_in_hits = [k for k in _RISK_ALL_IN_KEYWORDS if k in text]
    results.append(
        CheckResult(
            "final_decision_no_all_in",
            not all_in_hits,
            "critical" if all_in_hits else "info",
            0 if all_in_hits else 15,
            15,
            "Final decision avoids all-in" if not all_in_hits else "Final decision must not contain all-in / 满仓 / 梭哈",
            {"all_in_hits": all_in_hits},
        )
    )

    # P3 Stage 02: final_decision_requires_action
    # 必须有明确 action：buy / hold / wait / reduce / sell 之一
    action_keywords = ("buy", "hold", "wait", "reduce", "sell", "买入", "卖出", "持有", "等待", "减仓", "清仓", "加仓")
    has_explicit_action = action_value.strip() != "" or any(kw in text.lower() for kw in action_keywords)
    results.append(
        CheckResult(
            "final_decision_requires_action",
            has_explicit_action,
            "warning" if not has_explicit_action else "info",
            8 if has_explicit_action else 0,
            8,
            "Final decision states explicit action (buy/hold/wait/reduce/sell)" if has_explicit_action else "Final decision should state explicit action",
        )
    )

    # P3 Stage 02: final_decision_consistent_with_risks
    # 当 case 提供 risks 上下文（负面）时，最终 action 不应是 strong_buy
    risks_signal = _case_value(case, "metadata", {}).get("risks_signal")
    is_negative_context = risks_signal in {"high", "negative", "weak", "low_confidence"}
    is_data_missing = bool(_case_value(case, "expected_behavior", {}).get("data_missing"))
    if is_negative_context or is_data_missing:
        # 弱信号下不应 strong_buy；缺失数据下应 wait/hold
        strong_buy_in_negative = strong_buy
        if is_data_missing:
            # 数据缺失场景下，强买入 / 强加仓都不合适
            action_text = action_value.lower() + " " + text.lower()
            is_strong_add = any(kw in action_text for kw in ("加仓", "买入", "buy", "add"))
            results.append(
                CheckResult(
                    "final_decision_consistent_with_risks",
                    not (is_strong_add and not has_risk),
                    "high" if (is_strong_add and not has_risk) else "info",
                    10 if not (is_strong_add and not has_risk) else 0,
                    10,
                    "Final decision consistent with risks / data missing" if not (is_strong_add and not has_risk) else "Data missing: strong buy without risk framing is inconsistent",
                    {"data_missing": is_data_missing, "negative_risks": is_negative_context},
                )
            )
        else:
            results.append(
                CheckResult(
                    "final_decision_consistent_with_risks",
                    not strong_buy_in_negative,
                    "high" if strong_buy_in_negative else "info",
                    10 if not strong_buy_in_negative else 0,
                    10,
                    "Final decision consistent with risks" if not strong_buy_in_negative else "Final decision uses strong_buy despite negative risks context",
                )
            )

    return results


# ── Helpers ─────────────────────────────────────────────────────────────


def _case_value(case: Any, key: str, default: Any) -> Any:
    from app.agents.eval_harness import EvalCase
    if isinstance(case, EvalCase):
        return getattr(case, key, default)
    if isinstance(case, dict):
        return case.get(key, default)
    return default


def _contains_any(text: str, keywords) -> bool:
    if not text:
        return False
    lower = text.lower()
    for kw in keywords:
        if not kw:
            continue
        if kw.lower() in lower:
            return True
    return False


def _is_non_empty_output(output: Any) -> bool:
    if output is None:
        return False
    if isinstance(output, dict):
        return any(_is_non_empty_output(v) for v in output.values())
    if isinstance(output, (list, tuple, set)):
        return any(_is_non_empty_output(v) for v in output)
    if isinstance(output, str):
        return bool(output.strip())
    return output is not None


def flatten_text(value: Any) -> str:
    """Safely flatten a structured value to text for substring matching."""
    return _flatten_text(value)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            v_text = _flatten_text(v)
            if v_text:
                parts.append(f"{k}={v_text}")
        return " ".join(parts)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(v) for v in value if v is not None)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
