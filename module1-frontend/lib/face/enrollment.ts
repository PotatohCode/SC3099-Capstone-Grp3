/** Face identity rules and messages: who must enroll before checking in, the capture length, and error wording. */
import { loginErrorMessage, minutesFromRetryAfter, parseApiError } from '@/lib/utils/api-error'
import type { User } from '@/lib/types'

export const FACE_CAPTURE_MS = 5000
export const FACE_PROMPT_DISMISSED_KEY = 'saiv_face_prompt_dismissed'
export const FACE_RESET_WINDOW_MS = 5 * 60 * 1000
export const RESET_CODE_INVALID_MESSAGE =
  'That reset code is wrong, expired or already used. Check it with your instructor, or ask them for a new one.'
export const RESET_CODE_REQUIRED_MESSAGE =
  'Your face is already registered, so you need a reset code from your instructor to replace it.'
export const RESET_WINDOW_EXPIRED_MESSAGE =
  "Time's up. Your photo wasn't sent. Enter the reset code again to start a new 5-minute window."

/** Uppercases a typed reset code and drops spaces and hyphens, as the backend does. */
export function normalizeResetCode(code: string): string {
  return code.toUpperCase().replace(/[\s-]/g, '')
}

/** Formats milliseconds left as m:ss, never below 0:00. */
export function formatTimeLeft(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** True for a student whose account has no registered face, which blocks check-in in this app. */
export function needsFaceEnrollment(user: User | null | undefined): boolean {
  return !!user && user.role === 'student' && user.face_enrolled !== true
}

/** Message for a failed password re-check. */
export function reauthErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.status === 401) return 'Incorrect password.'
  return loginErrorMessage(error)
}

/** Message for a failed POST /users/me/face/reset-code/check. */
export function resetCodeCheckErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.isNetwork) return "Can't reach the server. Check your connection and try again."
  if (parsed.status === 429) {
    const minutes = minutesFromRetryAfter(parsed.retryAfterSeconds)
    return minutes
      ? `Too many code checks. Please wait ${minutes} ${minutes === 1 ? 'minute' : 'minutes'} and try again.`
      : 'Too many code checks. Please wait a minute and try again.'
  }
  if (parsed.code === 'FACE_RESET_CODE_INVALID' || parsed.code === 'FACE_RESET_CODE_REQUIRED' || parsed.status === 422) {
    return RESET_CODE_INVALID_MESSAGE
  }
  if (parsed.code === 'FACE_RESET_CODE_UNAVAILABLE' || parsed.status === 503) {
    return "Reset codes can't be checked right now. Please try again in a few minutes."
  }
  return parsed.detail ?? "Couldn't check the reset code. Please try again."
}

/** Message for a failed POST /users/me/face/enroll. */
export function enrollErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.isNetwork) return "Can't reach the server. Check your connection and try again."
  if (parsed.code === 'NO_FACE_DETECTED') {
    return 'No face was detected. Face the camera in good light, keep your whole face in view, and try again.'
  }
  if (parsed.code === 'CAMERA_CONSENT_REQUIRED') return 'Camera consent was not saved. Allow camera access and try again.'
  if (parsed.code === 'FACE_RESET_CODE_INVALID') return RESET_CODE_INVALID_MESSAGE
  if (parsed.code === 'FACE_RESET_CODE_REQUIRED') return RESET_CODE_REQUIRED_MESSAGE
  if (parsed.code === 'FACE_RESET_CODE_UNAVAILABLE') {
    return "Reset codes can't be checked right now. Please try again in a few minutes."
  }
  if (parsed.status === 413) return 'The photo was too large. Please try again.'
  if (parsed.status === 503) return 'The face service is unavailable right now. Please try again in a minute.'
  if (parsed.status === 429) return 'Too many requests. Please wait a moment and try again.'
  return parsed.detail ?? 'Face registration failed. Please try again.'
}
