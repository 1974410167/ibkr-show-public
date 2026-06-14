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
  ai_policy_assessment: Record<string, unknown>
  action_calibration: Record<string, unknown>
  top_hard_failures: TradeDecisionQualityTopItem[]
  top_warnings: TradeDecisionQualityTopItem[]
  top_flags: TradeDecisionQualityTopItem[]
  recent_trend: TradeDecisionQualityTrendItem[]
  generated_at: string
  data_limitations: string[]
}

export interface TradeDecisionOutcomeItem {
  decision_id: string
  symbol: string
  decision_type: string
  created_at: string
  decision_date: string | null
  draft_action: string | null
  risk_adjusted_action: string | null
  final_action: string | null
  action_group: string
  ai_position_stance: string | null
  ai_recommended_action_bias: string | null
  ai_recommended_target_position_pct: number | null
  ai_recommended_max_position_pct: number | null
  user_preferred_target_position_pct: number | null
  decision_price: number | null
  price_after_1d: number | null
  price_after_5d: number | null
  price_after_20d: number | null
  return_1d: number | null
  return_5d: number | null
  return_20d: number | null
  max_drawdown_20d: number | null
  max_runup_20d: number | null
  price_data_status: string
  outcome_label: string
  outcome_reason: string
  data_limitations: string[]
}

export interface TradeDecisionOutcomeSummary {
  version: string
  total_count: number
  evaluated_count: number
  pending_count: number
  missing_price_count: number
  add_like_count: number
  hold_like_count: number
  reduce_like_count: number
  add_like_avg_return_1d: number | null
  add_like_avg_return_5d: number | null
  add_like_avg_return_20d: number | null
  hold_like_avg_return_1d: number | null
  hold_like_avg_return_5d: number | null
  hold_like_avg_return_20d: number | null
  reduce_like_avg_return_1d: number | null
  reduce_like_avg_return_5d: number | null
  reduce_like_avg_return_20d: number | null
  add_like_win_rate_5d: number
  add_like_win_rate_20d: number
  bad_add_count: number
  missed_upside_count: number
  avoided_loss_count: number
  sold_too_early_count: number
  missed_ai_add_opportunity_count: number
  calibrated_action_success_count: number
  risk_gate_avoided_loss_count: number
  risk_gate_missed_upside_count: number
  action_value_score: number | null
  outcome_label_distribution: TradeDecisionQualityTopItem[]
  action_group_distribution: TradeDecisionQualityTopItem[]
  by_symbol: TradeDecisionQualityTopItem[]
  by_final_action: TradeDecisionQualityTopItem[]
  by_ai_recommended_action_bias: TradeDecisionQualityTopItem[]
  by_ai_position_stance: TradeDecisionQualityTopItem[]
  top_good_decisions: TradeDecisionOutcomeItem[]
  top_bad_decisions: TradeDecisionOutcomeItem[]
  top_missed_upside_decisions: TradeDecisionOutcomeItem[]
  generated_at: string
  data_limitations: string[]
}

export interface TradeDecisionOutcomeListResponse {
  items: TradeDecisionOutcomeItem[]
  summary: TradeDecisionOutcomeSummary
}

export interface UserInvestmentPolicySummary {
  source: 'user_config' | 'default_template' | 'fallback' | string
  asset_role: string
  conviction: string
  user_preferred_min_position_pct: number | null
  user_preferred_target_position_pct: number | null
  user_preferred_max_position_pct: number | null
  current_position_pct: number | null
  gap_to_user_preferred_target_pct: number | null
  gap_to_user_preferred_max_pct: number | null
  user_preference_gap_label?: string
  enabled: boolean
  add_rules: string[]
  no_add_triggers: string[]
  sell_triggers: string[]
  hard_constraints: string[]
  soft_preferences: string[]
  notes: string
  ai_review_status: string
  ai_review_summary: string | null
  disclaimer: string
}

export interface AiPolicyAssessment {
  status?: 'evaluated' | 'fallback' | 'not_evaluated' | string
  ai_assessed_asset_role?: string | null
  ai_role_confidence?: string | null
  ai_recommended_min_position_pct?: number | null
  ai_recommended_target_position_pct?: number | null
  ai_recommended_max_position_pct?: number | null
  ai_recommended_target_position_range_pct?: number[] | null
  ai_position_stance?: string | null
  current_position_pct?: number | null
  gap_to_ai_target_pct?: number | null
  gap_to_ai_max_pct?: number | null
  challenge_level?: string | null
  challenge_reason?: string | null
  preference_alignment_summary?: string | null
  recommended_action_bias?: string | null
  risk_budget?: Record<string, unknown>
  key_reasons?: string[]
  key_risks?: string[]
  data_limitations?: string[]
  prompt_key?: string
  prompt_source?: string
  prompt_version?: string | null
}

export interface TradeDecisionResult {
  id: string
  decision_type: string
  symbol: string
  user_question: string | null
  overall_score: number
  rating: string
  action: string
  draft_action?: string | null
  risk_adjusted_action?: string | null
  final_action?: string | null
  action_change_reason?: string | null
  action_downgrade_chain?: Array<Record<string, unknown>>
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
  user_investment_policy_summary?: UserInvestmentPolicySummary | null
  ai_policy_assessment?: AiPolicyAssessment
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
