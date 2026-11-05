import { checkinClosed, missedDate, missedSessions } from '../missed'
import type { SessionSummary } from '@/lib/types'

const NOW = Date.parse('2026-11-05T10:00:00Z')
const s = (id: string, patch: Partial<SessionSummary> = {}): SessionSummary => ({
  id,
  course_id: 'c1',
  name: id,
  status: 'active',
  scheduled_start: '2026-11-05T08:00:00',
  scheduled_end: '2026-11-05T09:00:00',
  checkin_opens_at: '2026-11-05T07:45:00',
  checkin_closes_at: '2026-11-05T08:30:00',
  ...patch,
})

describe('checkinClosed', () => {
  it('is closed once the window has passed, even while still active', () => {
    expect(checkinClosed(s('a'), NOW)).toBe(true)
  })
  it('is closed when the instructor closed it early', () => {
    expect(checkinClosed(s('a', { status: 'closed', checkin_closes_at: '2026-11-05T11:00:00' }), NOW)).toBe(true)
  })
  it('is not closed while the window is open or for cancelled sessions', () => {
    expect(checkinClosed(s('a', { checkin_closes_at: '2026-11-05T10:00:00' }), NOW)).toBe(false)
    expect(checkinClosed(s('a', { status: 'cancelled' }), NOW)).toBe(false)
  })
  it('is not closed when times are missing on an active session', () => {
    expect(checkinClosed(s('a', { checkin_closes_at: undefined }), NOW)).toBe(false)
  })
  it('is not missable when closed before check-in ever opened', () => {
    expect(checkinClosed(s('a', { status: 'closed', checkin_opens_at: '2026-11-06T07:45:00' }), NOW)).toBe(false)
  })
})

describe('missedSessions', () => {
  it('lists closed sessions with no check-in and skips attended, open, cancelled and pre-enrollment ones', () => {
    const sessions = [
      s('missed'),
      s('attended'),
      s('open', { checkin_closes_at: '2026-11-05T12:00:00' }),
      s('cancelled', { status: 'cancelled' }),
      s('before-enrol', { scheduled_start: '2026-10-01T08:00:00', checkin_closes_at: '2026-10-01T08:30:00' }),
      s('closed-early', { status: 'closed', checkin_closes_at: '2026-11-05T12:00:00' }),
      s('other-course', { course_id: 'c2' }),
    ]
    const enrol = [{ course_id: 'c1', enrolled_at: '2026-10-15T00:00:00' }, { course_id: 'c2' }]
    const got = missedSessions(sessions, [{ session_id: 'attended', checked_in_at: '2026-11-05T08:05:00' }], enrol, NOW)
    expect(got.map((x) => x.id)).toEqual(['missed', 'closed-early', 'other-course'])
  })

  it('counts a session as missed when the enrollment date is unknown', () => {
    expect(missedSessions([s('a')], [], [{ course_id: 'c1' }], NOW).map((x) => x.id)).toEqual(['a'])
  })

  it('shows nothing when enrollments could not be loaded', () => {
    expect(missedSessions([s('a')], [], null, NOW)).toEqual([])
  })

  it('skips sessions of courses the student is not enrolled in', () => {
    expect(missedSessions([s('a', { course_id: 'gone' })], [], [{ course_id: 'c1' }], NOW)).toEqual([])
  })

  it('when the check-in list was capped, skips sessions older than the oldest fetched check-in', () => {
    const sessions = [s('old', { scheduled_start: '2026-10-01T08:00:00', checkin_opens_at: '2026-10-01T07:45:00', checkin_closes_at: '2026-10-01T08:30:00' }), s('recent')]
    const checkins = [{ session_id: 'x', checked_in_at: '2026-10-20T08:00:00' }]
    expect(missedSessions(sessions, checkins, [{ course_id: 'c1' }], NOW, true).map((x) => x.id)).toEqual(['recent'])
    expect(missedSessions(sessions, checkins, [{ course_id: 'c1' }], NOW, false).map((x) => x.id)).toEqual(['old', 'recent'])
  })

  it('dates a row by scheduled start, falling back to the check-in close time, and drops undatable ones', () => {
    expect(missedDate(s('a'))).toBe('2026-11-05T08:00:00')
    expect(missedDate(s('a', { scheduled_start: '' }))).toBe('2026-11-05T08:30:00')
    expect(missedSessions([s('a', { scheduled_start: '', checkin_closes_at: 'bad' , status: 'closed' })], [], [{ course_id: 'c1' }], NOW)).toEqual([])
  })
})
