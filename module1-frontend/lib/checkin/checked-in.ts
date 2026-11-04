/** Finds sessions the student already has a check-in for on the server. */
import { getMyCheckIns } from '@/lib/services/checkin.service'
import type { CheckInHistoryItem } from '@/lib/types'

export const MY_CHECKINS_LIMIT = 100
export const PRECHECK_TIMEOUT_MS = 5000

export interface CheckedInSessions {
  submitted: Set<string>
}

/** Collects the session ids found in the student's check-in history. */
export function checkedInSessions(history: Pick<CheckInHistoryItem, 'session_id'>[]): CheckedInSessions {
  return { submitted: new Set(history.map((item) => item.session_id)) }
}

/** True when the session already has a submitted check-in. */
export function hasCheckIn(sessions: CheckedInSessions, sessionId: string): boolean {
  return sessions.submitted.has(sessionId)
}

function withTimeout<T>(promise: Promise<T>, ms: number | undefined): Promise<T> {
  if (!ms) return promise
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('TIMEOUT')), ms)
    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (error) => {
        clearTimeout(timer)
        reject(error)
      }
    )
  })
}

/** Loads the student's checked-in sessions; rejects if the history can't be fetched in time. */
export async function loadCheckedInSessions(options: { courseId?: string; timeoutMs?: number } = {}): Promise<CheckedInSessions> {
  const params = options.courseId ? { course_id: options.courseId, limit: MY_CHECKINS_LIMIT } : { limit: MY_CHECKINS_LIMIT }
  return checkedInSessions(await withTimeout(getMyCheckIns(params), options.timeoutMs))
}
