from pydantic import BaseModel, Field


class TradeDecisionHealthResponse(BaseModel):
    enabled: bool
    llm_configured: bool
    longbridge_configured: bool
    mcp_enabled: bool = False
    mcp_available: bool = False
    mcp_auth_status: str = "disabled"
    mcp_last_error: str = ""
    sdk_fallback_available: bool = False
    longbridge_sdk_configured: bool = False
    public_data_mode: str = "unavailable"
    trade_review_available: bool
    account_data_source: str
    public_market_data_source: str
    agent_mode: str = "trade_decision_langgraph_v1"
    graph_version: str = "trade_decision_graph_v1"
    message: str


class TradeDecisionHoldingItem(BaseModel):
    symbol: str
    normalized_symbol: str
    quantity: float | None = None
    avg_cost: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    position_pct: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    latest_review_score: float | None = None
    latest_decision: str | None = None
    data_source: str = "IBKR"


class TradeDecisionHoldingsResponse(BaseModel):
    items: list[TradeDecisionHoldingItem]


class TradeDecisionAnalyzeHoldingRequest(BaseModel):
    question: str | None = None
    force_refresh: bool = False


class TradeDecisionAnalyzeEntryRequest(BaseModel):
    symbol: str
    question: str | None = None
    force_refresh: bool = False


class TradeDecisionAnalyzeAutoRequest(BaseModel):
    symbol: str
    force_refresh: bool = False


class TradeDecisionScoreItem(BaseModel):
    score: float
    max_score: float
    reason: str = ""


class TradeDecisionPositionAdvice(BaseModel):
    current_position_pct: float | None = None
    suggested_target_position_pct: float | None = None
    max_position_pct: float | None = None
    suggested_cash_amount: float | None = None
    position_size_label: str


class TradeDecisionExecutionStep(BaseModel):
    step: int | None = None
    condition: str | None = None
    action: str | None = None
    amount: float | None = None
    note: str | None = None


class TradeDecisionExecutionPlan(BaseModel):
    should_act_now: bool
    plan: list[dict] = Field(default_factory=list)
    invalid_conditions: list[str] = Field(default_factory=list)
    recheck_triggers: list[str] = Field(default_factory=list)


class AgentRunTraceItem(BaseModel):
    event: str
    node_name: str | None = None
    tool: str | None = None
    tool_call_id: str | None = None
    round: int | None = None
    arguments: dict | None = None
    steps: list[str] | None = None
    ok: bool | None = None
    summary: str | None = None
    latency_ms: int | None = None
    created_at_ms: int | None = None
    elapsed_ms: int | None = None
    tools_called: list[str] | None = None
    tool_call_count: int | None = None
    tool_calls: list[dict] | None = None
    rounds_used: int | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    structured_output: dict | None = None


class TradeDecisionResult(BaseModel):
    id: str
    decision_type: str
    symbol: str
    user_question: str | None = None
    overall_score: float
    rating: str
    action: str
    draft_action: str | None = None
    risk_adjusted_action: str | None = None
    final_action: str | None = None
    action_change_reason: str | None = None
    action_downgrade_chain: list[dict] = Field(default_factory=list)
    confidence: str
    decision_summary: str
    score_detail: dict[str, TradeDecisionScoreItem]
    position_advice: TradeDecisionPositionAdvice
    execution_plan: TradeDecisionExecutionPlan
    key_reasons: list[str]
    major_risks: list[str]
    review_warnings: list[str]
    data_limitations: list[str]
    evidence_used: list[str]
    data_source_summary: dict
    card_pack: dict = Field(default_factory=dict)
    asset_debate: dict = Field(default_factory=dict)
    trade_plan: dict = Field(default_factory=dict)
    risk_gate: dict = Field(default_factory=dict)
    user_investment_policy_summary: dict | None = None
    ai_policy_assessment: dict = Field(default_factory=dict)
    decision_quality: dict = Field(default_factory=dict)
    run_trace: list[AgentRunTraceItem] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    evidence_summary: dict = Field(default_factory=dict)
    run_trace_summary: dict = Field(default_factory=dict)
    fallback_used: bool = False
    fallback_reason: str | None = None
    llm_error_summary: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class TradeDecisionListResponse(BaseModel):
    items: list[TradeDecisionResult]


class TradeDecisionOutcomeItem(BaseModel):
    decision_id: str
    symbol: str
    decision_type: str
    created_at: str
    decision_date: str | None = None
    draft_action: str | None = None
    risk_adjusted_action: str | None = None
    final_action: str | None = None
    action_group: str
    ai_position_stance: str | None = None
    ai_recommended_action_bias: str | None = None
    ai_recommended_target_position_pct: float | None = None
    ai_recommended_max_position_pct: float | None = None
    user_preferred_target_position_pct: float | None = None
    decision_price: float | None = None
    price_after_1d: float | None = None
    price_after_5d: float | None = None
    price_after_20d: float | None = None
    return_1d: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    max_drawdown_20d: float | None = None
    max_runup_20d: float | None = None
    price_data_status: str = "unknown"
    outcome_label: str
    outcome_reason: str
    data_limitations: list[str] = Field(default_factory=list)


class TradeDecisionOutcomeSummary(BaseModel):
    version: str
    total_count: int
    evaluated_count: int
    pending_count: int
    missing_price_count: int
    add_like_count: int
    hold_like_count: int
    reduce_like_count: int
    add_like_avg_return_1d: float | None = None
    add_like_avg_return_5d: float | None = None
    add_like_avg_return_20d: float | None = None
    hold_like_avg_return_1d: float | None = None
    hold_like_avg_return_5d: float | None = None
    hold_like_avg_return_20d: float | None = None
    reduce_like_avg_return_1d: float | None = None
    reduce_like_avg_return_5d: float | None = None
    reduce_like_avg_return_20d: float | None = None
    add_like_win_rate_5d: float
    add_like_win_rate_20d: float
    bad_add_count: int
    missed_upside_count: int
    avoided_loss_count: int
    sold_too_early_count: int
    missed_ai_add_opportunity_count: int
    calibrated_action_success_count: int
    risk_gate_avoided_loss_count: int
    risk_gate_missed_upside_count: int
    action_value_score: float | None = None
    outcome_label_distribution: list[dict]
    action_group_distribution: list[dict]
    by_symbol: list[dict]
    by_final_action: list[dict]
    by_ai_recommended_action_bias: list[dict]
    by_ai_position_stance: list[dict]
    top_good_decisions: list[TradeDecisionOutcomeItem]
    top_bad_decisions: list[TradeDecisionOutcomeItem]
    top_missed_upside_decisions: list[TradeDecisionOutcomeItem]
    generated_at: str
    data_limitations: list[str] = Field(default_factory=list)


class TradeDecisionOutcomeListResponse(BaseModel):
    items: list[TradeDecisionOutcomeItem]
    summary: TradeDecisionOutcomeSummary
