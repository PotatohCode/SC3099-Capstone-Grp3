/** Maps check-in and challenge API errors (status + code) to the message and recovery action shown to the student. */
import { PayloadTooLargeError } from '@/lib/checkin/payload'
import { parseApiError } from '@/lib/utils/api-error'

export type CheckInErrorAction = 'retry-capture' | 'retry-location' | 'reselect-session' | 'view-history' | 'queue-offline'

export interface CheckInErrorView {
  title?: string
  message: string
  secondary?: string
  action: CheckInErrorAction
  alternateAction?: CheckInErrorAction
  challengeInvalid?: boolean
}

export const CHALLENGE_EXPIRED_MESSAGE = "That check took too long. Let's try again."

export const ALREADY_CHECKED_IN_VIEW: CheckInErrorView = {
  title: 'Already checked in',
  message: "You've already checked in to this session. You can view it, or appeal it, in your history.",
  action: 'view-history',
  alternateAction: 'reselect-session',
}

export const QUEUED_CHECKIN_VIEW: CheckInErrorView = {
  title: 'Check-in waiting to sync',
  message: "Your check-in for this session is saved on this device and will be sent automatically when you're back online.",
  action: 'reselect-session',
}

const SESSION_ERRORS: Record<string, string> = {
  SESSION_NOT_FOUND: 'This session no longer exists. Please choose another session.',
  NOT_ENROLLED: "You're not enrolled in this course.",
  SESSION_NOT_ACTIVE: 'Check-in for this session is closed.',
  SESSION_WINDOW_CLOSED: 'Check-in for this session is closed.',
}

function waitMessage(prefix: string, seconds: number | null): string {
  return seconds ? `${prefix} Please wait ${seconds} seconds and try again.` : `${prefix} Please wait a minute and try again.`
}

/** Classifies an error from POST /checkins/; isOnline decides whether a missing response means queue offline. */
export function classifyCheckInError(error: unknown, isOnline: boolean): CheckInErrorView {
  if (error instanceof PayloadTooLargeError) {
    return { message: 'Photo too large, please retake.', action: 'retry-capture' }
  }
  const e = parseApiError(error)
  if (e.isNetwork) {
    return isOnline
      ? { message: "We couldn't reach the server. Check your connection and try again.", action: 'retry-capture' }
      : { message: "You're offline. Your check-in will be sent when you're back online.", action: 'queue-offline' }
  }
  if (e.code === 'OUTSIDE_SINGAPORE') {
    return {
      title: 'Check-in not available here',
      message: "Check-in is only available within Singapore. If you're using a VPN, turn it off and try again.",
      secondary: 'Nothing was saved, so you can try again.',
      action: 'retry-location',
      alternateAction: 'retry-capture',
    }
  }
  if (e.code === 'CHALLENGE_INVALID') {
    return { message: CHALLENGE_EXPIRED_MESSAGE, action: 'retry-capture', challengeInvalid: true }
  }
  if (e.code && SESSION_ERRORS[e.code]) return { message: SESSION_ERRORS[e.code], action: 'reselect-session' }
  if (e.code === 'ALREADY_CHECKED_IN') return { ...ALREADY_CHECKED_IN_VIEW }
  if (e.code === 'CONSENT_REQUIRED') {
    return {
      message: 'Camera and location permission are needed to check in. Please allow both and try again.',
      action: 'retry-location',
    }
  }
  if (e.status === 429) return { message: waitMessage('Too many check-in attempts.', e.retryAfterSeconds), action: 'retry-capture' }
  if (e.code === 'TOO_MANY_FRAMES') {
    return { message: 'Something went wrong with the face check. Please try again.', action: 'retry-capture' }
  }
  if (e.status === 413) return { message: 'Photo too large, please retake.', action: 'retry-capture' }
  if (e.status === 422) return { message: 'Some check-in details were invalid. Please try again.', action: 'retry-location' }
  if (e.status !== null && e.status >= 500) return { message: 'The server had a problem. Please try again.', action: 'retry-capture' }
  return { message: e.detail ?? 'Check-in failed. Please try again.', action: 'retry-capture' }
}

export type ChallengeErrorResult =
  | { fallbackToPhoto: true; attemptsExhausted?: boolean }
  | { fallbackToPhoto: false; view: CheckInErrorView }

/** Classifies an error from POST /checkins/challenge; 503 or no response fall back to a single photo, and no liveness attempts left ends the check. */
export function classifyChallengeError(error: unknown): ChallengeErrorResult {
  const e = parseApiError(error)
  if (e.isNetwork || e.status === 503) return { fallbackToPhoto: true }
  if (e.code === 'LIVENESS_ATTEMPTS_EXHAUSTED') return { fallbackToPhoto: true, attemptsExhausted: true }
  if (e.code && SESSION_ERRORS[e.code]) {
    return { fallbackToPhoto: false, view: { message: SESSION_ERRORS[e.code], action: 'reselect-session' } }
  }
  if (e.status === 429) {
    return { fallbackToPhoto: false, view: { message: waitMessage('Too many attempts.', e.retryAfterSeconds), action: 'retry-capture' } }
  }
  return { fallbackToPhoto: false, view: { message: "We couldn't start the face check. Please try again.", action: 'retry-capture' } }
}
