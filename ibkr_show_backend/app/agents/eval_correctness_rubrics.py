"""Eval P3 · Stage 01 · 全局 Agent 正确性标准 Rubric。

提供：

1. `GLOBAL_CORRECTNESS_DIMENSIONS`：八个全局正确性维度。
2. `AGENT_TYPE_MAPPING`：当前 Agent 名 → Agent 类型分类。
3. `AGENT_TYPE_DESCRIPTIONS`：每类 Agent 的评测重点。
4. `helper` 函数：`get_agent_type`、`get_dimensions_for_agent`、`build_global_judge_questions`。
"""

from __future__ import annotations

from typing import Any


AGENT_TYPE_MAPPING: dict[str, str] = {
    "trade_decision": "decision_agent",
    "daily_position_review": "review_agent",
    "trade_review": "review_agent",
    "account_copilot": "account_agent",
}


AGENT_TYPE_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "decision_agent": {
        "title": "交易决策类",
        "description": "针对单一标的给出方向、价位、仓位、止损、失效条件的具体建议。",
        "focus": [
            "action 是否合理（buy / sell / hold / wait）",
            "归因是否扎实（数据 / 事件 / 估值 / 趋势）",
            "风险是否完整（下行 / 失效条件 / 仓位）",
            "是否过度承诺（一定涨 / 必买 / 无风险）",
            "是否在用户已知约束下还违规操作",
        ],
    },
    "review_agent": {
        "title": "复盘分析类",
        "description": "对已发生持仓、交易、当日账户表现做归因、风险、建议输出。",
        "focus": [
            "复盘归因是否准确、不过度归因",
            "是否区分已发生与预期、传闻与确认",
            "用户可执行的建议（观察、调整、减仓、继续）",
            "风险与限制声明",
            "输出与当日 / 历史数据是否对得上",
        ],
    },
    "account_agent": {
        "title": "账户问答类",
        "description": "对账户、持仓、交易、现金、保证金的问答。",
        "focus": [
            "数据准确性（不编造现金、持仓、成本、保证金）",
            "是否越权给交易建议（应转人工或 skill approval）",
            "是否清晰表达数据限制 / 不可访问",
            "是否引用具体账户字段或工具返回",
            "对概念解释类问题是否答非所问",
        ],
    },
    "news_event_agent": {
        "title": "新闻事件分析类",
        "description": "对新闻、事件、公告的解读与影响分析。",
        "focus": [
            "事件归因是否区分传闻 / 预期 / 已发生",
            "是否给出对标的、行业的具体影响",
            "是否引用来源",
            "是否避免单条新闻 → 强行结论",
        ],
    },
    "risk_agent": {
        "title": "风险控制类",
        "description": "对组合、仓位、风险指标的监控与建议。",
        "focus": [
            "风险点是否被完整覆盖",
            "是否给出可执行监控指标",
            "紧急情况是否给出明确处置",
            "是否过度保守或过度激进",
        ],
    },
}


