import { request } from './http'
import type { TradeListResponse, TradeSummaryResponse } from '@/types/trades'

export interface TradeQuery {
  start_date?: string
  end_date?: string
  symbol?: string
  asset_class?: string
  buy_sell?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

function toQueryString(
  params: Record<string, string | number | undefined | null> | TradeQuery,
): string {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      searchParams.set(key, String(value))
    }
  })
  const queryString = searchParams.toString()
  return queryString ? `?${queryString}` : ''
}

export function fetchTrades(params: TradeQuery): Promise<TradeListResponse> {
  return request<TradeListResponse>(`/api/trades${toQueryString(params)}`)
}

export function fetchTradeSummary(params: Omit<TradeQuery, 'sort_by' | 'sort_order' | 'page' | 'page_size'>): Promise<TradeSummaryResponse> {
  return request<TradeSummaryResponse>(`/api/trades/summary${toQueryString(params)}`)
}
