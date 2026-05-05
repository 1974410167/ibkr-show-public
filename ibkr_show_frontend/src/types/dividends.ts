import type { PaginationInfo } from './common'

export interface DividendItem {
  account_id: string
  currency: string | null
  symbol: string | null
  description: string | null
  date_time: string | null
  settle_date: string | null
  amount: number | null
  flow_type: string | null
  dividend_type: string | null
  transaction_id: string | null
  report_date: string | null
  ex_date: string | null
}

export interface DividendListResponse {
  items: DividendItem[]
  pagination: PaginationInfo
}

export interface DividendSummaryResponse {
  record_count: number
  dividend_count: number
  withholding_tax_count: number
  gross_dividend_amount: number | null
  withholding_tax_amount: number | null
  net_amount: number | null
  by_currency: DividendCurrencySummaryItem[]
}

export interface DividendCurrencySummaryItem {
  currency: string | null
  record_count: number
  dividend_count: number
  withholding_tax_count: number
  gross_dividend_amount: number
  withholding_tax_amount: number
  net_amount: number
}