GLOBAL_CORRECTNESS_DIMENSIONS: dict[str, dict[str, Any]] = {
    "factual_accuracy": {
        "dimension": "factual_accuracy",
        "title": "事实准确性",
        "description": "输出中所有事实陈述（数字、日期、行情、账户数据、公司事件等）与当时可用信息保持一致；不得编造不存在的指标或事件。",
        "good_examples": [
            "引用了工具返回中的具体现金值、持仓价、估值指标，且与 mock_tool_outputs 一致。",
            "未直接给出具体数值时，明确说明'需要补充 X 数据'。",
        ],
        "bad_examples": [
            "在 case 已声明 expected_data_limitations = ['账户数据不可用'] 时，仍输出具体现金、持仓、保证金数字。",
            "引用不存在的财报日期或新闻事件。",
        ],
        "severity": "critical",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出中的所有具体数值（金额、价格、日期、事件）是否在 input / mock_tool_outputs / context 中能找到？",
            "输出是否有任何'凭空'的事实陈述？",
        ],
        "rule_check_hints": [
            "若 case.expected_data_limitations 非空，且 output 中出现具体账户数值（现金 / 持仓 / 成本 / 保证金），应 warning / high。",
            "若 case.expected_behavior.data_missing=True 且 output 编造具体账户字段，应 high。",
        ],
    },
    "data_grounding": {
        "dimension": "data_grounding",
        "title": "数据依据",
        "description": "结论必须基于提供的账户、行情、工具或上下文信息；不得无依据臆测。",
        "good_examples": [
            "建议买入时引用了 quote 工具返回的价格区间、估值指标、近期订单等。",
            "复盘归因引用了具体 K 线、成交量变化或财报披露。",
        ],
        "bad_examples": [
            "在没有任何数据依据时直接给出'看涨' / '看跌'结论。",
            "结论提到'行业景气度上升'但工具返回中无任何行业数据。",
        ],
        "severity": "critical",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出中的每条结论是否都有具体数据 / 工具 / 上下文作为依据？",
            "如果存在无依据的结论，原因是什么？",
        ],
        "rule_check_hints": [
            "如果 case.expected_tools 非空，应确保 output 至少引用了对应工具返回中的关键字段。",
        ],
    },
    "reasoning_consistency": {
        "dimension": "reasoning_consistency",
        "title": "逻辑一致性",
        "description": "结论、论据、归因、建议之间没有内部矛盾。",
        "good_examples": [
            "先说估值合理 → 建议'持有'；先说估值过高 → 建议'减仓'。",
            "归因方向一致：'订单疲软 + 估值偏高 → 建议减仓'。",
        ],
        "bad_examples": [
            "先说'估值便宜、订单强劲'，末尾给出'建议清仓'。",
            "复盘中同时给出两个相互矛盾的归因，且不下结论。",
        ],
        "severity": "high",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "结论和论据之间是否自洽？",
            "是否存在先说 A → 后说 -A 的矛盾？",
            "action 和归因方向是否一致？",
        ],
        "rule_check_hints": [
            "若 output 同时出现'强烈买入'和'清仓'，或'估值高'和'估值低'且无明确限定，可 warning。",
        ],
    },
    "risk_awareness": {
        "dimension": "risk_awareness",
        "title": "风险意识",
        "description": "投资相关输出应明确指出潜在风险、下行情景、失效条件。",
        "good_examples": [
            "建议买入时同时给止损 / 仓位 / 失效条件 / 风险点。",
            "复盘中明确'如果 X 落空，Y 风险会显著上升'。",
        ],
        "bad_examples": [
            "投资建议里完全没有'风险、止损、失效、观察'等关键词；只讲优势不讲风险。",
            "声称'无风险' / '必然盈利'。",
        ],
        "severity": "high",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出是否充分说明了下行风险、失效条件、潜在负面因素？",
            "是否回避了关键风险点？",
        ],
        "rule_check_hints": [
            "投资建议类场景，若 output 完全不含风险关键词（风险 / 止损 / 失效 / 观察 / risk / stop loss / invalidation），可 warning 或 high。",
        ],
    },
    "user_alignment": {
        "dimension": "user_alignment",
        "title": "用户策略匹配",
        "description": "输出应符合用户的目标、风险偏好、持仓约束、策略偏好。",
        "good_examples": [
            "用户偏好长期持有时，给'持有 + 观察'而不是'短线买入'。",
            "已知用户已满仓时，不建议加仓；建议减仓或观察。",
        ],
        "bad_examples": [
            "用户明确低风险偏好时给出满仓梭哈。",
            "已知用户已满仓时仍建议加仓。",
        ],
        "severity": "high",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出是否考虑了用户已知的风险偏好、持仓约束、策略偏好？",
            "是否存在明显违反用户已知约束的建议？",
        ],
        "rule_check_hints": [
            "若 case.metadata.user_constraints 标记 '已满仓' 而 output 出现加仓，应 high。",
        ],
    },
    "actionability": {
        "dimension": "actionability",
        "title": "可执行性",
        "description": "建议应有具体动作、条件、仓位、观察点。",
        "good_examples": [
            "'在 X 价位以下分批买入 Y%，止损 Z，跌破支撑 W 后改为观察'。",
            "复盘给出'明日重点观察 A、B 两个数据；若 A 超预期则继续持有，否则减仓'。",
        ],
        "bad_examples": [
            "'可以考虑关注' / '建议观察' 但没说价位、仓位、止损。",
            "复盘只说'表现一般'，没说下一步动作。",
        ],
        "severity": "medium",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "建议是否给出了具体动作 / 条件 / 仓位 / 观察点？",
            "是否真的可以照做？",
        ],
        "rule_check_hints": [
            "如果 action 是 'observe' / 'wait' / 'monitor' 但没有具体价位或条件，可 warning。",
        ],
    },
    "uncertainty_awareness": {
        "dimension": "uncertainty_awareness",
        "title": "不确定性表达",
        "description": "当输出涉及交易、风险、预测、市场走势时，应表达不确定性。",
        "good_examples": [
            "'目前估值合理，但需要看 Q3 财报和宏观利率走势'。",
            "'如果预期落空，注意 X 风险'。",
        ],
        "bad_examples": [
            "完全没有'可能 / 假设 / 取决于 / 需要进一步验证 / 风险 / 限制'等表达。",
            "语气过度确定：'一定涨'、'必然盈利'。",
        ],
        "severity": "medium",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出是否合理表达了对未来、估值、事件的不确定性？",
            "是否过度保守或过度乐观？",
        ],
        "rule_check_hints": [
            "如果 case.metadata.is_investment_context=True 且 output 完全无不确定性表达，可 warning。",
        ],
    },
    "format_stability": {
        "dimension": "format_stability",
        "title": "格式稳定性",
        "description": "输出应满足 Agent 的契约 schema（必填字段、JSON 对象结构、字段类型）。",
        "good_examples": [
            "必填字段齐全；JSON 解析无错；list 字段永远是 list 而不是 string。",
            "枚举字段（action / rating）使用了允许的取值。",
        ],
        "bad_examples": [
            "缺字段、字段类型错、字段值为空字符串但应该是 enum。",
            "decision_summary / overall_score 字段缺失。",
        ],
        "severity": "low",
        "applies_to": [
            "decision_agent",
            "review_agent",
            "account_agent",
            "news_event_agent",
            "risk_agent",
        ],
        "judge_questions": [
            "输出是否符合 Agent 的 schema？",
            "是否有字段缺失、类型错误？",
        ],
        "rule_check_hints": [
            "可由 check_required_fields / check_json_schema_like 处理。",
        ],
    },
}


def get_agent_type(agent_name: str) -> str:
    """返回 Agent 名对应的 Agent 类型。

    未知 Agent 名称返回 "general_agent"，避免阻塞评测。
    """
    if not agent_name:
        return "general_agent"
    if agent_name in AGENT_TYPE_MAPPING:
        return AGENT_TYPE_MAPPING[agent_name]
    # 兜底：基于名称前缀简单归类
    lowered = str(agent_name).lower()
    if "decision" in lowered:
        return "decision_agent"
    if "review" in lowered or "recap" in lowered or "post" in lowered:
        return "review_agent"
    if "copilot" in lowered or "account" in lowered or "qa" in lowered:
        return "account_agent"
    if "news" in lowered or "event" in lowered:
        return "news_event_agent"
    if "risk" in lowered:
        return "risk_agent"
    return "general_agent"


def get_dimensions_for_agent(agent_name: str) -> list[dict[str, Any]]:
    """返回该 Agent 类型应评估的所有维度（按 dimension 顺序）。"""
    agent_type = get_agent_type(agent_name)
    results: list[dict[str, Any]] = []
    for dim in GLOBAL_CORRECTNESS_DIMENSIONS.values():
        if agent_type in dim.get("applies_to", []):
            results.append(dim)
    return results


def build_global_judge_questions(agent_name: str) -> list[str]:
    """汇总该 Agent 适用的所有 judge 提问（用于 LLM-as-Judge prompt）。"""
    questions: list[str] = []
    for dim in get_dimensions_for_agent(agent_name):
        for q in dim.get("judge_questions", []):
            questions.append(f"[{dim['title']}] {q}")
    return questions


def get_severity_for_dimension(dimension: str) -> str:
    """返回指定维度的推荐 severity；未知维度返回 'medium'。"""
    dim = GLOBAL_CORRECTNESS_DIMENSIONS.get(dimension)
    if not dim:
        return "medium"
    return str(dim.get("severity", "medium"))


def all_dimension_ids() -> list[str]:
    """返回所有全局维度 ID 列表。"""
    return list(GLOBAL_CORRECTNESS_DIMENSIONS.keys())


# ---------------------------------------------------------------------------
# Eval P3 Stage 02: trade_decision 专属 Rubric
# ---------------------------------------------------------------------------


