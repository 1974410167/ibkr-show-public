/** Market Event API client. */

import { request } from './http'
import type {
  MarketEventCalendarResponse,
  MarketEventDetail,
  MarketEventPaginatedResponse,
  MarketEventRiskSummaryResponse,
  MarketEventSourceConfig,
  MarketEventSourceStatus,
  MarketEventSyncRun,
  MarketEventTestStatus,
} from '@/types/marketEvent'

export interface MarketEventQueryParams {
  start_at?: string
  end_at?: string
  category?: string
  event_type?: string
  status?: string
  importance?: string
  source_code?: string
  symbol?: string
  market?: string
  country?: string
  keyword?: string
  limit?: number
  offset?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  display_timezone?: string
  include_values?: boolean
  include_impacts?: boolean
}

function buildQuery(params: object): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

// Public endpoints

export function getMarketEvents(params: MarketEventQueryParams = {}): Promise<MarketEventPaginatedResponse> {
  return request<MarketEventPaginatedResponse>(`/api/market-events${buildQuery(params)}`)
}

export function getTodayMarketEvents(params: { display_timezone?: string; market?: string; symbol?: string; importance?: string } = {}): Promise<MarketEventPaginatedResponse> {
  return request<MarketEventPaginatedResponse>(`/api/market-events/today${buildQuery(params)}`)
}

export function getUpcomingMarketEvents(params: { days?: number; importance?: string; symbol?: string; market?: string; category?: string } = {}): Promise<MarketEventPaginatedResponse> {
  return request<MarketEventPaginatedResponse>(`/api/market-events/upcoming${buildQuery(params)}`)
}

export function getMarketEventRiskSummary(params: { display_timezone?: string } = {}): Promise<MarketEventRiskSummaryResponse> {
  return request<MarketEventRiskSummaryResponse>(`/api/market-events/risk-summary${buildQuery(params)}`)
}

export function getMarketEventCalendar(params: { start_at?: string; end_at?: string; category?: string; market?: string; symbol?: string; display_timezone?: string } = {}): Promise<MarketEventCalendarResponse> {
  return request<MarketEventCalendarResponse>(`/api/market-events/calendar${buildQuery(params)}`)
}

export function getMarketEventDetail(id: string, params: { include_raw?: boolean } = {}): Promise<MarketEventDetail> {
  return request<MarketEventDetail>(`/api/market-events/${id}${buildQuery(params)}`)
}

export function getSymbolMarketEvents(symbol: string, params: { days?: number; include_macro?: boolean; include_news?: boolean } = {}): Promise<MarketEventPaginatedResponse> {
  return request<MarketEventPaginatedResponse>(`/api/market-events/symbol/${symbol}${buildQuery(params)}`)
}

export function getMarketEventSources(): Promise<MarketEventSourceStatus[]> {
  return request<MarketEventSourceStatus[]>('/api/market-events/sources')
}

// Admin endpoints

export function getAdminMarketEventSources(): Promise<MarketEventSourceConfig[]> {
  return request<MarketEventSourceConfig[]>('/api/admin/market-events/sources')
}

export function getAdminMarketEventSource(sourceCode: string): Promise<MarketEventSourceConfig> {
  return request<MarketEventSourceConfig>(`/api/admin/market-events/sources/${sourceCode}`)
}

export function updateAdminMarketEventSource(sourceCode: string, body: { enabled?: boolean; priority?: number; description?: string }): Promise<MarketEventSourceConfig> {
  return request<MarketEventSourceConfig>(`/api/admin/market-events/sources/${sourceCode}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function saveAdminMarketEventCredential(sourceCode: string, body: { credential_key: string; value: string }): Promise<MarketEventSourceConfig> {
  return request<MarketEventSourceConfig>(`/api/admin/market-events/sources/${sourceCode}/credential`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function deleteAdminMarketEventCredential(sourceCode: string): Promise<MarketEventSourceConfig> {
  return request<MarketEventSourceConfig>(`/api/admin/market-events/sources/${sourceCode}/credential`, {
    method: 'DELETE',
  })
}

export function testAdminMarketEventSource(sourceCode: string): Promise<{ source_code: string; status: MarketEventTestStatus; message: string }> {
  return request(`/api/admin/market-events/sources/${sourceCode}/test`, { method: 'POST' })
}

export function getAdminMarketEventSyncRuns(params: { source_code?: string; sync_type?: string; status?: string; limit?: number; offset?: number } = {}): Promise<MarketEventSyncRun[]> {
  return request<MarketEventSyncRun[]>(`/api/admin/market-events/sync-runs${buildQuery(params)}`)
}

export function triggerMarketEventSync(body: {
  source_codes?: string[]
  sync_types?: string[]
  start_at?: string
  end_at?: string
  dry_run?: boolean
}): Promise<unknown> {
  return request('/api/admin/market-events/sync', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
