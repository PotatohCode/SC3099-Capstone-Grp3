/** Counts face-check attempts (one per Start) and decides after each one: submit, ask for another Start, or end the check and go to review. */
import { missedStepHint } from '@/lib/liveness/challenge'
import { parseApiError } from '@/lib/utils/api-error'
import type { VerifyChallengeResponse } from '@/lib/types'

export type Verification = 'passed' | 'review'

export const MAX_ATTEMPTS = 3
export const RETRY_MESSAGE = 'Unsuccessful capture, please retry.'

export type AttemptOutcome =
  | { kind: 'verified'; response: VerifyChallengeResponse }
  | { kind: 'verify-error'; error: unknown }
  | { kind: 'no-capture' }

export type AttemptDecision =
  | { kind: 'submit'; media: 'burst' | 'frame' | 'none'; verification: Verification; restartFreshness: boolean }
  | { kind: 'retry'; message: string; secondary: string }

const STORAGE_PREFIX = 'saiv_liveness_attempts:'
const memory = new Map<string, number>()

function readCount(key: string): number {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_PREFIX + key)
    if (stored !== null) return Number(stored) || 0
  } catch {
    return memory.get(key) ?? 0
  }
  return memory.get(key) ?? 0
}

function writeCount(key: string, value: number): void {
  memory.set(key, value)
  try {
    window.sessionStorage.setItem(STORAGE_PREFIX + key, String(value))
  } catch {
    return
  }
}

/** Returns how many Starts this student has used for the session in this tab (kept across reloads, cleared on logout). */
export function attemptsUsed(userId: string, sessionId: string): number {
  return readCount(`${userId}:${sessionId}`)
}

/** Records a Start for this student and session and returns its attempt number (1 for the first). */
export function startAttempt(userId: string, sessionId: string): number {
  const key = `${userId}:${sessionId}`
  const attempt = readCount(key) + 1
  writeCount(key, attempt)
  return attempt
}

/** Gives back a Start that never reached the liveness check (session closed, or the plain-photo fallback). */
export function undoAttempt(userId: string, sessionId: string): void {
  const key = `${userId}:${sessionId}`
  writeCount(key, Math.max(0, readCount(key) - 1))
}

/** Clears every attempt count; called on login and logout so another student on the same tab starts fresh. */
export function resetVerifyCalls(): void {
  memory.clear()
  try {
    const keys: string[] = []
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const key = window.sessionStorage.key(i)
      if (key?.startsWith(STORAGE_PREFIX)) keys.push(key)
    }
    keys.forEach((key) => window.sessionStorage.removeItem(key))
  } catch {
    return
  }
}

function triesLeft(n: number): string {
  return `${n} ${n === 1 ? 'try' : 'tries'} left.`
}

function endMedia(outcome: AttemptOutcome): { media: 'burst' | 'frame' | 'none'; restartFreshness: boolean } {
  if (outcome.kind === 'no-capture') return { media: 'none', restartFreshness: false }
  if (outcome.kind === 'verified') return { media: 'burst', restartFreshness: true }
  const e = parseApiError(outcome.error)
  const unusable = e.code === 'CHALLENGE_INVALID' || e.status === 409 || e.status === 413 || e.status === 422 || e.status === 429
  return { media: unusable ? 'frame' : 'burst', restartFreshness: false }
}

function serverHasNoTriesLeft(outcome: AttemptOutcome): boolean {
  if (outcome.kind === 'verified') return outcome.response.result === 'failed' && outcome.response.attempts_left === 0
  if (outcome.kind === 'verify-error') {
    const e = parseApiError(outcome.error)
    return e.code === 'LIVENESS_ATTEMPTS_EXHAUSTED' || e.status === 409
  }
  return false
}

/** Only a passed verify succeeds; any other outcome asks for another Start until the third attempt, then ends the check for review. */
export function decideAttempt(outcome: AttemptOutcome, attempt: number): AttemptDecision {
  if (outcome.kind === 'verified' && outcome.response.result === 'passed') {
    return { kind: 'submit', media: 'burst', verification: 'passed', restartFreshness: true }
  }
  if (attempt >= MAX_ATTEMPTS || serverHasNoTriesLeft(outcome)) {
    return { kind: 'submit', verification: 'review', ...endMedia(outcome) }
  }
  const hint = outcome.kind === 'verified' ? missedStepHint(outcome.response.failed_step) : null
  const left = triesLeft(MAX_ATTEMPTS - attempt)
  return { kind: 'retry', message: RETRY_MESSAGE, secondary: hint ? `${hint} ${left}` : left }
}
