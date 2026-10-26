/** Parses backend timestamps (naive UTC) and formats them in Singapore time (UTC+8) whatever the device timezone. */

export const APP_TIME_ZONE = 'Asia/Singapore'
export const APP_TIME_ZONE_LABEL = 'SGT'

const HAS_ZONE = /(Z|[+-]\d{2}(:?\d{2})?)$/i
const INVALID = '-'

/** Parses an ISO timestamp, treating one without a zone suffix as UTC as the backend sends it. */
export function parseServerDate(iso: string | null | undefined): Date {
  const trimmed = (iso ?? '').trim()
  if (!trimmed) return new Date(NaN)
  if (!HAS_ZONE.test(trimmed)) return new Date(`${trimmed}Z`)
  return new Date(trimmed.replace(/([+-]\d{2})$/, '$1:00'))
}

export interface ZonedParts {
  year: string
  month: string
  day: string
  hour: string
  minute: string
}

const partsFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** Returns zero-padded Singapore calendar and clock parts for a backend timestamp, or null when it can't be parsed. */
export function sgParts(iso: string | null | undefined): ZonedParts | null {
  const date = parseServerDate(iso)
  if (Number.isNaN(date.getTime())) return null
  const parts = partsFormatter.formatToParts(date)
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute') }
}

/** dd/mm/yy and HH:MM (24h) in Singapore time, returned separately so they can render on two lines. */
export function formatShortDateParts(iso: string): { date: string; time: string } {
  const p = sgParts(iso)
  if (!p) return { date: INVALID, time: '' }
  return { date: `${p.day}/${p.month}/${p.year.slice(-2)}`, time: `${p.hour}:${p.minute}` }
}

/** Full date and 24h time in Singapore time, e.g. "26/10/2026, 10:05 SGT". */
export function formatDateTime(iso: string): string {
  const p = sgParts(iso)
  if (!p) return INVALID
  return `${p.day}/${p.month}/${p.year}, ${p.hour}:${p.minute} ${APP_TIME_ZONE_LABEL}`
}

/** True when the Singapore month of iso lies within the inclusive 'YYYY-MM' range; empty bounds are open. */
export function isWithinMonthRange(iso: string, from: string, to: string): boolean {
  const p = sgParts(iso)
  if (!p) return !from && !to
  const month = `${p.year}-${p.month}`
  if (from && month < from) return false
  if (to && month > to) return false
  return true
}
