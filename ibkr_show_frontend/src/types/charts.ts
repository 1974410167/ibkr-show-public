export interface EquityCurvePoint {
  report_date: string
  total_equity: number | null
  total_pnl: number | null
  net_cost: number | null
  realized_pnl: number | null
  daily_mtm: number | null
  daily_twr: number | null
}

export interface EquityCurveResponse {
  items: EquityCurvePoint[]
}

export type PerformanceCalendarView = 'month' | 'year' | 'all-years'

export interface PerformanceCalendarItem {
  period_key: string
  label: string
  period_start: string
  period_end: string | null
  pnl: number | null
  twr: number | null
  has_data: boolean
}

export interface PerformanceCalendarSummary {
  positive_periods: number
  negative_periods: number
  total_pnl: number | null
  periods_with_data: number
}

export interface PerformanceCalendarResponse {
  view: PerformanceCalendarView
  anchor: string
  latest_anchor: string
  earliest_anchor: string | null
  previous_anchor: string | null
  next_anchor: string | null
  items: PerformanceCalendarItem[]
  summary: PerformanceCalendarSummary
}
