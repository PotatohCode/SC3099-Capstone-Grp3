/** Remembers which session a student was checking in to, so they can pick up where they left off after leaving the page. */

const PREFIX = 'saiv_checkin_progress:'
export const PROGRESS_MAX_AGE_MS = 12 * 60 * 60 * 1000

interface StoredProgress {
  sessionId: string
  savedAt: number
}

/** Saves the session the student is part-way through checking in to. */
export function saveProgress(userId: string | null | undefined, sessionId: string, now: number = Date.now()): void {
  if (!userId) return
  try {
    const value: StoredProgress = { sessionId, savedAt: now }
    window.localStorage.setItem(PREFIX + userId, JSON.stringify(value))
  } catch {
    return
  }
}

/** Returns the session id to resume for this student, or null when there is none or it is older than 12 hours. */
export function readProgress(userId: string | null | undefined, now: number = Date.now()): string | null {
  if (!userId) return null
  try {
    const raw = window.localStorage.getItem(PREFIX + userId)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<StoredProgress>
    if (typeof value.sessionId !== 'string' || typeof value.savedAt !== 'number') return null
    if (now - value.savedAt > PROGRESS_MAX_AGE_MS) return null
    return value.sessionId
  } catch {
    return null
  }
}

/** Forgets any saved progress for this student. */
export function clearProgress(userId: string | null | undefined): void {
  if (!userId) return
  try {
    window.localStorage.removeItem(PREFIX + userId)
  } catch {
    return
  }
}
