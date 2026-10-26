/** Finds sessions the student already has a check-in for, either on the server or waiting in the offline queue. */
import { getMyCheckIns } from '@/lib/services/checkin.service'
import { getQueuedCheckIns, type QueuedCheckIn } from '@/lib/services/offline.service'
import type { CheckInHistoryItem } from '@/lib/types'

export const MY_CHECKINS_LIMIT = 100
export const PRECHECK_TIMEOUT_MS = 5000

export interface CheckedInSessions {
  submitted: Set<string>
  queued: Set<string>
}

/** Splits session ids into those in the check-in history and those only in this student's offline queue. */
export function checkedInSessions(
  history: Pick<CheckInHistoryItem, 'session_id'>[],
  queued: Pick<QueuedCheckIn, 'userId' | 'payload'>[],
  userId: string | null | undefined
): CheckedInSessions {
  const submitted = new Set(history.map((item) => item.session_id))
  const pending = new Set<string>()
  for (const item of queued) {
    if (userId && item.userId === userId && !submitted.has(item.payload.session_id)) pending.add(item.payload.session_id)
  }
  return { submitted, queued: pending }
}

/** True when the session has a submitted or queued check-in. */
export function hasCheckIn(sessions: CheckedInSessions, sessionId: string): boolean {
  return sessions.submitted.has(sessionId) || sessions.queued.has(sessionId)
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

/** Loads the student's checked-in sessions; rejects if the history can't be fetched in time, while a broken offline queue counts as empty. */
export async function loadCheckedInSessions(
  userId: string | null | undefined,
  options: { courseId?: string; timeoutMs?: number } = {}
): Promise<CheckedInSessions> {
  const params = options.courseId ? { course_id: options.courseId, limit: MY_CHECKINS_LIMIT } : { limit: MY_CHECKINS_LIMIT }
  const [history, queued] = await withTimeout(
    Promise.all([getMyCheckIns(params), getQueuedCheckIns().catch(() => [] as QueuedCheckIn[])]),
    options.timeoutMs
  )
  return checkedInSessions(history, queued, userId)
}
