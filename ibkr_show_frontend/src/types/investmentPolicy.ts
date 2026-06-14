export type RiskProfile = 'conservative' | 'balanced' | 'aggressive_growth'
export type AddStyle = 'left_side_add' | 'pullback_add' | 'right_side_confirm' | 'batch_add'
export type AssetRole =
  | 'core_growth'
  | 'faith_holding'
  | 'satellite_growth'
  | 'speculative'
  | 'btc_proxy'
  | 'cash_like'
  | 'index_etf'
  | 'watchlist'
  | 'forbidden'
  | 'unknown'
export type Conviction = 'high' | 'medium' | 'low'
export type AiReviewStatus = 'unknown' | 'reasonable' | 'questionable' | 'risky'

export interface GlobalInvestmentPolicy {
  id: string
  policy_type: 'global'
  risk_profile: RiskProfile
  target_annual_return_pct: number | null
  max_drawdown_tolerance_pct: number | null
  allow_concentrated_position: boolean
  allow_single_position_over_20_pct: boolean
  allow_leverage: boolean
  cash_reserve_pct: number | null
  preferred_add_styles: AddStyle[]
  preferred_sell_style: string
  holding_period: string
  notes: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface GlobalInvestmentPolicyPayload {
  risk_profile: RiskProfile
  target_annual_return_pct: number | null
  max_drawdown_tolerance_pct: number | null
  allow_concentrated_position: boolean
  allow_single_position_over_20_pct: boolean
  allow_leverage: boolean
  cash_reserve_pct: number | null
  preferred_add_styles: AddStyle[]
  preferred_sell_style: string
  holding_period: string
  notes: string
  enabled: boolean
}

export interface SymbolInvestmentPolicy {
  id: string
  policy_type: 'symbol'
  symbol: string
  asset_role: AssetRole
  conviction: Conviction
  user_preferred_target_position_pct: number | null
  user_preferred_max_position_pct: number
  user_preferred_min_position_pct: number
  add_rules: string[]
  no_add_triggers: string[]
  sell_triggers: string[]
  hard_constraints: string[]
  soft_preferences: string[]
  notes: string
  enabled: boolean
  ai_review_status: AiReviewStatus
  ai_review_summary: string | null
  ai_review_updated_at: string | null
  created_at: string
  updated_at: string
}

export interface SymbolInvestmentPolicyPayload {
  symbol: string
  asset_role: AssetRole
  conviction: Conviction
  user_preferred_target_position_pct: number | null
  user_preferred_max_position_pct: number
  user_preferred_min_position_pct: number
  add_rules: string[]
  no_add_triggers: string[]
  sell_triggers: string[]
  hard_constraints: string[]
  soft_preferences: string[]
  notes: string
  enabled: boolean
  ai_review_status: AiReviewStatus
  ai_review_summary?: string | null
  ai_review_updated_at?: string | null
}

export interface SymbolInvestmentPolicyListResponse {
  items: SymbolInvestmentPolicy[]
}

export interface InvestmentPolicySeedDefaultsResponse {
  created: SymbolInvestmentPolicy[]
  skipped: SymbolInvestmentPolicy[]
  message: string
}
