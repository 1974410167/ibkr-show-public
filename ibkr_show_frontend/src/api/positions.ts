import { request } from './http'
import type { PositionDetailResponse, PositionListResponse, PositionSummaryResponse } from '@/types/positions'

export interface PositionQuery {
  report_date?: string
  symbol?: string
  asset_class?: string
  include_summary?: boolean
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export function fetchPositions(params: PositionQuery): Promise<PositionListResponse> {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      searchParams.set(key, String(value))
    }
  })

  const queryString = searchParams.toString()
  return request<PositionListResponse>(`/api/positions${queryString ? `?${queryString}` : ''}`)
}

export function fetchPositionSummary(params: Omit<PositionQuery, 'sort_by' | 'sort_order' | 'page' | 'page_size'>): Promise<PositionSummaryResponse> {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      searchParams.set(key, String(value))
    }
  })

  const queryString = searchParams.toString()
  return request<PositionSummaryResponse>(`/api/positions/summary${queryString ? `?${queryString}` : ''}`)
}

export function fetchPositionDetail(params: { symbol: string; asset_class?: string | null }): Promise<PositionDetailResponse> {
  const searchParams = new URLSearchParams()
  searchParams.set('symbol', params.symbol)
  if (params.asset_class) {
    searchParams.set('asset_class', params.asset_class)
  }
  return request<PositionDetailResponse>(`/api/positions/detail?${searchParams.toString()}`)
}