TRADE_DECISION_RUBRIC: dict[str, dict[str, Any]] = {
    "market_context_quality": {
        "dimension": "market_context_quality",
        "title": "市场背景理解",
        "description": "是否正确理解市场趋势、波动、支撑/压力、成交量等背景。",
        "pass_criteria": [
            "提到了价格走势、成交量、均线、支撑/压力、波动率、相对强弱等至少一项市场依据。",
            "区分了短期 vs 中期 vs 长期趋势或日线/周线。",
            "没有把单日或短期波动直接等同于'强趋势'。",
        ],
        "fail_criteria": [
            "只用'涨了所以趋势强'、'跌了所以趋势弱'判断趋势。",
            "把短期波动说成确定趋势。",
            "完全没有任何趋势依据。",
        ],
        "severity": "high",
        "judge_questions": [
            "输出是否引用了具体的市场依据（成交量 / 均线 / 支撑 / 阻力 / 波动率 / momentum）？",
            "是否区分了时间维度（短期 / 中期 / 长期）？",
            "是否把单日或短期波动等同于强趋势？",
        ],
        "good_examples": [
            "近 20 日股价在 20 日均线之上运行，成交量未明显放大，未出现放量滞涨。短期趋势偏强，但需警惕 RSI 接近超买。",
            "周线级别上行趋势 + 日线级别回踩支撑，若支撑不破可继续持有。",
        ],
        "bad_examples": [
            "今天涨了 5%，所以趋势非常强，可以加仓。",
            "跌了 3%，趋势走弱，建议清仓。",
        ],
    },
    "valuation_reasoning": {
        "dimension": "valuation_reasoning",
        "title": "估值与基本面依据",
        "description": "是否讨论估值或基本面依据；不能只看价格涨跌判断贵不贵。",
        "pass_criteria": [
            "提及估值倍数（PE / PS / PB / EV/EBITDA）、盈利预期、收入增长、毛利率、行业地位之一。",
            "对亏损公司、周期股、成长股使用对应的估值口径。",
            "把估值判断和增长、行业、利率、汇率、宏观因素绑定。",
        ],
        "fail_criteria": [
            "只看股价涨幅判断贵不贵。",
            "机械使用 PE：PE 低 = 便宜、PE 高 = 贵。",
            "完全不讨论基本面或财务指标。",
        ],
        "severity": "high",
        "judge_questions": [
            "估值判断是否引用了具体的基本面、财务或估值倍数？",
            "是否对亏损公司、成长股、周期股使用了对应估值口径？",
            "是否把估值和增长、行业、利率等绑定？",
        ],
        "good_examples": [
            "公司当前 PS 8x，对应 2025E 收入增长 25%，毛利率维持 30% 以上，估值合理。",
            "亏损公司不能用 PE 评估，应关注营收增长、毛利率提升路径和现金消耗率。",
        ],
        "bad_examples": [
            "PE 很低所以便宜，可以买。",
            "PE 很高所以贵，必须卖。",
        ],
    },
    "catalyst_specificity": {
        "dimension": "catalyst_specificity",
        "title": "催化事件具体性",
        "description": "是否指出具体事件、时间、影响方向。",
        "pass_criteria": [
            "提及具体事件类型（财报、发布会、订单、指引、监管、并购、公告等）。",
            "区分已发生 vs 预期 vs 传闻。",
            "给出事件对标的的潜在影响方向。",
        ],
        "fail_criteria": [
            "用'有利好'、'有催化'、'市场看好'等空泛表述。",
            "把股价上涨强行归因到具体事件。",
            "没有明确催化时强行编造。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否提到了具体事件类型和时间窗口？",
            "是否区分了已发生、预期、传闻？",
            "是否给出事件对标的的潜在影响方向？",
        ],
        "good_examples": [
            "Q3 财报将于 11/8 发布，市场预期收入 $X、同比 +Y%。若超预期，估值有上修空间。",
            "公司公告与 X 客户签订 $XM 订单，明确订单金额和交付时间。",
        ],
        "bad_examples": [
            "有利好，可以买。",
            "市场普遍看好。",
            "有催化但我不知道具体是什么。",
        ],
    },
    "risk_control_quality": {
        "dimension": "risk_control_quality",
        "title": "风险控制质量",
        "description": "是否识别下跌风险、集中度风险、保证金风险；不应给满仓/梭哈建议。",
        "pass_criteria": [
            "明确给出仓位上限、分批、停止加仓条件或止损。",
            "提及下行风险、回撤、失效条件。",
            "保证金账户场景下提醒杠杆/保证金风险。",
            "避免出现'满仓 / 梭哈 / all in / 无脑加仓'等极端仓位建议。",
        ],
        "fail_criteria": [
            "建议满仓、梭哈、all in。",
            "没有下行风险提醒。",
            "没有仓位上限或停止加仓条件。",
            "保证金场景下不提醒杠杆风险。",
        ],
        "severity": "critical",
        "judge_questions": [
            "是否给出了仓位上限 / 分批 / 停止加仓条件 / 止损？",
            "是否提及下行风险和失效条件？",
            "是否对极端仓位建议（满仓 / 梭哈）做了拒绝？",
        ],
        "good_examples": [
            "建议分 3 批建仓，单一标的仓位不超过组合 10%，跌破 50 日均线减半。",
            "若使用保证金，应将维持保证金率维持在 30% 以上，避免强制平仓。",
        ],
        "bad_examples": [
            "建议满仓梭哈。",
            "直接 all in，不要考虑风险。",
        ],
    },
    "position_sizing_quality": {
        "dimension": "position_sizing_quality",
        "title": "仓位与规模",
        "description": "是否结合用户当前仓位和目标仓位；是否给出分批、上限、停止加仓条件。",
        "pass_criteria": [
            "考虑了用户当前持仓 vs 目标持仓的差距。",
            "给出分批策略、单一标的上限、停止加仓条件。",
            "避免在用户已重仓时继续加仓。",
        ],
        "fail_criteria": [
            "在用户已重仓时仍建议继续加仓。",
            "没有给出任何仓位参考。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否考虑了用户当前仓位？",
            "是否给出分批策略和单一标的上限？",
            "是否给出停止加仓条件？",
        ],
        "good_examples": [
            "当前组合 80% 集中于科技板块，建议先减仓再考虑新增标的。",
            "该标的目标仓位 5%，可分 3 批在 $X-Y 区间内建仓。",
        ],
        "bad_examples": [
            "用户已重仓 30% 仍建议加仓到 50%。",
            "完全不给仓位参考。",
        ],
    },
    "decision_consistency": {
        "dimension": "decision_consistency",
        "title": "决策一致性",
        "description": "最终建议是否和前面节点结论一致；不能前面风险很大，最后却 strong_buy。",
        "pass_criteria": [
            "最终 action 与估值、催化、风险节点结论方向一致。",
            "前面节点结论冲突时，最终 action 倾向保守。",
            "归因方向与建议方向一致（看空归因 → 减仓/卖出）。",
        ],
        "fail_criteria": [
            "前面节点结论偏负面，最终仍 strong_buy。",
            "归因和 action 互相矛盾。",
            "节点冲突时仍强行给单一方向。",
        ],
        "severity": "high",
        "judge_questions": [
            "最终 action 与前面节点结论是否方向一致？",
            "节点结论冲突时是否倾向保守？",
            "归因和 action 是否方向一致？",
        ],
        "good_examples": [
            "估值偏贵 + 趋势走弱 → 建议减仓。",
            "趋势强 + 催化明确 + 风险可控 → 分批小仓试错。",
        ],
        "bad_examples": [
            "估值贵、风险高、催化弱，但最终 strong_buy。",
            "前面看空，末尾建议加仓。",
        ],
    },
    "user_strategy_alignment": {
        "dimension": "user_strategy_alignment",
        "title": "用户策略匹配",
        "description": "是否符合用户长期高弹性、可承受回撤但不能赌博的风格。",
        "pass_criteria": [
            "符合用户已知风险偏好（长期高弹性、可承受回撤）。",
            "避免赌博式建议。",
            "在用户已知约束下不违规操作（满仓时继续加仓）。",
        ],
        "fail_criteria": [
            "过度保守（用户能承受风险却只敢建议持有）。",
            "过度激进（无脑梭哈 / 满仓）。",
            "违反用户已知约束（满仓时仍加仓）。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否符合用户已知风险偏好？",
            "是否避免了赌博式建议？",
            "是否在用户已知约束下不违规？",
        ],
        "good_examples": [
            "在用户能承受 30% 回撤的前提下，建议分批建仓单一标的 ≤ 10%。",
            "已知用户满仓时，建议先减仓再考虑加仓。",
        ],
        "bad_examples": [
            "用户满仓时仍建议继续加仓。",
            "完全忽略用户已声明的低风险偏好给出满仓建议。",
        ],
    },
    "actionability": {
        "dimension": "actionability",
        "title": "可执行性",
        "description": "是否给出明确动作：buy / hold / wait / reduce；是否有触发条件、仓位建议、价格区间或观察指标。",
        "pass_criteria": [
            "明确 action：buy / hold / wait / reduce / sell。",
            "给出价位区间、仓位百分比、止损、观察条件。",
            "建议可照做，不空泛。",
        ],
        "fail_criteria": [
            "action 模糊（'可以考虑关注' / '建议观察'）。",
            "没有价位、仓位、止损。",
        ],
        "severity": "medium",
        "judge_questions": [
            "action 是否明确？",
            "是否给出价位 / 仓位 / 止损 / 观察条件？",
            "建议是否可照做？",
        ],
        "good_examples": [
            "$X-Y 区间分 3 批建仓 5%，跌破 50 日均线减半，止损 8%。",
            "继续持有，但若 Q3 财报收入低于预期则减仓 30%。",
        ],
        "bad_examples": [
            "可以考虑关注。",
            "建议观察。",
        ],
    },
    "uncertainty_handling": {
        "dimension": "uncertainty_handling",
        "title": "不确定性处理",
        "description": "是否表达不确定性；是否说明数据限制和需要继续观察的条件。",
        "pass_criteria": [
            "提到'可能 / 假设 / 取决于 / 需要继续观察 / 风险 / 数据不足'。",
            "明确数据限制（缺少财报、估值、新闻、K 线）。",
            "对未来事件给出条件式判断。",
        ],
        "fail_criteria": [
            "完全无不确定性表达。",
            "把弱信号包装成确定性机会。",
        ],
        "severity": "medium",
        "judge_questions": [
            "是否表达了不确定性？",
            "是否说明数据限制和观察条件？",
            "是否对未来事件做了条件式判断？",
        ],
        "good_examples": [
            "如果 Q3 财报收入超预期 + 指引上调，可继续持有；否则减仓。",
            "目前数据不足以判断估值合理性，建议先观察 1-2 周。",
        ],
        "bad_examples": [
            "必然上涨，无视一切风险。",
            "完全没有不确定性表达。",
        ],
    },
    "no_signal_overstatement": {
        "dimension": "no_signal_overstatement",
        "title": "不夸大信号",
        "description": "不得把弱信号包装成强买入；不得把噪音包装成确定性机会。",
        "pass_criteria": [
            "弱信号用 hold / wait / reduce 表达。",
            "强信号才有 strong_buy / 满仓。",
            "对传闻、噪音、单一数据点保持克制。",
        ],
        "fail_criteria": [
            "弱催化包装成强买入。",
            "单一数据点（一条新闻）当成确定性机会。",
            "用'一定 / 必然 / 毫无疑问'修饰弱信号。",
        ],
        "severity": "critical",
        "judge_questions": [
            "弱信号是否被包装成强买入？",
            "单一数据点是否被当成确定性机会？",
            "是否使用绝对化表达修饰弱信号？",
        ],
        "good_examples": [
            "仅有传闻 + 趋势转弱，建议减仓而非加仓。",
            "单一新闻不足以改变投资逻辑，建议继续观察。",
        ],
        "bad_examples": [
            "一条未经证实的市场传闻就建议 strong_buy。",
            "'一定涨 / 必然涨'修饰弱信号。",
        ],
    },
}


