/** Finds sessions whose check-in has closed that the student never checked in to, for History's Missed rows. */
import type { CheckInHistoryItem, SessionSummary } from '@/lib/types'
import { parseServerDate } from '@/lib/utils/datetime'

type Enrollment = { course_id: string; enrolled_at?: string }

const time = (iso: string | null | undefined) => parseServerDate(iso).getTime()

/** True once check-in is over: the window opened and has since passed, or the instructor closed it after it opened. */
export function checkinClosed(session: SessionSummary, nowMs: number): boolean {
  if (session.status === 'cancelled') return false
  const opens = time(session.checkin_opens_at)
  // Closed before it ever opened is not missable
  if (Number.isNaN(opens) || opens > nowMs) return false
  if (session.status === 'closed') return true
  const closes = time(session.checkin_closes_at)
  return !Number.isNaN(closes) && nowMs > closes
}

/** Date a Missed row is listed under: scheduled start, else the check-in close time. */
export function missedDate(session: SessionSummary): string {
  return Number.isNaN(time(session.scheduled_start)) ? session.checkin_closes_at ?? '' : session.scheduled_start
}

/** Closed sessions with no check-in; errs toward "not missed" when enrollments are unknown or the check-in list was capped. */
export function missedSessions(
  sessions: SessionSummary[],
  checkins: Pick<CheckInHistoryItem, 'session_id' | 'checked_in_at'>[],
  enrollments: Enrollment[] | null,
  nowMs: number,
  checkinsCapped = false
): SessionSummary[] {
  if (!enrollments) return []
  const attended = new Set(checkins.map((c) => c.session_id))
  const enrolledAt = new Map(enrollments.map((e) => [e.course_id, time(e.enrolled_at)]))
  const oldestCheckin = checkinsCapped ? Math.min(...checkins.map((c) => time(c.checked_in_at)).filter((t) => !Number.isNaN(t))) : -Infinity
  return sessions.filter((session) => {
    if (attended.has(session.id) || !checkinClosed(session, nowMs) || !enrolledAt.has(session.course_id)) return false
    const at = time(missedDate(session))
    if (Number.isNaN(at) || at < oldestCheckin) return false
    const since = enrolledAt.get(session.course_id)!
    // Not missed if not yet enrolled
    return Number.isNaN(since) || at >= since
  })
}
