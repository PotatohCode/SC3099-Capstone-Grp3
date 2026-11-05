import { checkinWindow } from '../window'

const opens = '2026-11-05T09:45:00'
const closes = '2026-11-05T10:30:00'
const at = (iso: string) => Date.parse(`${iso}Z`)
const active = { status: 'active' as const, checkin_opens_at: opens, checkin_closes_at: closes }

describe('checkinWindow', () => {
  it('blocks before the window opens and names the opening time in SGT', () => {
    expect(checkinWindow(active, at('2026-11-05T09:44:59'))).toEqual({
      open: false,
      reason: 'not-yet',
      message: 'Check-in opens at 05/11/2026, 17:45 SGT.',
    })
  })

  it('opens exactly at checkin_opens_at', () => {
    expect(checkinWindow(active, at(opens))).toEqual({ open: true })
  })

  it('is open inside the window', () => {
    expect(checkinWindow(active, at('2026-11-05T10:00:00'))).toEqual({ open: true })
  })

  it('is still open exactly at checkin_closes_at', () => {
    expect(checkinWindow(active, at(closes))).toEqual({ open: true })
  })

  it('blocks after the window closes and names the closing time in SGT', () => {
    expect(checkinWindow(active, at('2026-11-05T10:30:01'))).toEqual({
      open: false,
      reason: 'closed',
      message: 'Check-in closed at 05/11/2026, 18:30 SGT.',
    })
  })

  it.each(['scheduled', 'closed', 'cancelled'] as const)('blocks a %s session even inside the window', (status) => {
    expect(checkinWindow({ ...active, status }, at('2026-11-05T10:00:00'))).toMatchObject({ open: false, reason: 'not-active' })
  })

  it.each([
    ['missing opens', { checkin_opens_at: undefined }],
    ['missing closes', { checkin_closes_at: undefined }],
    ['unparseable opens', { checkin_opens_at: 'soon' }],
  ])('fails closed when times are %s', (_label, patch) => {
    expect(checkinWindow({ ...active, ...patch }, at('2026-11-05T10:00:00'))).toMatchObject({ open: false, reason: 'unknown' })
  })

  it('accepts timestamps that already carry a zone', () => {
    const zoned = { ...active, checkin_opens_at: '2026-11-05T17:45:00+08:00', checkin_closes_at: '2026-11-05T10:30:00Z' }
    expect(checkinWindow(zoned, at('2026-11-05T09:45:00'))).toEqual({ open: true })
  })
})