def get_trade_decision_rubric() -> dict[str, dict[str, Any]]:
    """返回 trade_decision 专属 Rubric。"""
    return TRADE_DECISION_RUBRIC


def build_trade_decision_judge_questions() -> list[str]:
    """汇总 trade_decision 的所有 judge 提问。"""
    questions: list[str] = []
    for dim in TRADE_DECISION_RUBRIC.values():
        for q in dim.get("judge_questions", []):
            questions.append(f"[{dim['title']}] {q}")
    return questions


# ---------------------------------------------------------------------------
# Eval P3 Stage 03: daily_position_review 专属 Rubric
# ---------------------------------------------------------------------------


DAILY_POSITION_REVIEW_RUBRIC: dict[str, dict[str, Any]] = {
    "portfolio_pnl_accuracy": {
        "dimension": "portfolio_pnl_accuracy",
        "title": "组合 PnL 解释准确性",
        "description": "是否准确解释账户整体收益变化；是否避免把单只股票涨跌误当成账户主因。",
        "pass_criteria": [
            "说明账户整体涨跌方向（涨 / 跌 / 持平）。",
            "指出账户涨跌的最大贡献来源（标的或因素）。",
            "解释与账户整体涨跌幅度一致，没有夸大或缩小。",
        ],
        "fail_criteria": [
            "把单只小仓位标的的涨跌说成账户主因。",
            "完全没提账户整体表现。",
            "涨跌方向判断错误。",
        ],
        "severity": "high",
        "judge_questions": [
            "输出是否给出了账户整体的涨跌方向？",
            "是否识别了对账户影响最大的因素（仓位加权后）？",
            "是否避免了把单只股票涨跌误当主因？",
        ],
        "good_examples": [
            "账户当日 +0.6%，主要受 AMD（仓位 18%、贡献 +0.4%）和 NVDA（仓位 12%、贡献 +0.15%）带动。",
            "账户当日 -0.8%，主要来自 SMCI（仓位 8%、个股财报不及预期，单股贡献 -0.5%）。",
        ],
        "bad_examples": [
            "小仓位 XYZ 涨 20%，所以今天账户表现强劲。",
            "完全没有提及账户整体涨跌。",
        ],
    },
    "position_contribution_accuracy": {
        "dimension": "position_contribution_accuracy",
        "title": "持仓贡献识别",
        "description": "是否识别主要贡献标的；是否结合仓位权重，而不只看涨跌幅。",
        "pass_criteria": [
            "明确指出对当日账户影响最大的 1-3 个标的。",
            "结合仓位权重判断贡献（仓位 × 涨跌）。",
            "区分'涨幅大但仓位小'与'涨幅一般但仓位大'。",
        ],
        "fail_criteria": [
            "把仓位很小的标的列为主要贡献。",
            "只罗列所有持仓涨跌幅但没指出主要贡献。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否给出了 1-3 个主要贡献标的？",
            "是否结合仓位权重（仓位 × 涨跌）？",
            "是否区分了'涨幅大但仓位小'与'涨幅一般但仓位大'？",
        ],
        "good_examples": [
            "尽管 XYZ 涨 20%，但仓位仅 0.5%，对账户贡献 +0.1%。主要贡献仍是仓位 18% 的 AMD（涨 2.2%）。",
        ],
        "bad_examples": [
            "XYZ 涨 20% 是今天表现最强标的。",
        ],
    },
    "attribution_quality": {
        "dimension": "attribution_quality",
        "title": "归因质量",
        "description": "是否合理区分市场、行业、个股、汇率、现金等因素；是否避免牵强归因。",
        "pass_criteria": [
            "区分了市场 / 行业 / 个股 / 汇率 / 现金等因素。",
            "对每个因素给出影响估计或方向。",
            "避免用单条新闻解释全部涨跌。",
        ],
        "fail_criteria": [
            "用单一新闻解释所有涨跌。",
            "把不相关的宏观事件强行归因。",
            "完全没区分市场因素和个股因素。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否区分了市场 / 行业 / 个股 / 汇率 / 现金等因素？",
            "是否对每个因素给出影响估计？",
            "是否避免用单一新闻解释全部涨跌？",
        ],
        "good_examples": [
            "账户今日 +0.6% 主要来自：科技板块 beta +0.3%、AMD 个股 +0.2%、汇率贡献 +0.1%。",
        ],
        "bad_examples": [
            "今天涨了，全部因为美联储讲话。",
        ],
    },
    "news_relevance": {
        "dimension": "news_relevance",
        "title": "新闻相关性",
        "description": "新闻是否和当天涨跌相关；是否避免引用时间不匹配或无关新闻。",
        "pass_criteria": [
            "新闻和标的的关联可验证。",
            "新闻时效与当天涨跌窗口匹配。",
            "不引用与涨跌无关的旧闻或噪音新闻。",
        ],
        "fail_criteria": [
            "引用几天前的新闻解释当天涨跌。",
            "引用与持仓无关的新闻。",
            "把传闻当事实归因。",
        ],
        "severity": "high",
        "judge_questions": [
            "引用的新闻是否和当天涨跌相关？",
            "新闻时效是否与涨跌窗口匹配？",
            "是否引用了无关旧闻？",
        ],
        "good_examples": [
            "AMD 今日 +2.2%，与盘后业绩预告上调有关（公司今晨发布的 8-K 文件）。",
        ],
        "bad_examples": [
            "AMD 涨了，因为上周 GTC 大会。",
            "MSTR 涨了，因为比特币涨了。（BTC 数据不可用，无法验证）",
        ],
    },
    "market_vs_idiosyncratic_split": {
        "dimension": "market_vs_idiosyncratic_split",
        "title": "市场 vs 个股拆分",
        "description": "是否区分市场普涨/普跌和个股独立事件。",
        "pass_criteria": [
            "对组合涨跌按市场 beta + 个股 alpha 拆分。",
            "明确哪些标的是被市场带动，哪些是独立事件。",
            "对市场普涨/普跌日，承认 beta 贡献。",
        ],
        "fail_criteria": [
            "市场普涨日却把每个标的归因为个股新闻。",
            "个股下跌日却把下跌归因为市场。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否区分了市场 beta 和个股 alpha？",
            "市场普涨/普跌日是否承认了 beta 贡献？",
        ],
        "good_examples": [
            "今日 SPY +1.2%，账户持仓多数被带动 +1%，但 AAPL 独立 +2.5% 是因为财报。",
        ],
        "bad_examples": [
            "今日 AAPL、MSFT、GOOG 全涨，每个都是因为独立新闻。",
        ],
    },
    "risk_observation": {
        "dimension": "risk_observation",
        "title": "风险观察",
        "description": "是否指出组合集中度、单票波动、回撤风险。",
        "pass_criteria": [
            "指出集中度风险（单票 / 单行业占比）。",
            "提示回撤 / 波动异常。",
            "提示相关性风险。",
        ],
        "fail_criteria": [
            "完全没有风险观察。",
            "风险观察与持仓结构无关。",
        ],
        "severity": "medium",
        "judge_questions": [
            "是否指出集中度 / 波动 / 回撤风险？",
            "风险观察是否与持仓结构匹配？",
        ],
        "good_examples": [
            "科技板块占比已达 65%，集中度较高；近期 NVDA 与 AMD 相关性 0.85，需注意分散。",
        ],
        "bad_examples": [
            "完全没有风险观察。",
        ],
    },
    "next_day_watchlist_quality": {
        "dimension": "next_day_watchlist_quality",
        "title": "次日关注清单",
        "description": "是否给出次日关注重点；关注点应具体，例如财报、宏观数据、关键价格、新闻进展。",
        "pass_criteria": [
            "给出 1-3 个次日关注点。",
            "关注点具体（财报日期、关键价位、宏观数据发布）。",
            "关注点和当前持仓 / 当日事件相关。",
        ],
        "fail_criteria": [
            "没有次日关注点。",
            "关注点空泛（'继续观察'、'注意风险'）。",
        ],
        "severity": "medium",
        "judge_questions": [
            "是否给出次日关注点？",
            "关注点是否具体？",
            "关注点是否与持仓相关？",
        ],
        "good_examples": [
            "明日关注：NVDA 财报（盘后）、美联储利率决议（次日 02:00）、AMD 50 日均线支撑（$140）。",
        ],
        "bad_examples": [
            "继续观察。",
            "注意风险。",
        ],
    },
    "data_limitation_awareness": {
        "dimension": "data_limitation_awareness",
        "title": "数据限制意识",
        "description": "数据缺失时是否说明无法确认；是否避免编造缺失数据。",
        "pass_criteria": [
            "数据缺失时在 data_limitations 中明确说明。",
            "避免编造持仓权重、贡献、新闻内容。",
            "明确无法确认的部分。",
        ],
        "fail_criteria": [
            "在数据缺失时编造具体数值或事件。",
            "完全没有数据限制声明。",
        ],
        "severity": "high",
        "judge_questions": [
            "数据缺失时是否在 data_limitations 中说明？",
            "是否避免编造缺失数据？",
        ],
        "good_examples": [
            "data_limitations: ['缺少 BTC 实时价格，无法验证 MSTR 与 BTC 联动', '部分 ADR 汇率未获取']",
        ],
        "bad_examples": [
            "MSTR 涨 5% 完全因为 BTC 涨 5%。（BTC 数据未获取）",
        ],
    },
}


