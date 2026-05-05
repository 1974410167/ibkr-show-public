import { request } from './http'
import type { DividendListResponse, DividendSummaryResponse } from '@/types/dividends'

export interface DividendQuery {
  start_date?: string
  end_date?: string
  currency?: string
  symbol?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export function fetchDividends(params: DividendQuery): Promise<DividendListResponse> {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      searchParams.set(key, String(value))
    }
  })

  const queryString = searchParams.toString()
  return request<DividendListResponse>(`/api/dividends${queryString ? `?${queryString}` : ''}`)
}

export function fetchDividendSummary(
  params: Omit<DividendQuery, 'sort_by' | 'sort_order' | 'page' | 'page_size'>,
): Promise<DividendSummaryResponse> {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      searchParams.set(key, String(value))
    }
  })

  const queryString = searchParams.toString()
  return request<DividendSummaryResponse>(`/api/dividends/summary${queryString ? `?${queryString}` : ''}`)
}
