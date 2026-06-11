export interface TradeDecisionHealth {
  enabled: boolean
  llm_configured: boolean
  longbridge_configured: boolean
  mcp_enabled: boolean
  mcp_available: boolean
  mcp_auth_status: string
  mcp_last_error: string
  sdk_fallback_available: boolean
  longbridge_sdk_configured: boolean
  public_data_mode: string
  trade_review_available: boolean
  account_data_source: string
  public_market_data_source: string
  message: string
}

export interface TradeDecisionScoreItem {
  score: number
  max_score: number
  reason: string
}

export interface TradeDecisionPositionAdvice {
  current_position_pct: number | null
  suggested_target_position_pct: number | null
  max_position_pct: number | null
  suggested_cash_amount: number | null
  position_size_label: string
  adjustment_pct?: number | null
}

export interface TradeDecisionExecutionPlan {
  should_act_now: boolean
  plan: Array<Record<string, unknown>>
  invalid_conditions: string[]
  recheck_triggers: string[]
}

export interface AgentRunTraceItem {
  event: string
  tool?: string | null
  tool_call_id?: string | null
  round?: number | null
  arguments?: Record<string, unknown> | null
  steps?: string[] | null
  ok?: boolean | null
  summary?: string | null
  latency_ms?: number | null
  created_at_ms?: number | null
}

export interface TradeDecisionQualityCheck {
  passed?: boolean
  hard_failures?: string[]
  warnings?: string[]
  flags?: string[]
  [key: string]: unknown
}

export interface TradeDecisionQuality {
  version?: string
  score?: number
  level?: 'excellent' | 'good' | 'warning' | 'poor' | string
  passed?: boolean
  hard_failures?: string[]
  warnings?: string[]
  flags?: string[]
  checks?: Record<string, TradeDecisionQualityCheck>
  summary?: string
  fallback_used?: boolean
  fallback_reason?: string | null
}

export interface TradeDecisionQualityTopItem {
  key: string
  count: number
}

export interface TradeDecisionQualityTrendItem {
  id: string
  symbol: string
  created_at: string
  score: number | null
  level: string
  passed: boolean | null
  action: string
}

export interface TradeDecisionQualitySummary {
  version: string
  total_count: number
  evaluated_count: number
  unevaluated_count: number
  pass_count: number
  fail_count: number
  pass_rate: number | null
  average_score: number | null
  level_distribution: Record<string, number>
  risk_gate: Record<string, unknown>
  structured_output: Record<string, unknown>
  action_consistency: Record<string, unknown>
  top_hard_failures: TradeDecisionQualityTopItem[]
  top_warnings: TradeDecisionQualityTopItem[]
  top_flags: TradeDecisionQualityTopItem[]
  recent_trend: TradeDecisionQualityTrendItem[]
  generated_at: string
  data_limitations: string[]
}

export interface TradeDecisionResult {
  id: string
  decision_type: string
  symbol: string
  user_question: string | null
  overall_score: number
  rating: string
  action: string
  confidence: string
  decision_summary: string
  score_detail: Record<string, TradeDecisionScoreItem>
  position_advice: TradeDecisionPositionAdvice
  execution_plan: TradeDecisionExecutionPlan
  key_reasons: string[]
  major_risks: string[]
  review_warnings: string[]
  data_limitations: string[]
  evidence_used: string[]
  data_source_summary: Record<string, string>
  card_pack?: Record<string, unknown>
  asset_debate?: Record<string, unknown>
  trade_plan?: Record<string, unknown>
  risk_gate?: Record<string, unknown>
  decision_quality?: TradeDecisionQuality
  run_trace: AgentRunTraceItem[]
  metadata: Record<string, unknown>
  evidence_summary: Record<string, unknown>
  run_trace_summary: Record<string, unknown>
  fallback_used?: boolean
  fallback_reason?: string | null
  created_at: string
  updated_at: string
}

export interface TradeDecisionListResponse {
  items: TradeDecisionResult[]
}

export interface TradeDecisionHoldingItem {
  symbol: string
  normalized_symbol: string
  quantity: number | null
  avg_cost: number | null
  current_price: number | null
  market_value: number | null
  position_pct: number | null
  unrealized_pnl: number | null
  unrealized_pnl_pct: number | null
  latest_review_score: number | null
  latest_decision: string | null
  data_source: string
}

export interface TradeDecisionHoldingsResponse {
  items: TradeDecisionHoldingItem[]
}
