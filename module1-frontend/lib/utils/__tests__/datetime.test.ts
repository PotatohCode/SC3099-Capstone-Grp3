import { formatDateTime, formatShortDateParts, isWithinMonthRange, parseServerDate, sgParts } from '@/lib/utils/datetime'

describe('Singapore time formatting', () => {
  it('runs in a device timezone that is not Singapore', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/New_York')
    expect(new Date(2026, 9, 26).getTimezoneOffset()).not.toBe(-480)
  })

  it('shows a naive UTC backend time as Singapore time', () => {
    expect(formatShortDateParts('2026-10-26T02:00:00')).toEqual({ date: '26/10/26', time: '10:00' })
    expect(formatDateTime('2026-10-26T02:05:00')).toBe('26/10/2026, 10:05 SGT')
  })

  it('treats naive strings as UTC and keeps explicit zones', () => {
    expect(parseServerDate('2026-10-26T02:00:00').toISOString()).toBe('2026-10-26T02:00:00.000Z')
    expect(parseServerDate('2026-10-26T02:00:00.123456').getTime()).toBe(Date.UTC(2026, 9, 26, 2, 0, 0, 123))
    expect(parseServerDate('2026-10-26T02:00:00Z').toISOString()).toBe('2026-10-26T02:00:00.000Z')
    expect(parseServerDate('2026-10-26T10:00:00+08:00').toISOString()).toBe('2026-10-26T02:00:00.000Z')
    expect(parseServerDate('2026-10-26T10:00:00+0800').toISOString()).toBe('2026-10-26T02:00:00.000Z')
    expect(parseServerDate('2026-10-26T10:00:00+08').toISOString()).toBe('2026-10-26T02:00:00.000Z')
  })

  it('shows a placeholder instead of throwing for missing or malformed times', () => {
    expect(formatDateTime('')).toBe('-')
    expect(formatDateTime('not a date')).toBe('-')
    expect(formatShortDateParts(null as unknown as string)).toEqual({ date: '-', time: '' })
    expect(sgParts(undefined)).toBeNull()
    expect(isWithinMonthRange('garbage', '', '')).toBe(true)
    expect(isWithinMonthRange('garbage', '2026-10', '')).toBe(false)
  })

  it('rolls the date over at Singapore midnight, not UTC midnight', () => {
    expect(formatShortDateParts('2026-10-31T16:30:00')).toEqual({ date: '01/11/26', time: '00:30' })
    expect(sgParts('2026-12-31T16:00:00')).toMatchObject({ year: '2027', month: '01', day: '01', hour: '00' })
  })

  it('filters by Singapore month', () => {
    expect(isWithinMonthRange('2026-10-31T16:30:00', '2026-11', '')).toBe(true)
    expect(isWithinMonthRange('2026-10-31T16:30:00', '', '2026-10')).toBe(false)
    expect(isWithinMonthRange('2026-10-31T15:30:00', '2026-10', '2026-10')).toBe(true)
    expect(isWithinMonthRange('2026-10-31T15:30:00', '', '')).toBe(true)
  })
})
