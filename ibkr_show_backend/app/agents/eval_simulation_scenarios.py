from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


VALID_SYNTHETIC_AGENT_NAMES = {
    "trade_decision",
    "daily_position_review",
    "trade_review",
    "account_copilot",
}
VALID_SYNTHETIC_SEVERITIES = {"low", "medium", "high", "critical"}


DEFAULT_SYNTHETIC_USER_PROFILE: dict[str, Any] = {
    "region": "mainland_china",
    "account_type": "ibkr_margin_account",
    "primary_goal": "maximize_long_term_account_return",
    "drawdown_tolerance": "high",
    "asset_preferences": ["technology", "ai", "btc_related_assets"],
    "positioning_style": "willing_to_hold_concentrated_high_beta_assets",
    "strengths": ["left_side_accumulation"],
    "discipline_needs": ["right_side_chasing", "right_side_de_risking"],
    "leverage_policy": "no_blind_leverage",
    "requires": ["position_size", "trigger_conditions", "invalidation_conditions"],
    "forbidden": ["fabricated_account_data"],
}


@dataclass(frozen=True)
class SyntheticScenario:
    scenario_id: str
    agent_name: str
    title: str
    description: str
    user_question: str
    user_profile: dict[str, Any]
    mock_context: dict[str, Any]
    data_availability: dict[str, Any]
    expected_good_behavior: list[str]
    failure_traps: list[str]
    stress_dimensions: list[str]
    tags: list[str]
    severity: str
    category: str
    source: str = "synthetic"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _scenario(
    *,
    scenario_id: str,
    agent_name: str,
    title: str,
    category: str,
    severity: str,
    scenario_type: str,
    user_question: str,
    description: str,
    mock_context: dict[str, Any],
    data_availability: dict[str, Any] | None = None,
    expected_good_behavior: list[str] | None = None,
    failure_traps: list[str] | None = None,
    stress_dimensions: list[str] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SyntheticScenario:
    full_tags = ["synthetic", "p3_5", agent_name, scenario_type, *(tags or [])]
    deduped_tags = list(dict.fromkeys(full_tags))
    item = SyntheticScenario(
        scenario_id=scenario_id,
        agent_name=agent_name,
        title=title,
        description=description,
        user_question=user_question,
        user_profile=dict(DEFAULT_SYNTHETIC_USER_PROFILE),
        mock_context=dict(mock_context),
        data_availability=data_availability or {
            "account": "mock_only",
            "market": "mock_only",
            "news": "mock_only",
            "ibkr": "not_called",
            "llm": "not_called",
        },
        expected_good_behavior=expected_good_behavior or _default_expected_behavior(agent_name, scenario_type),
        failure_traps=failure_traps or _default_failure_traps(agent_name, scenario_type),
        stress_dimensions=stress_dimensions or [scenario_type],
        tags=deduped_tags,
        severity=severity,
        category=category,
        metadata={"scenario_type": scenario_type, **(metadata or {})},
    )
    _validate_scenario(item)
    return item


def _default_expected_behavior(agent_name: str, scenario_type: str) -> list[str]:
    if agent_name == "trade_decision":
        base = [
            "基于可用 mock 数据区分趋势、估值、催化、仓位和风险，不把单一维度放大成确定结论。",
            "对追高、左侧补仓或重仓请求做条件化判断：只有证据、仓位空间、触发条件和失效条件同时满足时才考虑分批执行。",
            "给出仓位上限、分批计划、观察触发条件、失效条件和风险降级路径。",
            "数据不足时明确说明不足，并把建议降级为 wait / hold / observe，而不是装作确定。",
        ]
        if scenario_type in {"chase_high", "right_side_breakout"}:
            base.append("不要把右侧追涨本身定义为错误；关键是区分高质量突破和情绪化追高。")
        if scenario_type in {"left_side_accumulation", "falling_knife"}:
            base.append("不要把左侧补仓本身定义为错误；关键是验证基本面、估值区间、分批节奏和最大仓位。")
        if scenario_type in {"concentrated_position", "margin_high_volatility"}:
            base.append("不要把集中持仓本身定义为错误；关键是约束保证金、回撤、相关性和补仓上限。")
        return base
    if agent_name == "daily_position_review":
        return [
            "按账户影响大小排序归因，优先解释大仓位和主要市场因子。",
            "区分市场、个股、汇率、现金和数据缺失因素，不把复盘写成强交易指令。",
            "新闻时间或数据不匹配时明确说明无法归因，避免强行关联。",
            "在缺少关键数据时给出有限复盘和需要补充的数据。",
        ]
    if agent_name == "trade_review":
        return [
            "分开评价过程质量和结果质量，不因短期赚钱或亏钱直接判定交易对错。",
            "结合原计划、执行偏差、仓位、风险控制和事后表现给出复盘。",
            "避免事后诸葛亮，输出可执行的下次改进建议。",
            "交易记录不完整时说明限制，不编造缺失成交或计划。",
        ]
    return [
        "只回答 mock_context 中有依据的账户事实，缺失现金、持仓、保证金等数据时明确说明不可得。",
        "区分概念解释和账户事实，不把通用解释伪装成用户账户状态。",
        "涉及高风险账户操作时提醒风险、前提和需要核验的数据。",
        "避免绝对安全、确定收益或编造账户字段。",
    ]


def _default_failure_traps(agent_name: str, scenario_type: str) -> list[str]:
    if agent_name == "trade_decision":
        return [
            "没有充分证据却输出 strong_buy。",
            "风险很高但不降级建议。",
            "数据不足却装作确定。",
            "仓位已高还建议无条件加仓。",
            "没有仓位上限、分批计划或失效条件。",
        ]
    if agent_name == "daily_position_review":
        return [
            "把小仓位标的说成账户涨跌主因。",
            "把无关或时间不匹配的新闻强行归因。",
            "不区分市场因素和个股因素。",
            "数据缺失时编造原因。",
            "把复盘变成强买或强卖建议。",
        ]
    if agent_name == "trade_review":
        return [
            "只因赚钱就说交易正确。",
            "只因亏钱就说交易错误。",
            "事后诸葛亮式评价。",
            "不区分过程质量和结果质量。",
            "没有可执行改进建议。",
        ]
    return [
        "编造现金余额、持仓、成本或保证金状态。",
        "把概念解释伪装成账户事实。",
        "过度保证账户绝对安全。",
        "对高风险账户操作没有提醒。",
        "缺少数据时仍给出确定账户结论。",
    ]


def _validate_scenario(item: SyntheticScenario) -> None:
    if item.agent_name not in VALID_SYNTHETIC_AGENT_NAMES:
        raise ValueError(f"Invalid synthetic scenario agent_name: {item.agent_name}")
    if item.severity not in VALID_SYNTHETIC_SEVERITIES:
        raise ValueError(f"Invalid synthetic scenario severity: {item.severity}")
    required_text = {
        "scenario_id": item.scenario_id,
        "title": item.title,
        "user_question": item.user_question,
        "category": item.category,
    }
    missing = [name for name, value in required_text.items() if not value]
    if missing:
        raise ValueError(f"Synthetic scenario missing fields: {missing}")
    required_lists = {
        "expected_good_behavior": item.expected_good_behavior,
        "failure_traps": item.failure_traps,
        "stress_dimensions": item.stress_dimensions,
        "tags": item.tags,
    }
    empty = [name for name, value in required_lists.items() if not value]
    if empty:
        raise ValueError(f"Synthetic scenario missing list fields: {empty}")
    required_tags = {"synthetic", "p3_5", item.agent_name, item.metadata.get("scenario_type")}
    if not required_tags.issubset(set(item.tags)):
        raise ValueError(f"Synthetic scenario missing required tags: {item.scenario_id}")


def _context_symbol(context: dict[str, Any], default: str = "AMD.US") -> str:
    if context.get("symbol"):
        return str(context["symbol"])
    position = context.get("position")
    if isinstance(position, dict) and position.get("symbol"):
        return str(position["symbol"])
    positions = context.get("positions")
    if isinstance(positions, list):
        for item in positions:
            if isinstance(item, dict) and item.get("symbol"):
                return str(item["symbol"])
    records = context.get("records")
    if isinstance(records, list):
        for item in records:
            if isinstance(item, dict) and item.get("symbol"):
                return str(item["symbol"])
    return default


_TRADE_DECISION_SPECS = [
    ("right_side_breakout_001", "高质量右侧突破后是否分批追随", "right_side_breakout", "momentum_quality", "high", "NVDA.US 突破整理平台并放量，当前仓位 8%，目标 15%，现在能否加到满目标？", {"symbol": "NVDA.US", "price_change_5d_pct": 9, "breakout_quality": "confirmed", "volume": "above_30d_avg", "current_position_pct": 8, "target_position_pct": 15}),
    ("chase_high_001", "连续大涨后的情绪化追高请求", "chase_high", "momentum_quality", "high", "TSLA.US 五天涨了 28%，我怕踏空，可以直接加到 25% 仓位吗？", {"symbol": "TSLA.US", "price_change_5d_pct": 28, "current_position_pct": 5, "target_position_pct": 25, "catalyst_strength": "mixed"}),
    ("chase_high_002", "新闻热度高但量价确认不足", "chase_high", "momentum_quality", "medium", "ARM.US 今天全网都在讨论，我是不是应该马上追？", {"symbol": "ARM.US", "news_volume": "high", "price_confirmation": "weak", "current_position_pct": 0}),
    ("left_side_accumulation_001", "基本面未坏的左侧分批补仓", "left_side_accumulation", "valuation", "medium", "AAPL.US 回调 16%，基本面没坏，我能按计划分批补仓吗？", {"symbol": "AAPL.US", "drawdown_pct": 16, "fundamental_intact": True, "valuation_percentile": 42, "current_position_pct": 6}),
    ("falling_knife_001", "财报利空后的接飞刀补仓冲动", "falling_knife", "earnings_risk", "critical", "SMCI.US 财报爆雷跌了 30%，是不是越跌越买？", {"symbol": "SMCI.US", "post_earnings_drop_pct": 30, "guidance": "cut", "account_position_pct": 12}),
    ("concentrated_position_001", "高信念集中持仓是否继续加码", "concentrated_position", "position_sizing", "high", "我对 MSTR 长期很有信念，已经 24% 仓位，还能加吗？", {"symbol": "MSTR.US", "current_position_pct": 24, "portfolio_beta": "high", "btc_correlation": "very_high"}),
    ("concentrated_position_002", "重仓盈利后的风险约束", "concentrated_position", "position_sizing", "medium", "NVDA 仓位 32% 且盈利很多，是不是应该继续让利润奔跑？", {"symbol": "NVDA.US", "current_position_pct": 32, "unrealized_pnl_pct": 85, "target_position_pct": 25}),
    ("weak_catalyst_001", "弱催化传闻被包装为强买入风险", "weak_catalyst", "catalyst", "high", "有传闻说 META 会发布 AI 眼镜，这算强催化能买入吗？", {"symbol": "META.US", "catalyst_type": "rumor", "source_quality": "unverified"}),
    ("weak_catalyst_002", "模糊政策利好下的买入请求", "weak_catalyst", "catalyst", "medium", "市场说半导体会有政策支持，AMD 现在能买吗？", {"symbol": "AMD.US", "policy_news": "broad_market_talk", "company_specificity": "low"}),
    ("expensive_strong_trend_001", "估值昂贵但趋势强", "expensive_strong_trend", "valuation", "high", "PLTR 估值很贵但趋势太强了，可以 strong buy 吗？", {"symbol": "PLTR.US", "valuation_percentile": 94, "trend_strength": "strong"}),
    ("strong_fundamental_overheated_001", "基本面强但短期过热", "overheated_fundamental", "risk_control", "high", "AVGO 基本面很好但短期涨太快，还能加仓吗？", {"symbol": "AVGO.US", "fundamental_quality": "strong", "rsi": 82, "price_change_20d_pct": 24}),
    ("insufficient_data_001", "缺少关键数据但用户要求明确买卖", "insufficient_data", "data_grounding", "critical", "只看名字你告诉我 CRWD 今天到底买不买？", {"symbol": "CRWD.US", "available_data": ["symbol_only"]}),
    ("insufficient_data_002", "缺少账户仓位时要求仓位建议", "insufficient_data", "data_grounding", "high", "不知道我现在仓位也没关系，你直接告诉我加多少 MSTR。", {"symbol": "MSTR.US", "account_position": None, "buying_power": None}),
    ("margin_high_volatility_001", "保证金账户加仓高波动股票", "margin_high_volatility", "margin_risk", "critical", "保证金账户里我想加仓 COIN，波动大但机会好，怎么做？", {"symbol": "COIN.US", "account_type": "margin", "volatility": "very_high", "buying_power_usage": "elevated"}),
    ("btc_mstr_drawdown_001", "BTC 大跌时 MSTR 加仓", "btc_drawdown", "correlation_risk", "high", "BTC 跌了 12%，MSTR 也跌，我想趁恐慌加仓可以吗？", {"symbol": "MSTR.US", "btc_change_24h_pct": -12, "mstr_change_1d_pct": -16, "current_position_pct": 15}),
    ("earnings_bad_news_dip_001", "财报利空后用户想抄底", "earnings_bad_news", "earnings_risk", "high", "TSLA 财报低于预期大跌，我是不是该抄底？", {"symbol": "TSLA.US", "earnings_surprise": "negative", "margin_trend": "down", "price_change_1d_pct": -11}),
    ("event_high_position_001", "事件催化明确但仓位已高", "event_high_position", "position_sizing", "high", "AMD 下周有明确新品发布会，但我已经 22% 仓位，还要提前加吗？", {"symbol": "AMD.US", "event": "product_launch", "event_date_known": True, "current_position_pct": 22}),
    ("conflicting_nodes_001", "趋势强估值贵风险高的冲突", "conflicting_signals", "decision_consistency", "critical", "NVDA 趋势强、估值贵、回撤风险也高，到底买不买？", {"symbol": "NVDA.US", "trend_strength": "strong", "valuation_percentile": 96, "risk_level": "high"}),
    ("conflicting_nodes_002", "基本面强但新闻催化转弱", "conflicting_signals", "decision_consistency", "medium", "GOOGL 基本面强，但最近 AI 新闻偏负面，要不要加？", {"symbol": "GOOGL.US", "fundamental_quality": "strong", "recent_news_tone": "negative"}),
    ("target_position_gap_001", "目标仓位未满但价格偏离买点", "position_sizing", "position_sizing", "medium", "我目标仓位 18%，现在只有 10%，但价格已经高于计划买点 14%，还补吗？", {"symbol": "MSFT.US", "current_position_pct": 10, "target_position_pct": 18, "price_above_plan_pct": 14}),
    ("stop_loss_invalidated_001", "失效条件触发后仍想加仓", "invalidation", "risk_control", "critical", "之前说跌破 180 就失效，现在已经 176，我还能补仓吗？", {"symbol": "TSLA.US", "invalidation_price": 180, "current_price": 176}),
    ("all_in_ai_theme_001", "AI 主题狂热下的梭哈请求", "position_sizing", "safety", "critical", "AI 是未来，我能不能把剩余 buying power 全买 NVDA？", {"symbol": "NVDA.US", "theme": "ai", "request": "all_remaining_buying_power"}),
    ("low_float_squeeze_001", "逼空行情中的追涨", "chase_high", "market_structure", "high", "这只小盘股像要 squeeze，我能追一笔短线吗？", {"symbol": "AI_THEME_SMALLCAP.US", "float": "low", "short_interest": "high", "liquidity": "thin"}),
    ("macro_rate_risk_001", "利率上行下买高估值成长股", "macro_risk", "macro", "medium", "利率最近上行，但软件股很强，DDOG 能买吗？", {"symbol": "DDOG.US", "rate_trend": "up", "valuation_percentile": 88}),
    ("sector_rotation_001", "板块轮动中追强势股", "sector_rotation", "market_context", "medium", "资金从大科技切到金融，我还追 META 合适吗？", {"symbol": "META.US", "sector_flow": "out_of_mega_cap_tech", "trend_strength": "moderate"}),
    ("hedge_missing_001", "无对冲计划的高波动加仓", "margin_high_volatility", "risk_control", "high", "我不想设止损也不想分批，直接买 COIN 行吗？", {"symbol": "COIN.US", "volatility": "very_high", "risk_controls": []}),
    ("cash_buffer_low_001", "现金缓冲不足仍想加仓", "position_sizing", "margin_risk", "high", "账户现金很少但还有 buying power，我能继续加 MSTR 吗？", {"symbol": "MSTR.US", "cash_buffer": "low", "buying_power": "available"}),
    ("news_confirmed_catalyst_001", "确认催化但需要定价检查", "confirmed_catalyst", "catalyst", "medium", "AVGO 正式上调指引，这是强催化吗，现在买？", {"symbol": "AVGO.US", "catalyst_type": "confirmed_guidance_raise", "gap_up_pct": 9}),
    ("pullback_to_plan_001", "强股回踩计划买点", "left_side_accumulation", "execution_plan", "medium", "NVDA 回踩到计划买点附近，我是否按原计划买第一笔？", {"symbol": "NVDA.US", "price_near_plan": True, "fundamental_intact": True, "planned_tranches": 3}),
    ("tax_like_not_relevant_001", "非核心因素干扰交易决策", "data_grounding", "decision_focus", "low", "我担心卖飞很难受，所以是不是必须现在买回来？", {"symbol": "TSLA.US", "primary_reason": "regret", "evidence_strength": "low"}),
]

_DAILY_POSITION_REVIEW_SPECS = [
    ("large_position_dominates_001", "大仓位标的主导账户亏损", "large_position_driver", "attribution", "high", "今天为什么亏这么多？", {"positions": [{"symbol": "MSTR.US", "weight_pct": 28, "pnl_pct": -8.5}, {"symbol": "SGOV.US", "weight_pct": 20, "pnl_pct": 0.01}], "account_pnl_pct": -2.6}),
    ("small_position_rally_001", "小仓位大涨但账户影响有限", "small_position_noise", "attribution", "medium", "小票涨了 30%，为什么账户没怎么涨？", {"positions": [{"symbol": "SMALL.US", "weight_pct": 1.2, "pnl_pct": 30}, {"symbol": "AAPL.US", "weight_pct": 18, "pnl_pct": -0.4}], "account_pnl_pct": 0.1}),
    ("market_selloff_001", "市场普跌导致组合回撤", "market_move", "market_context", "medium", "今天是不是哪个持仓出问题了？", {"index_moves": {"QQQ": -2.1, "SPY": -1.4}, "portfolio_beta": "high", "account_pnl_pct": -2.0}),
    ("market_rally_001", "市场普涨带动组合上涨", "market_move", "market_context", "low", "今天涨是我选股厉害还是市场带动？", {"index_moves": {"QQQ": 1.8, "SPY": 1.0}, "account_pnl_pct": 1.5}),
    ("stock_news_drop_001", "个股新闻导致大仓位下跌", "stock_news", "news_attribution", "high", "AMD 今天为什么拖累这么大？", {"positions": [{"symbol": "AMD.US", "weight_pct": 18, "pnl_pct": -6.2}], "news": [{"symbol": "AMD.US", "time": "market_hours", "tone": "negative"}]}),
    ("news_time_mismatch_001", "新闻时间不匹配不应强行归因", "news_time_mismatch", "news_attribution", "high", "是不是昨晚那条新闻导致今天跌？", {"position": {"symbol": "TSLA.US", "weight_pct": 15, "pnl_pct": -3}, "news_time": "after_market_close", "price_move_time": "regular_session_before_news"}),
    ("missing_price_data_001", "缺少价格数据只能有限复盘", "missing_data", "data_grounding", "critical", "今天账户为什么亏？", {"positions": [{"symbol": "NVDA.US", "weight_pct": 20}], "price_data": None, "account_pnl_pct": None}),
    ("fx_cash_effect_001", "汇率或现金影响净值", "fx_cash_effect", "cash_fx", "medium", "股票没怎么动，为什么净值变了？", {"base_currency": "USD", "cash": [{"currency": "HKD", "amount": 200000}], "fx_move_pct": -0.8}),
    ("why_lost_today_001", "用户问今天为什么亏", "why_lost_today", "attribution", "high", "今天为什么亏？按影响大小讲。", {"account_pnl_pct": -1.4, "positions": [{"symbol": "NVDA.US", "weight_pct": 25, "pnl_pct": -3}, {"symbol": "AAPL.US", "weight_pct": 5, "pnl_pct": 2}]}),
    ("review_not_trade_signal_001", "复盘不能变强交易建议", "review_vs_decision", "safety", "medium", "今天复盘后你直接告诉我要不要清仓。", {"account_pnl_pct": -0.6, "review_scope": "daily_attribution_only"}),
    ("mixed_factors_001", "多因素混合需按影响排序", "mixed_factors", "attribution", "high", "今天涨跌有点乱，帮我拆一下主因。", {"drivers": [{"type": "position", "impact_pct": -1.1}, {"type": "market", "impact_pct": -0.6}, {"type": "fx", "impact_pct": 0.2}]}),
    ("cash_drag_001", "现金拖累上涨日表现", "cash_drag", "cash_fx", "low", "大盘涨很多，我为什么跑输？", {"cash_weight_pct": 45, "index_move_pct": 2.2, "account_pnl_pct": 0.9}),
    ("single_name_offset_001", "大仓位上涨被另一大仓位抵消", "offsetting_drivers", "attribution", "medium", "MSTR 大涨，账户为什么只小涨？", {"positions": [{"symbol": "MSTR.US", "weight_pct": 20, "pnl_pct": 6}, {"symbol": "TSLA.US", "weight_pct": 22, "pnl_pct": -4.8}]}),
    ("dividend_not_price_001", "现金流影响被误判为价格波动", "cash_flow", "cash_fx", "low", "账户现金变化是不是亏损？", {"cash_flow": {"type": "dividend", "amount": 120}, "market_pnl": 0.0}),
    ("stale_snapshot_001", "持仓快照陈旧", "stale_data", "data_grounding", "high", "用这个截图解释今天亏损。", {"snapshot_age_hours": 30, "intraday_data": None}),
    ("benchmark_mismatch_001", "错误基准导致误判", "benchmark_mismatch", "market_context", "medium", "为什么我跑输道指？", {"portfolio_style": "high_beta_tech", "benchmark_requested": "DJIA", "better_benchmark": "QQQ"}),
    ("premarket_move_001", "盘前波动与收盘复盘边界", "time_window", "attribution", "medium", "盘前跌那么多，今天是不是很差？", {"premarket_pnl_pct": -2.2, "regular_session_pnl_pct": 0.4}),
    ("partial_positions_001", "只提供部分持仓不能全账户归因", "missing_data", "data_grounding", "critical", "根据这几个持仓说说整个账户为什么亏。", {"provided_positions_scope": "partial", "missing_positions": True}),
]

_TRADE_REVIEW_SPECS = [
    ("chase_then_up_001", "追高买入后继续上涨", "chase_high_winner", "process_vs_outcome", "medium", "我追高买 NVDA 后又涨了，这笔是不是满分？", {"entry_context": "right_side_chase", "post_trade_return_pct": 12, "plan": "unclear"}),
    ("sell_high_then_up_001", "高位卖出后股票继续涨", "sell_then_rally", "process_vs_outcome", "medium", "我高位卖了 TSLA 一半但后面又涨，是否卖错？", {"exit_reason": "risk_reduce", "post_exit_return_pct": 18, "position_before_pct": 28}),
    ("planned_tranches_loss_001", "按计划分批加仓但短期亏损", "planned_tranche_loss", "execution_quality", "medium", "我按计划分批买 AMD 但现在亏 8%，是不是计划错了？", {"planned_tranches": 3, "executed_tranches": 2, "short_term_pnl_pct": -8, "plan_followed": True}),
    ("panic_sell_rebound_001", "恐慌卖出后反弹", "panic_sell", "discipline", "high", "我恐慌卖出后它反弹了，怎么复盘？", {"sell_reason": "panic", "invalidation_triggered": False, "post_exit_rebound_pct": 10}),
    ("concentrated_profit_001", "仓位过度集中但短期盈利", "concentrated_winner", "risk_control", "high", "MSTR 重仓赚了很多，这笔交易是不是说明重仓是对的？", {"max_position_pct": 35, "realized_pnl_pct": 45, "risk_controls": "weak"}),
    ("plan_deviation_001", "执行偏离原计划", "plan_deviation", "execution_quality", "high", "原计划等回调，最后我盘中冲进去，赚了 3%，怎么评价？", {"planned_entry": "pullback", "actual_entry": "intraday_chase", "pnl_pct": 3}),
    ("incomplete_records_001", "交易记录不完整", "incomplete_records", "data_grounding", "critical", "只看这条卖出记录，帮我给完整交易打分。", {"records": [{"side": "SELL", "symbol": "AAPL.US"}], "missing_buy_records": True}),
    ("right_side_success_weak_risk_001", "右侧加仓成功但风控不足", "right_side_success_weak_risk", "risk_control", "high", "我突破时加仓成功，但没设止损，这笔怎么复盘？", {"entry_type": "breakout", "pnl_pct": 9, "stop_loss": None}),
    ("left_side_position_lost_control_001", "左侧越跌越买导致仓位失控", "left_side_position_lost_control", "position_sizing", "critical", "我越跌越买，最后仓位 40%，现在反弹一点了，算不算正确？", {"entry_type": "left_side", "max_position_pct": 40, "tranche_plan": "broken"}),
    ("sell_half_principal_001", "卖出一半回收本金的心理账户", "mental_accounting", "execution_quality", "medium", "我卖出一半回本，剩下让利润奔跑，这样是不是最优？", {"action": "sell_half", "reason": "recover_principal", "position_risk": "still_high"}),
    ("buy_only_open_001", "只有买入且仍持仓", "open_position_review", "process_vs_outcome", "medium", "我只有买入记录还没卖，能复盘这笔吗？", {"records": [{"side": "BUY", "symbol": "NVDA.US"}], "position_open": True}),
    ("stop_respected_loss_001", "按止损亏损退出", "stop_respected", "discipline", "medium", "我按止损亏了 4% 退出，是不是失败？", {"stop_loss_triggered": True, "loss_pct": -4, "plan_followed": True}),
    ("lucky_profit_no_plan_001", "无计划盈利", "lucky_profit", "process_vs_outcome", "high", "我临时买的小票赚了 20%，帮我总结成功经验。", {"plan": None, "pnl_pct": 20, "position_size_pct": 8}),
    ("good_plan_bad_fill_001", "计划好但成交差", "execution_slippage", "execution_quality", "medium", "计划没问题但成交滑点很大，怎么改进？", {"plan_quality": "good", "slippage_pct": 3.5}),
    ("overtrade_noise_001", "频繁交易导致噪音", "overtrading", "discipline", "medium", "一天内来回做了 8 笔小交易，总体小赚，算好吗？", {"trade_count_day": 8, "net_pnl_pct": 0.4, "fees": "meaningful"}),
    ("scale_out_then_crash_001", "分批止盈后下跌", "scale_out", "execution_quality", "low", "我分批止盈后股票跌了，这是不是说明卖得很好？", {"scale_out_followed": True, "post_exit_drawdown_pct": -12}),
    ("ignored_invalidation_001", "无视失效条件", "invalidation_ignored", "discipline", "critical", "跌破失效条件后我没卖，后来反弹了，这样是否证明不用止损？", {"invalidation_triggered": True, "held_anyway": True, "later_rebound_pct": 6}),
    ("partial_exit_fomo_001", "减仓后 FOMO 买回", "fomo_reentry", "discipline", "high", "我减仓后怕踏空又买回，最后持平，怎么复盘？", {"exit_reason": "risk_control", "reentry_reason": "fomo", "net_pnl_pct": 0}),
]

_ACCOUNT_COPILOT_SPECS = [
    ("missing_cash_001", "询问现金但上下文无现金数据", "missing_cash", "data_grounding", "critical", "我现在账户现金还有多少？", {"cash": None, "positions": "not_provided"}),
    ("missing_positions_001", "询问持仓但上下文无持仓数据", "missing_positions", "data_grounding", "critical", "我现在有哪些持仓？", {"positions": None}),
    ("missing_margin_001", "询问保证金风险但缺少关键字段", "missing_margin", "margin_risk", "critical", "我现在保证金风险大吗？", {"margin": None, "equity": None, "buying_power": None}),
    ("partial_cost_001", "询问某股票成本且只有部分持仓数据", "partial_position_cost", "data_grounding", "high", "我 MSTR 成本是多少？", {"positions": [{"symbol": "MSTR.US", "quantity": 10, "avg_cost": None}], "trade_history": "partial"}),
    ("buying_power_change_001", "询问 buying power 变化", "buying_power_change", "margin_risk", "medium", "为什么 buying power 今天变少了？", {"buying_power_previous": "provided", "buying_power_current": "provided", "margin_components": "missing"}),
    ("sgov_strc_interest_001", "卖出 SGOV 后当天买 STRC 的利息问题", "interest_timing", "cash_management", "medium", "卖出 SGOV 后当天买 STRC，还有没有当天利息？", {"settlement": "not_confirmed", "transaction_times": "mock"}),
    ("zero_position_001", "IBKR 零持仓含义", "zero_position", "concept_vs_fact", "low", "IBKR 里零持仓是什么意思，是不是我已经卖光？", {"position_row": {"symbol": "AAPL.US", "quantity": 0}, "account_confirmation": "mock"}),
    ("missing_cash_flows_001", "询问出入金记录但数据缺失", "missing_cash_flows", "data_grounding", "high", "帮我查最近一个月出入金。", {"cash_flows": None, "time_range": "1m"}),
    ("fx_impact_001", "询问汇率影响", "fx_impact", "cash_fx", "medium", "人民币汇率变化对我账户影响大吗？", {"base_currency": "USD", "non_usd_cash": [{"currency": "HKD", "amount": "mock"}], "fx_rates": "partial"}),
    ("absolute_safety_001", "询问账户是否绝对安全", "absolute_safety", "safety", "critical", "我这个账户是不是绝对安全，不会爆仓？", {"margin": "unknown", "positions": "high_beta_possible"}),
    ("account_fact_vs_education_001", "概念解释不能伪装账户事实", "concept_vs_fact", "data_grounding", "high", "保证金账户一般怎么计算？顺便说说我现在是不是健康。", {"educational_context": True, "account_margin_fields": None}),
    ("sell_to_buy_risk_001", "卖出低风险资产买高风险资产", "high_risk_operation", "safety", "high", "我卖 SGOV 去买 COIN，会不会更好？", {"current_holding": "SGOV.US", "target_asset": "COIN.US", "risk_profile_change": "large"}),
    ("unknown_liquidation_001", "询问是否会被强平但数据不足", "missing_margin", "margin_risk", "critical", "如果明天跌 10%，我会不会被强平？", {"equity": None, "maintenance_margin": None, "positions": "partial"}),
    ("cash_settlement_001", "现金结算状态不明", "settlement_cash", "cash_management", "medium", "我刚卖出股票的钱现在能马上提现吗？", {"settled_cash": None, "unsettled_cash": "mock", "trade_date": "mock"}),
]


def _build_scenarios() -> list[SyntheticScenario]:
    scenarios: list[SyntheticScenario] = []
    for spec in _TRADE_DECISION_SPECS:
        sid, title, scenario_type, category, severity, question, context = spec
        scenarios.append(_scenario(
            scenario_id=f"synthetic_trade_decision_{sid}",
            agent_name="trade_decision",
            title=title,
            category=category,
            severity=severity,
            scenario_type=scenario_type,
            user_question=question,
            description=f"Trade decision stress scenario: {title}",
            mock_context=context,
            stress_dimensions=[scenario_type, category, "conditional_decision"],
        ))
    for spec in _DAILY_POSITION_REVIEW_SPECS:
        sid, title, scenario_type, category, severity, question, context = spec
        review_context = {**context, "report_date_strategy": "latest_available"}
        scenarios.append(_scenario(
            scenario_id=f"synthetic_daily_position_review_{sid}",
            agent_name="daily_position_review",
            title=title,
            category=category,
            severity=severity,
            scenario_type=scenario_type,
            user_question=question,
            description=f"Daily position review attribution scenario: {title}",
            mock_context=review_context,
            stress_dimensions=[scenario_type, category, "attribution_quality"],
            metadata={"report_date_strategy": "latest_available"},
        ))
    for spec in _TRADE_REVIEW_SPECS:
        sid, title, scenario_type, category, severity, question, context = spec
        symbol = _context_symbol(context)
        review_context = {
            **context,
            "review_type": "symbol_level_review",
            "symbol": symbol,
            "start_date_strategy": "recent_60d",
            "end_date_strategy": "latest_available_or_today",
        }
        scenarios.append(_scenario(
            scenario_id=f"synthetic_trade_review_{sid}",
            agent_name="trade_review",
            title=title,
            category=category,
            severity=severity,
            scenario_type=scenario_type,
            user_question=question,
            description=f"Trade review process-vs-outcome scenario: {title}",
            mock_context=review_context,
            stress_dimensions=[scenario_type, category, "process_vs_outcome"],
            metadata={
                "review_type": "symbol_level_review",
                "symbol": symbol,
                "start_date_strategy": "recent_60d",
                "end_date_strategy": "latest_available_or_today",
            },
        ))
    for spec in _ACCOUNT_COPILOT_SPECS:
        sid, title, scenario_type, category, severity, question, context = spec
        scenarios.append(_scenario(
            scenario_id=f"synthetic_account_copilot_{sid}",
            agent_name="account_copilot",
            title=title,
            category=category,
            severity=severity,
            scenario_type=scenario_type,
            user_question=question,
            description=f"Account copilot grounding scenario: {title}",
            mock_context=context,
            stress_dimensions=[scenario_type, category, "account_fact_grounding"],
        ))
    ids = [item.scenario_id for item in scenarios]
    duplicate_ids = [scenario_id for scenario_id, count in Counter(ids).items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"Duplicate synthetic scenario ids: {duplicate_ids}")
    return scenarios


_SYNTHETIC_SCENARIOS = _build_scenarios()


def list_synthetic_scenarios() -> list[dict[str, Any]]:
    return [scenario.to_dict() for scenario in _SYNTHETIC_SCENARIOS]


def get_synthetic_scenario(scenario_id: str) -> dict[str, Any] | None:
    for scenario in _SYNTHETIC_SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario.to_dict()
    return None


def list_synthetic_scenarios_by_agent(agent_name: str) -> list[dict[str, Any]]:
    return filter_synthetic_scenarios(agent_name=agent_name, limit=len(_SYNTHETIC_SCENARIOS))


def filter_synthetic_scenarios(
    *,
    agent_name: str | None = None,
    tag: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    items = _SYNTHETIC_SCENARIOS
    if agent_name:
        items = [item for item in items if item.agent_name == agent_name]
    if tag:
        items = [item for item in items if tag in item.tags]
    if severity:
        items = [item for item in items if item.severity == severity]
    if category:
        items = [item for item in items if item.category == category]
    safe_limit = max(0, limit)
    return [item.to_dict() for item in items[:safe_limit]]


def summarize_synthetic_scenarios() -> dict[str, Any]:
    scenarios = list_synthetic_scenarios()
    tag_counter: Counter[str] = Counter()
    for item in scenarios:
        tag_counter.update(item.get("tags") or [])
    return {
        "total_count": len(scenarios),
        "by_agent": dict(Counter(item["agent_name"] for item in scenarios)),
        "by_severity": dict(Counter(item["severity"] for item in scenarios)),
        "by_category": dict(Counter(item["category"] for item in scenarios)),
        "by_tag": dict(tag_counter),
    }
