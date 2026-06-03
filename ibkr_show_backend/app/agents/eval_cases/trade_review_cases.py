from app.agents.eval_harness import EvalCase


CASES = [
    EvalCase(
        case_id="trade_review_buy_only_open_position_not_zero",
        agent_name="trade_review",
        title="BUY-only 未平仓交易不能因无 SELL 归零",
        tags=["buy_only", "open_position"],
        input={"review_type": "single_trade_review", "trade_id": "sample-buy-only"},
        expected_behavior={"data_missing": False},
        expected_output_fields=["summary", "overall_score", "rating", "data_limitations"],
    ),
    EvalCase(
        case_id="trade_review_profit_but_chase_high_not_excellent",
        agent_name="trade_review",
        title="盈利但追高不能只因赚钱评 excellent",
        tags=["chase_high", "scoring"],
        input={"symbol": "NVDA.US"},
        expected_output_fields=["summary", "overall_score", "rating", "mistake_tags"],
        forbidden_behavior=["赚钱就是好交易"],
    ),
    EvalCase(
        case_id="trade_review_loss_but_disciplined_not_poor",
        agent_name="trade_review",
        title="亏损但纪律正确不能只因亏损评 poor",
        tags=["loss", "discipline"],
        input={"symbol": "AMD.US"},
        expected_output_fields=["summary", "overall_score", "rating", "data_limitations"],
    ),
    EvalCase(
        case_id="trade_review_sold_too_early_avoid_hindsight",
        agent_name="trade_review",
        title="卖飞可以指出机会成本但避免后视镜",
        tags=["opportunity_cost", "hindsight"],
        input={"symbol": "TSLA.US"},
        expected_output_fields=["summary", "mistake_tags", "data_limitations"],
        forbidden_behavior=["完全否定当时卖出"],
    ),
    # ---------------------------------------------------------------------------
    # Eval P3 Stage 04: trade_review correctness cases
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="trade_review_correctness_chase_high_profit",
        agent_name="trade_review",
        title="追高买入后继续上涨：不能只因赚钱说对，仍要指出追高风险",
        description="在 5 个交易日上涨 25% 后追高买入，盈利 +5%。期望：不能简单说'赚钱了所以对'，仍要指出追高风险。",
        tags=["correctness", "regression", "behavior_bias", "process_outcome"],
        category="behavior_bias",
        severity="high",
        input={"symbol": "NVDA.US", "trade_id": "sample-chase-profit"},
        expected_output_fields=["summary", "overall_score", "rating", "mistake_tags", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["追高", "FOMO", "高位加仓", "改进", "下次"],
        },
        forbidden_behavior=["赚钱就是好交易", "盈利所以买入对"],
        metadata={
            "correctness_dimensions": [
                "behavior_bias_detection",
                "process_vs_outcome_separation",
                "improvement_suggestion_quality",
            ],
            "expected_behavior_biases": ["chase_high"],
            "require_process_review": True,
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_sold_too_early_no_hindsight",
        agent_name="trade_review",
        title="高位卖出后股票继续涨：不能简单说卖飞就是错",
        description="在 $200 卖出 AAPL 后股票涨到 $250。期望：不能简单否定当时卖出，要看当时计划和风险控制。",
        tags=["correctness", "regression", "hindsight_bias", "process_outcome"],
        category="hindsight_bias",
        severity="high",
        input={"symbol": "AAPL.US", "trade_id": "sample-sold-too-early"},
        expected_output_fields=["summary", "mistake_tags", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["当时", "计划", "风险", "机会成本"],
        },
        forbidden_behavior=["卖飞就是错", "完全否定当时卖出"],
        metadata={
            "correctness_dimensions": [
                "hindsight_bias_avoidance",
                "process_vs_outcome_separation",
            ],
            "hindsight_trap": True,
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_disciplined_loss",
        agent_name="trade_review",
        title="按计划分批加仓但短期亏损：过程可能合理",
        description="按计划在 $X-Y 分 3 批加仓 5%，但短期亏损 -3%。期望：过程可能合理，不能只因亏损否定。",
        tags=["correctness", "regression", "process_outcome", "execution_consistency"],
        category="trade_fact",
        severity="medium",
        input={"symbol": "AMD.US", "trade_id": "sample-disciplined-loss"},
        expected_output_fields=["summary", "overall_score", "rating", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["按计划", "过程合理", "执行纪律", "分批"],
        },
        forbidden_behavior=["亏钱就是差交易"],
        metadata={
            "correctness_dimensions": [
                "process_vs_outcome_separation",
                "execution_consistency",
            ],
            "require_process_review": True,
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_panic_sell_bounce",
        agent_name="trade_review",
        title="恐慌卖出后反弹：识别情绪化和执行偏差",
        description="VIX 飙升 30% 的次日恐慌卖出，2 周后反弹 8%。期望：识别情绪化和执行偏差。",
        tags=["correctness", "regression", "behavior_bias", "execution_consistency"],
        category="behavior_bias",
        severity="high",
        input={"symbol": "AMD.US", "trade_id": "sample-panic-sell"},
        expected_output_fields=["summary", "mistake_tags", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["恐慌", "情绪化", "执行偏差", "VIX"],
        },
        metadata={
            "correctness_dimensions": [
                "behavior_bias_detection",
                "execution_consistency",
            ],
            "expected_behavior_biases": ["panic_sell", "deviation"],
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_concentrated_profit",
        agent_name="trade_review",
        title="仓位过度集中但短期盈利：指出风险，不因盈利掩盖问题",
        description="NVDA 仓位 30%，单票集中度过高，但短期盈利 +12%。期望：指出集中度风险。",
        tags=["correctness", "regression", "risk_position", "process_outcome"],
        category="risk_review",
        severity="high",
        input={"symbol": "NVDA.US", "trade_id": "sample-concentrated-profit"},
        expected_output_fields=["summary", "overall_score", "rating", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["集中度", "仓位", "分散", "风险"],
        },
        metadata={
            "correctness_dimensions": [
                "risk_and_position_review",
                "process_vs_outcome_separation",
            ],
            "require_process_review": True,
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_execution_deviation",
        agent_name="trade_review",
        title="执行偏离原计划：指出偏离点，给出下次执行规则",
        description="原计划在 $X 分 3 批建仓 5%，实际在 $Y（高 8%）一次性建仓 8%。期望：指出偏离点，给出下次执行规则。",
        tags=["correctness", "regression", "execution_consistency", "improvement"],
        category="behavior_bias",
        severity="high",
        input={"symbol": "TSLA.US", "trade_id": "sample-deviation"},
        expected_output_fields=["summary", "mistake_tags", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["偏离", "原计划", "执行", "下次"],
        },
        metadata={
            "correctness_dimensions": [
                "execution_consistency",
                "improvement_suggestion_quality",
            ],
            "expected_behavior_biases": ["deviation"],
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_incomplete_record",
        agent_name="trade_review",
        title="交易记录不完整：说明数据限制，不能编造",
        description="缺少年化收益率、对手方、部分交易细节。期望：说明数据限制，不能编造。",
        tags=["correctness", "regression", "data_limitation"],
        category="data_limitation",
        severity="medium",
        input={"symbol": "META.US", "trade_id": "sample-incomplete"},
        expected_behavior={"data_missing": True},
        expected_data_limitations=["缺少年化收益率", "对手方不可见"],
        expected_output_fields=["summary", "data_limitations"],
        metadata={
            "correctness_dimensions": ["data_limitation_awareness"],
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_right_side_no_stop",
        agent_name="trade_review",
        title="右侧加仓成功但风险控制不足：肯定方向但指出仓位/止损不足",
        description="右侧突破时加仓方向正确但仓位重、止损设置过宽。期望：肯定方向但指出风险控制不足。",
        tags=["correctness", "regression", "risk_position"],
        category="risk_review",
        severity="high",
        input={"symbol": "NVDA.US", "trade_id": "sample-right-no-stop"},
        expected_output_fields=["summary", "overall_score", "rating", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["方向", "止损", "仓位", "风险控制"],
        },
        metadata={
            "correctness_dimensions": [
                "risk_and_position_review",
                "improvement_suggestion_quality",
            ],
            "require_process_review": True,
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_left_side_overload",
        agent_name="trade_review",
        title="左侧越跌越买导致仓位失控",
        description="左侧加仓未设置上限，导致单一标的仓位达 35%。期望：识别左侧加仓风险和仓位上限问题。",
        tags=["correctness", "regression", "behavior_bias", "risk_position"],
        category="behavior_bias",
        severity="critical",
        input={"symbol": "XYZ.US", "trade_id": "sample-left-overload"},
        expected_output_fields=["summary", "overall_score", "rating", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["左侧", "越跌越买", "仓位上限", "集中度"],
        },
        metadata={
            "correctness_dimensions": [
                "behavior_bias_detection",
                "risk_and_position_review",
            ],
            "expected_behavior_biases": ["anchoring", "overconfidence"],
        },
    ),
    EvalCase(
        case_id="trade_review_correctness_mental_accounting",
        agent_name="trade_review",
        title="卖出一半回收本金的心理账户问题",
        description="用户卖掉一半持仓后认为剩余仓位'零成本'。期望：解释心理账户问题。",
        tags=["correctness", "regression", "behavior_bias"],
        category="behavior_bias",
        severity="medium",
        input={"symbol": "TSLA.US", "trade_id": "sample-mental-accounting"},
        expected_output_fields=["summary", "mistake_tags", "improvement_suggestions"],
        expected_behavior={
            "should_mention_any_of": ["心理账户", "锚定", "剩余成本", "free ride"],
        },
        metadata={
            "correctness_dimensions": [
                "behavior_bias_detection",
            ],
            "expected_behavior_biases": ["anchoring"],
        },
    ),
]