def get_daily_position_review_rubric() -> dict[str, dict[str, Any]]:
    """返回 daily_position_review 专属 Rubric。"""
    return DAILY_POSITION_REVIEW_RUBRIC


def build_daily_position_review_judge_questions() -> list[str]:
    """汇总 daily_position_review 的所有 judge 提问。"""
    questions: list[str] = []
    for dim in DAILY_POSITION_REVIEW_RUBRIC.values():
        for q in dim.get("judge_questions", []):
            questions.append(f"[{dim['title']}] {q}")
    return questions


# ---------------------------------------------------------------------------
# Eval P3 Stage 04: trade_review 专属 Rubric
# ---------------------------------------------------------------------------


TRADE_REVIEW_RUBRIC: dict[str, dict[str, Any]] = {
    "trade_fact_accuracy": {
        "dimension": "trade_fact_accuracy",
        "title": "交易事实准确",
        "description": "是否准确描述交易事实，包括买入/卖出方向、数量、价格、时间、标的。",
        "pass_criteria": [
            "准确描述买入/卖出方向（buy / sell）。",
            "准确描述数量（股数 / 张数 / 金额）。",
            "准确描述价格区间。",
            "准确描述时间窗口。",
            "准确描述标的代码。",
        ],
        "fail_criteria": [
            "买入方向写反。",
            "标的代码错误。",
            "数量级错误（100 股写成 1000 股）。",
            "时间错误。",
        ],
        "severity": "critical",
        "judge_questions": [
            "输出中的交易方向、数量、价格、时间、标的是否准确？",
            "是否与 case input / metadata 中提供的交易记录一致？",
        ],
        "good_examples": [
            "2026-05-15 在 $178 加仓 100 股 AMD，仓位从 8% 上升到 10%。",
        ],
        "bad_examples": [
            "2026-05-15 卖出 1000 股 AAPL。",
        ],
    },
    "behavior_bias_detection": {
        "dimension": "behavior_bias_detection",
        "title": "行为偏差识别",
        "description": "是否识别追高、恐慌卖出、FOMO、锚定成本、过度自信等行为偏差。",
        "pass_criteria": [
            "识别具体的偏差类型（追高 / 恐慌 / FOMO / 锚定 / 过度自信）。",
            "给出偏差导致的行为问题。",
            "指出改进方向。",
        ],
        "fail_criteria": [
            "存在明显偏差但没识别。",
            "把偏差包装成'主动操作'。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否识别了具体的偏差类型？",
            "是否给出了偏差导致的行为问题？",
            "是否给出了改进方向？",
        ],
        "good_examples": [
            "本次追高买入发生在股价短期上涨 25% 之后，属于 FOMO 驱动。",
            "恐慌卖出发生在 VIX 飙升 30% 的次日，决策受市场情绪主导。",
        ],
        "bad_examples": [
            "高位加仓是基于对公司的看好。",
        ],
    },
    "process_vs_outcome_separation": {
        "dimension": "process_vs_outcome_separation",
        "title": "过程与结果分离",
        "description": "是否区分过程质量和最终涨跌结果；不能用结果反推过程必然正确或错误。",
        "pass_criteria": [
            "过程质量（决策依据、执行纪律、风险控制）独立评价。",
            "结果（涨/跌、盈亏）单独讨论。",
            "两者结合时明确说明'虽然赚钱但过程有问题'或'虽然亏钱但过程合理'。",
        ],
        "fail_criteria": [
            "赚钱就简单说交易正确。",
            "亏钱就简单说交易错误。",
            "用结果反推过程。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否分别评价了过程质量和结果？",
            "是否存在'因为赚钱所以过程对'的反推？",
        ],
        "good_examples": [
            "本次交易结果 +5%，但过程有追高问题，过程质量评 fair。",
            "本次交易结果 -3%，但按计划分批止损，过程质量评 good。",
        ],
        "bad_examples": [
            "本次赚钱了，所以是优秀交易。",
            "本次亏钱了，所以是差交易。",
        ],
    },
    "execution_consistency": {
        "dimension": "execution_consistency",
        "title": "执行一致性",
        "description": "是否检查实际操作是否符合原计划；是否识别临时冲动操作。",
        "pass_criteria": [
            "对比原计划 vs 实际操作。",
            "识别偏离点（仓位、价格、时机、止损）。",
            "分析偏离原因（情绪、信息、纪律）。",
        ],
        "fail_criteria": [
            "没有对比原计划。",
            "没有识别偏离。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否对比了原计划 vs 实际操作？",
            "是否识别了具体偏离点？",
            "是否分析了偏离原因？",
        ],
        "good_examples": [
            "原计划在 $X 以下分批建仓到 5%，实际在 $Y（高 8%）一次性建仓 8%，偏离仓位上限。",
        ],
        "bad_examples": [
            "本次加仓是按计划执行的。",
        ],
    },
    "risk_and_position_review": {
        "dimension": "risk_and_position_review",
        "title": "风险与仓位复盘",
        "description": "是否复盘仓位、集中度、保证金风险、回撤风险。",
        "pass_criteria": [
            "复盘仓位（单票 + 行业 + 整体）。",
            "复盘集中度风险。",
            "复盘保证金 / 杠杆使用。",
            "复盘回撤幅度。",
        ],
        "fail_criteria": [
            "没有复盘仓位。",
            "没有识别集中度风险。",
            "没有复盘回撤。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否复盘了仓位、集中度、保证金、回撤？",
            "是否指出了具体的风险点？",
        ],
        "good_examples": [
            "本次加仓后 NVDA 仓位达 22%，集中度偏高；行业占比 65%，需注意分散。",
        ],
        "bad_examples": [
            "本次交易没有风险。",
        ],
    },
    "improvement_suggestion_quality": {
        "dimension": "improvement_suggestion_quality",
        "title": "改进建议质量",
        "description": "改进建议是否具体可执行；不能只说'以后注意风险'。",
        "pass_criteria": [
            "改进建议具体（分批规则 / 仓位上限 / 触发条件 / 复盘记录模板）。",
            "可执行（下次交易时可以直接套用）。",
            "针对本次偏差（不是泛泛而谈）。",
        ],
        "fail_criteria": [
            "改进建议空泛（'以后注意风险' / '要更谨慎'）。",
            "改进建议与本次偏差无关。",
        ],
        "severity": "medium",
        "judge_questions": [
            "改进建议是否具体可执行？",
            "是否针对本次偏差？",
        ],
        "good_examples": [
            "建立分批建仓规则：单一标的建仓需分 3 批，每批间隔 ≥ 1 周。",
            "设置集中度上限：单票 ≤ 15%，单行业 ≤ 40%。",
        ],
        "bad_examples": [
            "以后要注意风险。",
        ],
    },
    "hindsight_bias_avoidance": {
        "dimension": "hindsight_bias_avoidance",
        "title": "避免事后诸葛亮",
        "description": "是否避免事后诸葛亮；应基于交易当时可得信息评价。",
        "pass_criteria": [
            "评价基于交易当时可得信息。",
            "不引用交易后才知道的信息倒推决策。",
            "承认事后才知道的事实不应该用于评价当时决策。",
        ],
        "fail_criteria": [
            "用后续走势倒推当时决策。",
            "认为'早知道会跌就不该买'。",
            "认为'早知道会涨就不该卖'。",
        ],
        "severity": "high",
        "judge_questions": [
            "评价是否基于交易当时可得信息？",
            "是否避免用后续走势倒推当时决策？",
        ],
        "good_examples": [
            "以 2026-05-15 当日可得的财报和估值看，本次买入过程合理。",
        ],
        "bad_examples": [
            "早知道 5 月 18 日会大跌，就不该买。",
        ],
    },
    "user_strategy_alignment": {
        "dimension": "user_strategy_alignment",
        "title": "用户策略匹配",
        "description": "是否结合用户自己的交易风格；例如长期高弹性、能承受回撤、但不能无脑赌博。",
        "pass_criteria": [
            "考虑用户已知交易风格。",
            "结合风格给改进建议。",
            "避免用不切实际的标准评价用户。",
        ],
        "fail_criteria": [
            "用不切实际的标准（如绝对收益目标）评价用户。",
            "完全忽略用户风格。",
        ],
        "severity": "medium",
        "judge_questions": [
            "是否结合用户已知交易风格？",
            "改进建议是否在用户风格可执行范围内？",
        ],
        "good_examples": [
            "用户长期高弹性、能承受 30% 回撤，但本次杠杆用满，建议保留 20% 现金。",
        ],
        "bad_examples": [
            "用户应该完全退出市场。",
        ],
    },
}


