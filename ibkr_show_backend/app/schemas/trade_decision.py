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
