export type EquityCurveRangeKey = 'ytd' | 'all' | '1y' | '6m' | '3m' | '1m'

export type EquityCurveRangeOption = {
  key: EquityCurveRangeKey
  label: string
}

export const EQUITY_CURVE_RANGE_OPTIONS: EquityCurveRangeOption[] = [
  { key: 'ytd', label: '本年迄今' },
  { key: 'all', label: '全部' },
  { key: '1y', label: '最近一年' },
  { key: '6m', label: '6个月' },
  { key: '3m', label: '3个月' },
  { key: '1m', label: '1个月' },
]

export function buildEquityCurveRangeParams(
  reportDate: string | null | undefined,
  range: EquityCurveRangeKey,
): {
  start_date?: string
  end_date?: string
} {
  if (!reportDate || range === 'all') {
    return {}
  }

  if (range === 'ytd') {
    const year = reportDate.slice(0, 4)
    return {
      start_date: `${year}-01-01`,
      end_date: reportDate,
    }
  }

  const parsed = new Date(`${reportDate}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) {
    return {}
  }

  const start = new Date(parsed)
  if (range === '1y') {
    start.setUTCFullYear(start.getUTCFullYear() - 1)
  } else if (range === '6m') {
    start.setUTCMonth(start.getUTCMonth() - 6)
  } else if (range === '3m') {
    start.setUTCMonth(start.getUTCMonth() - 3)
  } else if (range === '1m') {
    start.setUTCMonth(start.getUTCMonth() - 1)
  }

  return {
    start_date: formatDate(start),
    end_date: reportDate,
  }
}

function formatDate(value: Date): string {
  const year = value.getUTCFullYear()
  const month = String(value.getUTCMonth() + 1).padStart(2, '0')
  const day = String(value.getUTCDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
