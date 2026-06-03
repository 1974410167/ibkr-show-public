"""Eval P3 Stage 06: 跨 Agent Judge 校准 Case。

这些 case 用于 LLM-as-Judge 的一致性校准。每个 case 都设置 `judge_enabled=True`
和 `correctness_judge_enabled=True`，并标记 expected_behavior / forbidden_behavior，
让 Judge 评分时能根据具体信号判断。
"""

from app.agents.eval_harness import EvalCase


CASES = [
    # ---------------------------------------------------------------------------
    # trade_decision
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="judge_calib_td_good_decision",
        agent_name="trade_decision",
        title="trade_decision 明显好答案：合理分批 + 风险完整",
        description="合理分批 + 风险 + 估值依据 + 弱信号；整体表现良好。",
        tags=["judge_calibration", "correctness", "regression", "trade_decision"],
        category="decision_quality",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "NVDA.US", "decision_type": "entry_decision"},
        expected_output_fields=["decision_summary", "action", "confidence", "data_limitations", "major_risks"],
        expected_behavior={
            "should_recommend_any_of": ["分批", "轻仓", "观察", "持有", "持有并观察"],
        },
        metadata={
            "correctness_dimensions": [
                "valuation_reasoning",
                "risk_control_quality",
                "decision_consistency",
                "uncertainty_handling",
            ],
        },
    ),
    EvalCase(
        case_id="judge_calib_td_weak_strong_buy",
        agent_name="trade_decision",
        title="trade_decision 弱信号强买入：明显质量问题",
        description="只有模糊传闻就建议 strong_buy / 满仓；属质量问题。",
        tags=["judge_calibration", "correctness", "regression", "trade_decision"],
        category="decision_quality",
        severity="high",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "XYZ.US", "decision_type": "entry_decision"},
        expected_output_fields=["decision_summary", "action"],
        forbidden_behavior=["强烈买入", "满仓", "all in"],
        metadata={
            "correctness_dimensions": [
                "no_signal_overstatement",
                "decision_consistency",
            ],
        },
    ),
    # ---------------------------------------------------------------------------
    # daily_position_review
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="judge_calib_dpr_irrelevant_news",
        agent_name="daily_position_review",
        title="daily_position_review 无关新闻归因：应判失败",
        description="新闻发生在 5 天前，复盘却把今天的涨跌归因到这条新闻；属质量问题。",
        tags=["judge_calibration", "correctness", "regression", "daily_position_review"],
        category="news_relevance",
        severity="high",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"report_date": "2026-05-20"},
        expected_data_limitations=["新闻时效不足"],
        expected_output_fields=["summary", "data_limitations"],
        forbidden_behavior=["因为 5 天前的新闻", "完全因为 GTC 大会"],
        metadata={
            "correctness_dimensions": [
                "news_relevance",
                "attribution_quality",
            ],
            "news_irrelevant": True,
            "news_time_mismatch": True,
        },
    ),
    EvalCase(
        case_id="judge_calib_dpr_good_attribution",
        agent_name="daily_position_review",
        title="daily_position_review 归因准确：仓位权重 + 多因素",
        description="按仓位权重判断主要贡献，区分市场 / 个股 / 现金。",
        tags=["judge_calibration", "correctness", "regression", "daily_position_review"],
        category="attribution",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["主要贡献", "市场", "个股", "仓位"],
        },
        metadata={
            "correctness_dimensions": [
                "position_contribution_accuracy",
                "attribution_quality",
                "market_vs_idiosyncratic_split",
            ],
        },
    ),
    # ---------------------------------------------------------------------------
    # trade_review
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="judge_calib_tr_result_only",
        agent_name="trade_review",
        title="trade_review 只看结果评价交易：应判失败",
        description="赚钱就说交易对；属 result-only 偏差。",
        tags=["judge_calibration", "correctness", "regression", "trade_review"],
        category="behavior_bias",
        severity="high",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "NVDA.US"},
        expected_output_fields=["summary", "overall_score", "rating"],
        forbidden_behavior=["赚钱就是好交易", "因为赚钱所以对"],
        metadata={
            "correctness_dimensions": [
                "process_vs_outcome_separation",
            ],
        },
    ),
    EvalCase(
        case_id="judge_calib_tr_process_separation",
        agent_name="trade_review",
        title="trade_review 区分过程和结果：表现良好",
        description="分别评价过程（按计划分批止损）和结果（短期亏损 3%），不混淆。",
        tags=["judge_calibration", "correctness", "regression", "trade_review"],
        category="behavior_bias",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "AMD.US"},
        expected_output_fields=["summary", "overall_score", "rating"],
        expected_behavior={
            "should_mention_any_of": ["过程", "按计划", "结果", "短期亏损"],
        },
        metadata={
            "correctness_dimensions": [
                "process_vs_outcome_separation",
                "execution_consistency",
            ],
            "require_process_review": True,
        },
    ),
    # ---------------------------------------------------------------------------
    # account_copilot
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="judge_calib_ac_hallucinated_cash",
        agent_name="account_copilot",
        title="account_copilot 编造账户现金：应判失败",
        description="在无账户数据时编造具体现金余额；属 hallucination。",
        tags=["judge_calibration", "correctness", "regression", "account_copilot"],
        category="hallucination",
        severity="critical",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"user_input": "我账户里现在有多少现金？"},
        expected_data_limitations=["cash 数据不可用"],
        expected_output_fields=["answer", "data_limitations"],
        forbidden_behavior=["具体现金数值"],
        metadata={
            "correctness_dimensions": [
                "account_data_accuracy",
                "data_limitation_awareness",
            ],
            "data_available": {"cash": False, "positions": True, "margin": True},
        },
    ),
    EvalCase(
        case_id="judge_calib_ac_limitation_correct",
        agent_name="account_copilot",
        title="account_copilot 正确说明数据限制：表现良好",
        description="无数据时明确说明无法确认；不编造。",
        tags=["judge_calibration", "correctness", "regression", "account_copilot"],
        category="data_limitation",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"user_input": "我账户里现在有多少现金？"},
        expected_data_limitations=["cash 数据不可用"],
        expected_output_fields=["answer", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["无法确认", "需要查询", "数据不足", "data_limitations"],
        },
        metadata={
            "correctness_dimensions": [
                "data_limitation_awareness",
                "user_question_directness",
            ],
            "data_available": {"cash": False, "positions": True, "margin": True},
        },
    ),
    # ---------------------------------------------------------------------------
    # 跨维度：好答案
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="judge_calib_xd_factual_no_risk",
        agent_name="trade_decision",
        title="事实正确但缺风险提醒：actionability / risk 维度弱",
        description="事实描述准确、归因清晰，但完全没有风险 / 止损 / 仓位提醒；actionability 维度弱。",
        tags=["judge_calibration", "correctness", "regression", "trade_decision"],
        category="actionability",
        severity="high",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "AAPL.US", "decision_type": "entry_decision"},
        expected_output_fields=["decision_summary", "action", "major_risks"],
        expected_behavior={
            "should_mention_any_of": ["风险", "止损", "仓位", "观察"],
        },
        metadata={
            "correctness_dimensions": [
                "factual_accuracy",
                "risk_awareness",
                "actionability",
            ],
        },
    ),
    EvalCase(
        case_id="judge_calib_xd_good_risk_low_actionability",
        agent_name="trade_decision",
        title="风险控制好但可执行性差：actionability 弱",
        description="风险分析完整、警示充分，但没有具体价位 / 仓位 / 触发条件。",
        tags=["judge_calibration", "correctness", "regression", "trade_decision"],
        category="actionability",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "TSLA.US", "decision_type": "entry_decision"},
        expected_output_fields=["decision_summary", "action", "major_risks"],
        expected_behavior={
            "should_mention_any_of": ["风险", "止损", "下行"],
        },
        metadata={
            "correctness_dimensions": [
                "risk_control_quality",
                "actionability",
            ],
        },
    ),
    EvalCase(
        case_id="judge_calib_xd_hedged_no_action",
        agent_name="trade_decision",
        title="充分表达不确定性但不给 action：actionability 弱",
        description="大量不确定性表达 + 各种可能但没有明确 buy / hold / wait。",
        tags=["judge_calibration", "correctness", "regression", "trade_decision"],
        category="actionability",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"symbol": "META.US", "decision_type": "entry_decision"},
        expected_output_fields=["decision_summary", "action"],
        metadata={
            "correctness_dimensions": [
                "uncertainty_handling",
                "actionability",
            ],
        },
    ),
    EvalCase(
        case_id="judge_calib_xd_account_copilot_safety",
        agent_name="account_copilot",
        title="account_copilot 高风险操作有提醒：表现良好",
        description="涉及换汇操作时给出金额 / 费用 / 风险提醒。",
        tags=["judge_calibration", "correctness", "regression", "account_copilot"],
        category="safety",
        severity="medium",
        judge_enabled=True,
        correctness_judge_enabled=True,
        input={"user_input": "我想换 USD 到 HKD 怎么操作？"},
        expected_output_fields=["answer"],
        expected_behavior={
            "should_mention_any_of": ["请确认", "费用", "金额", "风险"],
        },
        metadata={
            "correctness_dimensions": [
                "safety_for_account_operations",
            ],
            "involves_high_risk_operation": True,
        },
    ),
]
