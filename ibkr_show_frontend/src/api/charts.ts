import { request } from './http'
import type { EquityCurveResponse, PerformanceCalendarResponse, PerformanceCalendarView } from '@/types/charts'

export function fetchEquityCurve(params: {
  start_date?: string
  end_date?: string
} = {}): Promise<EquityCurveResponse> {
  const searchParams = new URLSearchParams()
  if (params.start_date) {
    searchParams.set('start_date', params.start_date)
  }
  if (params.end_date) {
    searchParams.set('end_date', params.end_date)
  }
  const queryString = searchParams.toString()
  return request<EquityCurveResponse>(`/api/charts/equity-curve${queryString ? `?${queryString}` : ''}`)
}

export function fetchPerformanceCalendar(params: {
  view: PerformanceCalendarView
  anchor?: string
}): Promise<PerformanceCalendarResponse> {
  const searchParams = new URLSearchParams()
  searchParams.set('view', params.view)
  if (params.anchor) {
    searchParams.set('anchor', params.anchor)
  }
  return request<PerformanceCalendarResponse>(`/api/charts/performance-calendar?${searchParams.toString()}`)
}
