import type { PaginationInfo } from './common'

export interface PositionItem {
  account_id: string
  report_date: string
  symbol: string | null
  description: string | null
  asset_class: string | null
  quantity: number | null
  mark_price: number | null
  position_value: number | null
  percent_of_nav: number | null
  average_cost_price: number | null
  cost_basis_money: number | null
  total_realized_pnl: number | null
  realized_pnl_percent: number | null
  total_unrealized_pnl: number | null
  unrealized_pnl_percent: number | null
  total_fifo_pnl: number | null
  previous_day_change_percent: number | null
}

export interface PositionListResponse {
  items: PositionItem[]
  pagination: PaginationInfo
  summary: PositionSummaryResponse | null
}

export interface PositionConcentrationItem {
  symbol: string | null
  description: string | null
  asset_class: string | null
  position_value: number
  percent_of_nav: number | null
}

export interface PositionAssetDistributionItem {
  asset_class: string | null
  position_value: number
  positions_count: number
}

export interface PositionSummaryResponse {
  report_date: string | null
  total_positions: number
  total_position_value: number
  total_cost_basis_money: number
  total_realized_pnl: number
  total_unrealized_pnl: number
  total_fifo_pnl: number
  top_positions: PositionConcentrationItem[]
  asset_distribution: PositionAssetDistributionItem[]
}

export interface PositionDetailBar {
  report_date: string
  open_price: number | null
  high_price: number | null
  low_price: number | null
  close_price: number | null
  quantity: number | null
}

export interface PositionDetailTradeMarker {
  trade_date: string | null
  date_time: string | null
  buy_sell: string | null
  quantity: number | null
  trade_price: number | null
  fifo_pnl_realized: number | null
}

export interface PositionDetailResponse {
  symbol: string | null
  description: string | null
  asset_class: string | null
  bars: PositionDetailBar[]
  trades: PositionDetailTradeMarker[]
}
