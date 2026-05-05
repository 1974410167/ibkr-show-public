import type { AccountDeltaMetric, AccountOverview } from '@/types/account'

export interface DashboardStatCard {
  title: string
  value: string
  helper?: string
  icon: string
  tone: 'neutral' | 'positive' | 'negative' | 'accent'
  deltaAmount?: string
  deltaPercent?: string
  deltaTone?: 'neutral' | 'positive' | 'negative' | 'accent'
}

export function formatMetricNumber(value: number | null, digits = 2): string {
  if (value === null) {
    return '--'
  }

  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

function formatMetricPercent(value: number | null): string {
  if (value === null) {
    return '--'
  }
  return `${formatMetricNumber(value, 2)}%`
}

function formatSignedMetricNumber(value: number | null, digits = 2): string {
  if (value === null) {
    return ''
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${formatMetricNumber(value, digits)}`
}

function formatSignedMetricPercent(value: number | null): string {
  if (value === null) {
    return ''
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${formatMetricNumber(value, 2)}%`
}

function deltaTone(metric: AccountDeltaMetric | null): 'neutral' | 'positive' | 'negative' | 'accent' {
  if (!metric || !metric.amount_change) {
    return 'neutral'
  }
  return metric.amount_change > 0 ? 'positive' : 'negative'
}

function metricTone(
  value: number | null,
  fallback: 'neutral' | 'accent' = 'neutral',
): 'neutral' | 'positive' | 'negative' | 'accent' {
  if (value === null || value === 0) {
    return fallback
  }
  return value > 0 ? 'positive' : 'negative'
}

export function buildDashboardStatCards(overview: AccountOverview): DashboardStatCard[] {
  return [
    {
      title: '总权益',
      value: formatMetricNumber(overview.total_equity),
      helper: overview.report_date,
      icon: 'pi pi-wallet',
      tone: 'accent',
      deltaAmount: formatSignedMetricNumber(overview.total_equity_delta?.amount_change ?? null),
      deltaPercent: formatSignedMetricPercent(overview.total_equity_delta?.percent_change ?? null),
      deltaTone: deltaTone(overview.total_equity_delta),
    },
    { title: '现金', value: formatMetricNumber(overview.cash), icon: 'pi pi-dollar', tone: 'neutral' },
    { title: '股票市值', value: formatMetricNumber(overview.stock_value), icon: 'pi pi-chart-bar', tone: 'neutral' },
    {
      title: '已实现盈亏',
      value: formatMetricNumber(overview.fifo_total_realized_pnl),
      icon: 'pi pi-check-circle',
      tone: overview.fifo_total_realized_pnl !== null && overview.fifo_total_realized_pnl < 0 ? 'negative' : 'positive',
    },
    {
      title: '未实现盈亏',
      value: formatMetricNumber(overview.fifo_total_unrealized_pnl),
      icon: 'pi pi-bolt',
      tone:
        overview.fifo_total_unrealized_pnl !== null && overview.fifo_total_unrealized_pnl < 0
          ? 'negative'
          : 'positive',
    },
    {
      title: '总盈亏',
      value: formatMetricNumber(overview.fifo_total_pnl),
      icon: 'pi pi-chart-line',
      tone: overview.fifo_total_pnl !== null && overview.fifo_total_pnl < 0 ? 'negative' : 'positive',
      deltaAmount: formatSignedMetricNumber(overview.fifo_total_pnl_delta?.amount_change ?? null),
      deltaPercent: formatSignedMetricPercent(overview.fifo_total_pnl_delta?.percent_change ?? null),
      deltaTone: deltaTone(overview.fifo_total_pnl_delta),
    },
    {
      title: '当日TWR',
      value: formatMetricPercent(overview.cnav_twr),
      helper: 'IBKR CNAV 单日收益率',
      icon: 'pi pi-percentage',
      tone: metricTone(overview.cnav_twr, 'accent'),
    },
    {
      title: '年初至今TWR',
      value: formatMetricPercent(overview.ytd_twr),
      helper: `${overview.report_date.slice(0, 4)}-01-01 至今`,
      icon: 'pi pi-calendar',
      tone: metricTone(overview.ytd_twr, 'accent'),
    },
    { title: '年内分红', value: formatMetricNumber(overview.crtt_dividends_ytd), icon: 'pi pi-briefcase', tone: 'neutral' },
    { title: '年内利息', value: formatMetricNumber(overview.crtt_broker_interest_ytd), icon: 'pi pi-chart-line', tone: 'neutral' },
    { title: '年内佣金', value: formatMetricNumber(overview.crtt_commissions_ytd), icon: 'pi pi-minus-circle', tone: 'negative' },
  ]
}