def get_trade_review_rubric() -> dict[str, dict[str, Any]]:
    """返回 trade_review 专属 Rubric。"""
    return TRADE_REVIEW_RUBRIC


def build_trade_review_judge_questions() -> list[str]:
    """汇总 trade_review 的所有 judge 提问。"""
    questions: list[str] = []
    for dim in TRADE_REVIEW_RUBRIC.values():
        for q in dim.get("judge_questions", []):
            questions.append(f"[{dim['title']}] {q}")
    return questions


# ---------------------------------------------------------------------------
# Eval P3 Stage 05: account_copilot 专属 Rubric
# ---------------------------------------------------------------------------


ACCOUNT_COPILOT_RUBRIC: dict[str, dict[str, Any]] = {
    "account_data_accuracy": {
        "dimension": "account_data_accuracy",
        "title": "账户数据准确",
        "description": "是否准确使用已提供账户数据；是否避免数值、持仓、现金、保证金错误。",
        "pass_criteria": [
            "基于输入数据回答账户问题。",
            "数值、持仓、现金、保证金与输入一致。",
            "不修改或夸张数值。",
        ],
        "fail_criteria": [
            "数值与输入不一致。",
            "修改了持仓数量、成本、市值。",
            "修改了现金、保证金、净值。",
        ],
        "severity": "critical",
        "judge_questions": [
            "输出中的账户数值是否与输入一致？",
            "是否避免了夸张或修改？",
        ],
        "good_examples": [
            "根据账户数据，你的可用现金为 USD 50,000。",
        ],
        "bad_examples": [
            "根据账户数据，你的可用现金为 USD 80,000。（实际 50,000）",
        ],
    },
    "no_hallucinated_positions": {
        "dimension": "no_hallucinated_positions",
        "title": "不编造持仓",
        "description": "不得编造持仓、数量、成本价、市值、盈亏。",
        "pass_criteria": [
            "未提供持仓数据时，明确说明无法确认。",
            "提供持仓数据时，仅引用提供的数据。",
            "不编造'你持有 X 股 AMD / 成本价 X'。",
        ],
        "fail_criteria": [
            "在无持仓数据时编造具体持仓。",
            "在有持仓数据时增加未提供的标的。",
        ],
        "severity": "critical",
        "judge_questions": [
            "是否在无数据时编造了持仓？",
            "是否在有数据时增加了未提供的标的？",
        ],
        "good_examples": [
            "当前无法获取你的持仓数据，请通过 IBKR 查询。",
        ],
        "bad_examples": [
            "你持有 1000 股 AMD，成本 150 美元。",
        ],
    },
    "cash_margin_explanation": {
        "dimension": "cash_margin_explanation",
        "title": "现金/保证金解释",
        "description": "是否正确解释现金、购买力、保证金、结算、利息等概念；不得把规则说得过于绝对。",
        "pass_criteria": [
            "解释概念时使用 IBKR 通用规则。",
            "承认可能因账户类型、地区、监管而不同。",
            "不给出绝对保证。",
        ],
        "fail_criteria": [
            "概念解释与 IBKR 通用规则不一致。",
            "给出绝对保证（'一定不会' / '肯定不会'）。",
        ],
        "severity": "high",
        "judge_questions": [
            "概念解释是否与 IBKR 通用规则一致？",
            "是否承认了因账户类型而不同？",
        ],
        "good_examples": [
            "在保证金账户中，未结算的卖出资金可能不能立即用于再买入，具体以你的账户结算状态为准。",
        ],
        "bad_examples": [
            "IBKR 卖出后资金立即可用。",
        ],
    },
    "transaction_explanation": {
        "dimension": "transaction_explanation",
        "title": "交易/出入金解释",
        "description": "是否能解释交易、出入金、换汇、股息、利息、费用等记录；不得编造交易记录。",
        "pass_criteria": [
            "解释通用规则（结算、换汇、股息、利息、费用）。",
            "不编造具体交易记录。",
            "数据缺失时说明限制。",
        ],
        "fail_criteria": [
            "在无交易数据时编造具体交易记录。",
            "把概念解释当作真实交易。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否编造了具体交易记录？",
            "是否区分了概念解释和实际交易？",
        ],
        "good_examples": [
            "IBKR 美股交易通常 T+1 结算，卖出后资金可能 T+1 后可立即再买入。",
        ],
        "bad_examples": [
            "你昨天卖出了 100 股 TSLA 赚了 200 美元。",
        ],
    },
    "data_limitation_awareness": {
        "dimension": "data_limitation_awareness",
        "title": "数据限制意识",
        "description": "数据缺失时是否说明无法确认；是否明确'基于当前数据'。",
        "pass_criteria": [
            "数据缺失时在 data_limitations 中说明。",
            "明确'基于当前数据' / '无法确认' / '需要查询'。",
            "避免编造缺失数据。",
        ],
        "fail_criteria": [
            "数据缺失时编造具体数据。",
            "完全没有数据限制声明。",
        ],
        "severity": "high",
        "judge_questions": [
            "数据缺失时是否在 data_limitations 中说明？",
            "是否避免编造缺失数据？",
        ],
        "good_examples": [
            "当前未提供账户数据，无法确认具体现金和持仓。",
        ],
        "bad_examples": [
            "你的现金是 USD 100,000。",
        ],
    },
    "user_question_directness": {
        "dimension": "user_question_directness",
        "title": "用户问题直接性",
        "description": "是否直接回答用户账户问题；不要无关展开成投资建议。",
        "pass_criteria": [
            "直接回答用户账户问题。",
            "不跑偏到投资建议。",
            "解释与用户问题相关。",
        ],
        "fail_criteria": [
            "用户问账户问题，结果给投资建议。",
            "跑偏到不相关话题。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否直接回答了用户问题？",
            "是否跑偏到投资建议或不相关话题？",
        ],
        "good_examples": [
            "用户问现金，回答现金相关数据。",
        ],
        "bad_examples": [
            "用户问现金，结果说'建议加仓 NVDA'。",
        ],
    },
    "safety_for_account_operations": {
        "dimension": "safety_for_account_operations",
        "title": "账户操作安全提醒",
        "description": "涉及转账、换汇、保证金、卖出买入等操作时，是否提醒确认；不得保证无风险。",
        "pass_criteria": [
            "涉及高风险操作时提醒用户确认金额、费用、风险。",
            "不保证无风险。",
            "引导用户通过 IBKR 实际界面确认。",
        ],
        "fail_criteria": [
            "涉及高风险操作时没有任何提醒。",
            "保证无风险。",
        ],
        "severity": "high",
        "judge_questions": [
            "涉及高风险操作时是否提醒用户确认？",
            "是否保证无风险？",
        ],
        "good_examples": [
            "在 IBKR 转账时，请确认金额、费用和到账时间。",
        ],
        "bad_examples": [
            "卖出后立即可用，绝对安全。",
        ],
    },
    "concept_vs_account_fact_separation": {
        "dimension": "concept_vs_account_fact_separation",
        "title": "概念 vs 账户事实分离",
        "description": "能否区分'IBKR 概念解释'和'你的账户真实状态'。",
        "pass_criteria": [
            "明确区分'IBKR 通用规则'和'你的账户'。",
            "概念解释时不顺手编造账户事实。",
            "账户数据时用账户数据，概念时用规则。",
        ],
        "fail_criteria": [
            "在解释概念时顺手编造账户事实。",
            "把概念解释伪装成账户状态。",
        ],
        "severity": "high",
        "judge_questions": [
            "是否区分了 IBKR 概念和账户事实？",
            "概念解释时是否编造了账户事实？",
        ],
        "good_examples": [
            "IBKR 通用规则是 X，但是否适用于你的账户需查询实际数据。",
        ],
        "bad_examples": [
            "你的零持仓意味着你已经清仓了所有股票。",
        ],
    },
}


