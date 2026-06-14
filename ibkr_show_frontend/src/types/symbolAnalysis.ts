export interface FinancialField {
  id: string
  name: string
  value: number | string | null
  raw_value: string | null
  yoy: number | null
  value_type: string | null
  level: number | null
}

export interface FinancialPeriod {
  label: string
  fiscal_year: number | null
  fiscal_period: string
  report_type: string
  metrics: Record<string, number | null>
  statements: Record<string, FinancialField[]>
}

export interface SymbolMarketSnapshot {
  symbol: string
  name: string | null
  currency: string | null
  last_price: number | null
  change_percent: number | null
  market_cap: number | null
  pe_ttm: number | null
  forward_pe: number | null
  pe_3y_median: number | null
  pe_industry_median: number | null
  pb: number | null
  dividend_yield: number | null
  turnover_rate: number | null
  eps_ttm: number | null
  forward_eps: number | null
  bps: number | null
  total_shares: number | null
  valuation_date: string | null
  valuation_summary: string | null
}

export interface SymbolFinancialsResponse {
  symbol: string
  currency: string | null
  report_type: string
  period_count: number
  periods: FinancialPeriod[]
  market_snapshot: SymbolMarketSnapshot | null
  source: string
}

export interface MetricComparisonItem {
  key: string
  label: string
  left_value: number | null
  right_value: number | null
  winner: 'left' | 'right' | 'tie' | 'unknown' | string
}

export interface SymbolComparisonResponse {
  left: SymbolFinancialsResponse
  right: SymbolFinancialsResponse
  latest_metric_comparison: MetricComparisonItem[]
}

export interface SymbolAiAdviceResponse {
  left_symbol: string
  right_symbol: string
  recommendation: 'left' | 'right' | 'neutral' | string
  confidence: 'high' | 'medium' | 'low' | string
  summary: string
  key_reasons: string[]
  risks: string[]
  add_conditions: string[]
  data_limitations: string[]
  raw_response: string | null
}

export type SymbolAnalysisTaskStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface SymbolAnalysisTaskStep {
  id: string
  label: string
  status: SymbolAnalysisTaskStatus
}

export interface SymbolAnalysisTask {
  id: string
  label: string
  status: SymbolAnalysisTaskStatus
  stage: string
  started_at: string
  completed_at: string | null
  error_message: string | null
  steps: SymbolAnalysisTaskStep[]
}

export interface SymbolAnalysisSnapshot {
  loading: boolean
  errorMessage: string
  singleFinancials: SymbolFinancialsResponse | null
  comparison: SymbolComparisonResponse | null
  aiAdvice: SymbolAiAdviceResponse | null
  aiAdviceLoading: boolean
  aiAdviceError: string
}
