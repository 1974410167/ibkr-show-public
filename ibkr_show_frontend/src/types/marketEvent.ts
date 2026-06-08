/** Market Event types -- mirrors backend Pydantic schemas. */

export type MarketEventSourceCode =
  | 'BLS' | 'BEA' | 'FRED' | 'FED' | 'ISM' | 'LONGBRIDGE' | 'MANUAL' | 'SYSTEM'

export type MarketEventCategory =
  | 'MACRO' | 'FED' | 'COMPANY' | 'MARKET' | 'NEWS' | 'CRYPTO' | 'POLICY' | 'MANUAL'

export type MarketEventType =
  | 'CPI' | 'PPI' | 'NONFARM_PAYROLLS' | 'UNEMPLOYMENT_RATE' | 'JOLTS' | 'PCE' | 'GDP'
  | 'ISM_MANUFACTURING_PMI' | 'ISM_SERVICES_PMI'
  | 'FOMC_RATE_DECISION' | 'FOMC_MINUTES' | 'FOMC_SEP' | 'FED_SPEECH'
  | 'EARNINGS' | 'DIVIDEND' | 'SPLIT' | 'IPO' | 'INVESTOR_DAY' | 'SHAREHOLDER_MEETING'
  | 'MARKET_CLOSED' | 'HALF_TRADING_DAY' | 'TRADING_SESSION_CHANGE'
  | 'NEWS' | 'POLICY' | 'TARIFF' | 'EXPORT_CONTROL' | 'CRYPTO_EVENT' | 'BTC_EVENT' | 'MSTR_BTC_EVENT'
  | 'MANUAL_EVENT' | 'UNKNOWN'

export type MarketEventStatus =
  | 'SCHEDULED' | 'WATCHING' | 'RELEASED' | 'VALUE_UPDATED' | 'INTERPRETED'
  | 'REVIEWED' | 'REVISED' | 'CANCELLED' | 'FAILED'

export type MarketEventImportance = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type MarketEventValueType =
  | 'PREVIOUS' | 'FORECAST' | 'ACTUAL' | 'REVISED' | 'CONSENSUS' | 'LOW_ESTIMATE' | 'HIGH_ESTIMATE'

export type MarketEventImpactDirection = 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL' | 'UNCERTAIN' | 'MIXED'
export type MarketEventImpactLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type MarketEventTestStatus = 'SUCCESS' | 'FAILED' | 'SKIPPED'

export interface MarketEventValueResponse {
  value_type: MarketEventValueType
  label: string
  value_text?: string | null
  value_numeric?: number | null
  unit?: string | null
  currency?: string | null
  period?: string | null
  published_at?: string | null
}

export interface MarketEventImpactResponse {
  symbol?: string | null
  asset_class?: string | null
  market?: string | null
  sector?: string | null
  industry?: string | null
  impact_direction: MarketEventImpactDirection
  impact_level: MarketEventImpactLevel
  reason: string
  confidence: number
  source: string
}

export interface MarketEventNewsLinkResponse {
  title: string
  url: string
  publisher: string
  published_at?: string | null
  summary: string
  symbols: string[]
}

export interface MarketEventListItem {
  id: string
  title: string
  summary: string
  category: MarketEventCategory
  event_type: MarketEventType
  status: MarketEventStatus
  importance: MarketEventImportance
  source_code: MarketEventSourceCode
  country?: string | null
  market?: string | null
  symbols: string[]
  asset_classes: string[]
  scheduled_at: string
  scheduled_timezone: string
  display_time?: string | null
  period?: string | null
  is_all_day: boolean
  is_confirmed_time: boolean
  has_actual_value: boolean
  has_forecast_value: boolean
  source_url?: string | null
  values: MarketEventValueResponse[]
  impacts: MarketEventImpactResponse[]
  created_at?: string | null
  updated_at?: string | null
}

export interface MarketEventDetail extends MarketEventListItem {
  definition_id?: string | null
  region?: string | null
  news_links: MarketEventNewsLinkResponse[]
  analysis: Record<string, unknown>[]
}

export interface MarketEventRiskSummary {
  risk_level: MarketEventImportance
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  top_events: MarketEventListItem[]
}

export interface MarketEventRiskSummaryResponse {
  today: MarketEventRiskSummary
  next_7_days: MarketEventRiskSummary
  next_30_days: MarketEventRiskSummary
}

export interface MarketEventCalendarDay {
  date: string
  risk_level: MarketEventImportance
  events: MarketEventListItem[]
}

export interface MarketEventCalendarResponse {
  days: MarketEventCalendarDay[]
}

export interface MarketEventPaginatedResponse {
  items: MarketEventListItem[]
  total: number
  limit: number
  offset: number
}

export interface MarketEventSourceStatus {
  source_code: MarketEventSourceCode
  source_name: string
  enabled: boolean
  description: string
  doc_url?: string | null
  last_check_status?: MarketEventTestStatus | null
  last_check_at?: string | null
}

export interface MarketEventSourceConfig {
  source_code: MarketEventSourceCode
  source_name: string
  description: string
  enabled: boolean
  priority: number
  apply_url?: string | null
  doc_url?: string | null
  requires_api_key: boolean
  credential_key_name?: string | null
  credential_configured: boolean
  masked_value?: string | null
  last_check_at?: string | null
  last_check_status?: MarketEventTestStatus | null
  last_error?: string | null
  updated_at?: string | null
}

export interface MarketEventSyncRun {
  id: string
  source_code: MarketEventSourceCode
  provider_name: string
  sync_type: string
  status: string
  started_at: string
  finished_at?: string | null
  total_count: number
  created_count: number
  updated_count: number
  skipped_count: number
  failed_count: number
  error_message?: string | null
}
