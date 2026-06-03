import { describe, it, expect } from 'vitest'
import { formatLocalDateTime } from './dateTime'

describe('formatLocalDateTime', () => {
  it('returns "-" for empty / null / undefined', () => {
    expect(formatLocalDateTime(null)).toBe('-')
    expect(formatLocalDateTime(undefined)).toBe('-')
    expect(formatLocalDateTime('')).toBe('-')
  })

  it('returns "-" for unparseable strings', () => {
    expect(formatLocalDateTime('not-a-date')).toBe('-')
    expect(formatLocalDateTime('abcdef')).toBe('-')
  })

  it('parses UTC Z-suffix string and formats in a fixed timezone', () => {
    // 2026-05-30T20:30:08Z → Asia/Shanghai is +8 → 2026-05-31 04:30:08
    const result = formatLocalDateTime('2026-05-30T20:30:08Z', { timeZone: 'Asia/Shanghai' })
    expect(result).toBe('2026-05-31 04:30:08')
  })

  it('parses UTC offset string correctly', () => {
    const result = formatLocalDateTime('2026-05-30T20:30:08+00:00', { timeZone: 'Asia/Shanghai' })
    expect(result).toBe('2026-05-31 04:30:08')
  })

  it('treats bare datetime (no timezone) as UTC', () => {
    // "2026-05-30T20:30:08" without Z → should be treated as UTC
    const result = formatLocalDateTime('2026-05-30T20:30:08', { timeZone: 'Asia/Shanghai' })
    expect(result).toBe('2026-05-31 04:30:08')
  })

  it('treats space-separated bare datetime as UTC', () => {
    const result = formatLocalDateTime('2026-05-30 20:30:08', { timeZone: 'Asia/Shanghai' })
    expect(result).toBe('2026-05-31 04:30:08')
  })

  it('appends timezone offset when showTimezone is true', () => {
    const result = formatLocalDateTime('2026-05-30T20:30:08Z', {
      timeZone: 'Asia/Shanghai',
      showTimezone: true,
    })
    expect(result).toMatch(/^2026-05-31 04:30:08 GMT\+8$/)
  })

  it('formats correctly in UTC timezone', () => {
    const result = formatLocalDateTime('2026-05-30T20:30:08Z', { timeZone: 'UTC' })
    expect(result).toBe('2026-05-30 20:30:08')
  })

  it('pads single-digit values', () => {
    const result = formatLocalDateTime('2026-01-05T03:05:09Z', { timeZone: 'UTC' })
    expect(result).toBe('2026-01-05 03:05:09')
  })
})
