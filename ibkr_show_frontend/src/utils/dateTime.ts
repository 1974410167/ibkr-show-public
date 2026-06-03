/**
 * Format an ISO-8601 timestamp string into the browser's local timezone.
 *
 * Parsing rules:
 * - Empty / null / undefined → '-'
 * - Strings ending in 'Z' or containing an offset (+HH:MM / -HH:MM) are
 *   parsed directly by the Date constructor.
 * - Bare datetime strings like "2026-05-30T20:30:08" or "2026-05-30 20:30:08"
 *   are treated as UTC to avoid browser-dependent local-time interpretation.
 */

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`
}

function hasTimezone(s: string): boolean {
  return /[Zz]|[+-]\d{2}:\d{2}$/.test(s)
}

function normalizeBareDatetime(s: string): string {
  // "2026-05-30 20:30:08" → "2026-05-30T20:30:08Z"
  const trimmed = s.trim().replace(' ', 'T')
  return hasTimezone(trimmed) ? trimmed : `${trimmed}Z`
}

export interface FormatDateTimeOptions {
  showTimezone?: boolean
  /** Override the IANA timezone used for display (default: browser local). */
  timeZone?: string
}

export function formatLocalDateTime(
  value?: string | null,
  options?: FormatDateTimeOptions,
): string {
  if (!value) return '-'

  const date = new Date(normalizeBareDatetime(value))
  if (Number.isNaN(date.getTime())) return '-'

  const tz = options?.timeZone ?? undefined // undefined → browser local
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((acc, p) => {
      acc[p.type] = p.value
      return acc
    }, {})

  let result = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`

  if (options?.showTimezone) {
    const tzName = new Intl.DateTimeFormat('en', {
      timeZone: tz,
      timeZoneName: 'shortOffset',
    })
      .formatToParts(date)
      .find((p) => p.type === 'timeZoneName')?.value
    if (tzName) result += ` ${tzName}`
  }

  return result
}

/** Format only the date portion (YYYY-MM-DD). */
export function formatLocalDate(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(normalizeBareDatetime(value))
  if (Number.isNaN(date.getTime())) return '-'
  const y = date.getFullYear()
  const m = pad2(date.getMonth() + 1)
  const d = pad2(date.getDate())
  return `${y}-${m}-${d}`
}
