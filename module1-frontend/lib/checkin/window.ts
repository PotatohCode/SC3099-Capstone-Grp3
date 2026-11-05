/** Decides whether a session can be checked into now: status active and inside its check-in window, same rule as the backend. */
import type { SessionSummary } from '@/lib/types'
import { formatDateTime, parseServerDate } from '@/lib/utils/datetime'

export type CheckInWindow =
  | { open: true }
  | { open: false; reason: 'not-active' | 'not-yet' | 'closed' | 'unknown'; message: string }

type WindowSession = Pick<SessionSummary, 'status' | 'checkin_opens_at' | 'checkin_closes_at'>

/** Returns open, or the reason a student can't start checking in, with a Singapore-time message. */
export function checkinWindow(session: WindowSession, nowMs: number): CheckInWindow {
  if (session.status !== 'active') {
    return { open: false, reason: 'not-active', message: 'This session is not open for check-in.' }
  }
  const opens = parseServerDate(session.checkin_opens_at).getTime()
  const closes = parseServerDate(session.checkin_closes_at).getTime()
  if (Number.isNaN(opens) || Number.isNaN(closes)) {
    return { open: false, reason: 'unknown', message: 'Check-in times are unavailable for this session.' }
  }
  // Inclusive bounds, like the backend
  if (nowMs < opens) {
    return { open: false, reason: 'not-yet', message: `Check-in opens at ${formatDateTime(session.checkin_opens_at!)}.` }
  }
  if (nowMs > closes) {
    return { open: false, reason: 'closed', message: `Check-in closed at ${formatDateTime(session.checkin_closes_at!)}.` }
  }
  return { open: true }
}
