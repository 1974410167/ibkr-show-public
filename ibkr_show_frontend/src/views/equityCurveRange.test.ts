import { describe, expect, it } from 'vitest'

import { buildEquityCurveRangeParams } from '@/views/equityCurveRange'

describe('buildEquityCurveRangeParams', () => {
  it('defaults ytd to the first day of the report year', () => {
    expect(buildEquityCurveRangeParams('2026-04-29', 'ytd')).toEqual({
      start_date: '2026-01-01',
      end_date: '2026-04-29',
    })
  })

  it('returns no filter params for all history', () => {
    expect(buildEquityCurveRangeParams('2026-04-29', 'all')).toEqual({})
  })

  it('builds rolling month and year windows from the latest report date', () => {
    expect(buildEquityCurveRangeParams('2026-04-29', '1m')).toEqual({
      start_date: '2026-03-29',
      end_date: '2026-04-29',
    })
    expect(buildEquityCurveRangeParams('2026-04-29', '3m')).toEqual({
      start_date: '2026-01-29',
      end_date: '2026-04-29',
    })
    expect(buildEquityCurveRangeParams('2026-04-29', '1y')).toEqual({
      start_date: '2025-04-29',
      end_date: '2026-04-29',
    })
  })
})
