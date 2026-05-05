import { describe, expect, it } from 'vitest'

import type { AccountOverview } from '@/types/account'
import { buildDashboardStatCards } from '@/views/dashboardMetrics'

const baseOverview: AccountOverview = {
  account_id: 'U1',
  report_date: '2026-04-29',
  currency: 'USD',
  total_equity: 71040.8236651,
  cash: 8579.6636651,
  stock_value: 62461.16,
  options_value: 0,
  funds_value: 0,
  crypto_value: 0,
  interest_accruals: 0,
  dividend_accruals: 0,
  margin_financing_charge_accruals: 0,
  fifo_total_realized_pnl: 9579.122878,
  fifo_total_unrealized_pnl: 11361.385797,
  fifo_total_pnl: 20940.508675,
  cnav_twr: 0.887068806,
  ytd_twr: 7.65904119545,
  crtt_dividends_ytd: 89.46,
  crtt_broker_interest_ytd: -0.83,
  crtt_commissions_ytd: -12.9599797,
  total_equity_delta: {
    amount_change: 624.639999994004,
    percent_change: 0.887068806461799,
  },
  fifo_total_realized_pnl_delta: {
    amount_change: 0,
    percent_change: 0,
  },
  fifo_total_unrealized_pnl_delta: {
    amount_change: 624.6400000000012,
    percent_change: 5.817777675005909,
  },
  fifo_total_pnl_delta: {
    amount_change: 624.640000000003,
    percent_change: 3.0746408632216813,
  },
}

describe('buildDashboardStatCards', () => {
  it('omits realized and unrealized pnl deltas but keeps total pnl delta', () => {
    const cards = buildDashboardStatCards(baseOverview)

    const realized = cards.find((card) => card.title === '已实现盈亏')
    const unrealized = cards.find((card) => card.title === '未实现盈亏')
    const totalPnl = cards.find((card) => card.title === '总盈亏')

    expect(realized?.deltaAmount).toBeUndefined()
    expect(realized?.deltaPercent).toBeUndefined()
    expect(unrealized?.deltaAmount).toBeUndefined()
    expect(unrealized?.deltaPercent).toBeUndefined()
    expect(totalPnl?.deltaAmount).toBe('+624.64')
    expect(totalPnl?.deltaPercent).toBe('+3.07%')
  })

  it('formats overview summary fields and helpers consistently', () => {
    const cards = buildDashboardStatCards(baseOverview)

    expect(cards.find((card) => card.title === '当日TWR')).toMatchObject({
      value: '0.89%',
      helper: 'IBKR CNAV 单日收益率',
      tone: 'positive',
    })
    expect(cards.find((card) => card.title === '年初至今TWR')).toMatchObject({
      value: '7.66%',
      helper: '2026-01-01 至今',
      tone: 'positive',
    })
    expect(cards.find((card) => card.title === '年内分红')?.value).toBe('89.46')
    expect(cards.find((card) => card.title === '年内佣金')?.value).toBe('-12.96')
  })
})
