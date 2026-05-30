export interface TradeReviewScoreItem {
  score: number | null
  max_score: number
  reason: string
  applicable?: boolean
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

export interface ExcludedScoreDimension {
  key: string
  label: string
  max_score: number
  reason: string
}

export interface TradeReviewResult {
  id: string
  review_type: string
  symbol: string
  trade_ids: string[]
  start_date: string | null
  end_date: string | null
  overall_score: number
  rating: string
  score_detail: Record<string, TradeReviewScoreItem>
  raw_applicable_score?: number
  applicable_max_score?: number
  excluded_score_dimensions?: ExcludedScoreDimension[]
  summary: string
  strengths: string[]
  weaknesses: string[]
  mistake_tags: string[]
  improvement_suggestions: string[]
  data_limitations: string[]
  evidence_used: string[]
  run_trace: AgentRunTraceItem[]
  metadata: Record<string, unknown>
  evidence_summary: Record<string, unknown>
  run_trace_summary: Record<string, unknown>
  evidence_pack?: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface TradeReviewListResponse {
  items: TradeReviewResult[]
}

export interface TradeReviewHealth {
  enabled: boolean
  llm_configured: boolean
  longbridge_configured: boolean
  message: string
}

export interface TradeReviewMistakeSummaryItem {
  tag: string
  count: number
  symbols: string[]
  latest_review_id: string
}

export interface TradeReviewMistakeSummaryResponse {
  items: TradeReviewMistakeSummaryItem[]
}