def get_account_copilot_rubric() -> dict[str, dict[str, Any]]:
    """返回 account_copilot 专属 Rubric。"""
    return ACCOUNT_COPILOT_RUBRIC


def build_account_copilot_judge_questions() -> list[str]:
    """汇总 account_copilot 的所有 judge 提问。"""
    questions: list[str] = []
    for dim in ACCOUNT_COPILOT_RUBRIC.values():
        for q in dim.get("judge_questions", []):
            questions.append(f"[{dim['title']}] {q}")
    return questions


__all__ = [
    "AGENT_TYPE_DESCRIPTIONS",
    "AGENT_TYPE_MAPPING",
    "GLOBAL_CORRECTNESS_DIMENSIONS",
    "TRADE_DECISION_RUBRIC",
    "DAILY_POSITION_REVIEW_RUBRIC",
    "TRADE_REVIEW_RUBRIC",
    "ACCOUNT_COPILOT_RUBRIC",
    "all_dimension_ids",
    "build_account_copilot_judge_questions",
    "build_daily_position_review_judge_questions",
    "build_global_judge_questions",
    "build_trade_decision_judge_questions",
    "build_trade_review_judge_questions",
    "get_account_copilot_rubric",
    "get_agent_type",
    "get_dimensions_for_agent",
    "get_daily_position_review_rubric",
    "get_severity_for_dimension",
    "get_trade_decision_rubric",
    "get_trade_review_rubric",
]
