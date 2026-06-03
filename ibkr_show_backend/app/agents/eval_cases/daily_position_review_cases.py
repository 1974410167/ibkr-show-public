from app.agents.eval_harness import EvalCase


CASES = [
    EvalCase(
        case_id="daily_review_account_attribution_before_news",
        agent_name="daily_position_review",
        title="账户涨跌应账户归因优先于新闻叙事",
        tags=["attribution", "account_first"],
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
    ),
    EvalCase(
        case_id="daily_review_public_data_missing_limitations",
        agent_name="daily_position_review",
        title="公开数据不足必须写 data_limitations",
        tags=["data_missing"],
        input={"report_date": "2026-05-21"},
        expected_behavior={"data_missing": True},
        expected_output_fields=["summary", "data_limitations"],
    ),
    EvalCase(
        case_id="daily_review_small_move_no_over_attribution",
        agent_name="daily_position_review",
        title="单日小波动不能强行归因到单一新闻",
        tags=["attribution", "small_move"],
        input={"report_date": "2026-05-22"},
        expected_output_fields=["summary", "data_limitations"],
        forbidden_behavior=["唯一原因", "完全因为"],
    ),
    EvalCase(
        case_id="daily_review_mstr_no_btc_without_data",
        agent_name="daily_position_review",
        title="MSTR 缺 BTC 数据时不能凭空归因 BTC",
        tags=["mstr", "btc", "data_missing"],
        input={"report_date": "2026-05-23", "symbol": "MSTR.US"},
        expected_behavior={"data_missing": True},
        expected_output_fields=["summary", "data_limitations"],
    ),
    # ---------------------------------------------------------------------------
    # Eval P3 Stage 03: daily_position_review correctness cases
    # ---------------------------------------------------------------------------
    EvalCase(
        case_id="daily_review_correctness_main_position_driver",
        agent_name="daily_position_review",
        title="单只大仓位导致账户上涨：必须识别为主要贡献",
        description="AMD 是最大仓位（18%）并当日 +2.2%；其他持仓变动较小。期望：指出 AMD 是主要贡献。",
        tags=["correctness", "regression", "attribution", "position_contribution"],
        category="attribution",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["AMD", "主要贡献", "主要驱动"],
        },
        metadata={
            "correctness_dimensions": [
                "portfolio_pnl_accuracy",
                "position_contribution_accuracy",
                "attribution_quality",
            ],
            "position_weights": {"AMD": 0.18, "NVDA": 0.12, "AAPL": 0.10, "TSLA": 0.04},
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_small_position_not_main",
        agent_name="daily_position_review",
        title="小仓位大涨但仓位小，不能说成主要贡献",
        description="XYZ 仓位 0.5%、当日 +20%；AMD 仓位 18%、当日 +2.2%。期望：XYZ 不是主要贡献。",
        tags=["correctness", "regression", "position_contribution", "position_weight"],
        category="position_contribution",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["AMD", "主要贡献", "仓位"],
        },
        forbidden_behavior=["XYZ 是主要贡献", "XYZ 贡献最大"],
        metadata={
            "correctness_dimensions": [
                "position_contribution_accuracy",
                "position_weight_awareness" if False else "position_contribution_accuracy",
            ],
            "position_weights": {"AMD": 0.18, "XYZ": 0.005},
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_market_beta_day",
        agent_name="daily_position_review",
        title="市场普涨带动组合：归因为市场 beta 而非编新闻",
        description="多数持仓上涨，但无个股重大新闻；SPY +1.2%。期望：归因为市场/行业 beta。",
        tags=["correctness", "regression", "attribution", "market_vs_stock"],
        category="attribution",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["市场", "beta", "板块", "普涨", "market"],
        },
        metadata={
            "correctness_dimensions": [
                "attribution_quality",
                "market_vs_idiosyncratic_split",
            ],
            "market_context": {"spy_change_pct": 1.2, "sector_change_pct": 1.1},
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_single_stock_negative",
        agent_name="daily_position_review",
        title="个股利空导致下跌：指出个股事件并说明影响",
        description="SMCI 仓位 8%、Q3 财报不及预期、当日 -12%。期望：指出个股事件。",
        tags=["correctness", "regression", "attribution", "single_stock_event"],
        category="attribution",
        severity="high",
        input={"report_date": "2026-05-20", "symbol": "SMCI.US"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["SMCI", "财报", "不及预期", "个股"],
        },
        metadata={
            "correctness_dimensions": [
                "attribution_quality",
                "portfolio_pnl_accuracy",
            ],
            "position_weights": {"SMCI": 0.08, "AAPL": 0.20, "NVDA": 0.15},
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_news_time_mismatch",
        agent_name="daily_position_review",
        title="新闻时间不匹配：几天前新闻不应归因当天涨跌",
        description="GTC 大会发生在 5 天前，不应作为今天 AMD 涨跌的主因。",
        tags=["correctness", "regression", "news_relevance", "time_mismatch"],
        category="news_relevance",
        severity="high",
        input={"report_date": "2026-05-20", "symbol": "AMD.US"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["新闻时效", "时间不匹配", "data_limitations"],
        },
        forbidden_behavior=["因为 GTC 大会"],
        metadata={
            "correctness_dimensions": ["news_relevance"],
            "news_irrelevant": True,
            "news_time_mismatch": True,
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_data_missing_limitations",
        agent_name="daily_position_review",
        title="数据缺失：缺少持仓权重或新闻",
        description="缺少持仓权重和部分新闻。期望：明确数据限制，不编造。",
        tags=["correctness", "regression", "data_limitation"],
        category="data_limitation",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_behavior={"data_missing": True},
        expected_data_limitations=["缺少持仓权重", "部分新闻不可用"],
        expected_output_fields=["summary", "data_limitations"],
        metadata={
            "correctness_dimensions": ["data_limitation_awareness"],
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_fx_cash_impact",
        agent_name="daily_position_review",
        title="汇率或现金影响：不要只归因股票",
        description="账户净值变化部分来自汇率/现金。期望：不要只归因股票。",
        tags=["correctness", "regression", "attribution", "fx_cash"],
        category="attribution",
        severity="medium",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["汇率", "现金", "FX", "cash", "换算"],
        },
        metadata={
            "correctness_dimensions": [
                "attribution_quality",
                "data_limitation_awareness",
            ],
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_why_loss_today",
        agent_name="daily_position_review",
        title="用户问今天为什么亏：重点突出最大亏损来源和风险点",
        description="用户问今天为什么亏。期望：重点突出最大亏损来源和风险点。",
        tags=["correctness", "regression", "user_facing", "risk_observation"],
        category="risk_observation",
        severity="medium",
        input={"report_date": "2026-05-20", "question": "今天为什么亏？"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["主要亏损", "拖累", "风险", "集中度"],
        },
        metadata={
            "correctness_dimensions": [
                "portfolio_pnl_accuracy",
                "risk_observation",
            ],
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_no_strong_trade_advice",
        agent_name="daily_position_review",
        title="复盘不应变成交易决策：不要强买/强卖",
        description="复盘默认不是交易建议。期望：不给强买/强卖。",
        tags=["correctness", "regression", "no_strong_trade"],
        category="no_strong_trade",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_not_recommend": ["强烈买入", "重仓", "all in", "立即清仓", "强买入"],
        },
        forbidden_behavior=["今天必须清仓", "all in 买入"],
        metadata={
            "correctness_dimensions": [
                "uncertainty_handling",
                "user_alignment",
            ],
        },
    ),
    EvalCase(
        case_id="daily_review_correctness_mixed_factors",
        agent_name="daily_position_review",
        title="多因素混合：市场下跌 + 个股新闻 + 仓位集中",
        description="市场下跌 -1.2%，单一个股因利空 -8%，仓位集中度高。期望：按影响大小排序。",
        tags=["correctness", "regression", "attribution", "risk_observation", "mixed_factors"],
        category="attribution",
        severity="high",
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
        expected_behavior={
            "should_mention_any_of": ["市场", "个股", "集中度", "仓位"],
        },
        metadata={
            "correctness_dimensions": [
                "attribution_quality",
                "market_vs_idiosyncratic_split",
                "risk_observation",
            ],
            "market_context": {"spy_change_pct": -1.2},
            "position_weights": {"SMCI": 0.20, "AAPL": 0.15, "NVDA": 0.12},
        },
    ),
]
