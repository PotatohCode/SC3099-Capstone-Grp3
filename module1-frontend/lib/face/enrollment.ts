/** Face identity rules and messages: who must enroll before checking in, the capture length, and error wording. */
import { loginErrorMessage, parseApiError } from '@/lib/utils/api-error'
import type { User } from '@/lib/types'

export const FACE_CAPTURE_MS = 5000
export const FACE_PROMPT_DISMISSED_KEY = 'saiv_face_prompt_dismissed'

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

/** Message for a failed POST /users/me/face/enroll. */
export function enrollErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.isNetwork) return "Can't reach the server. Check your connection and try again."
  if (parsed.code === 'NO_FACE_DETECTED') {
    return 'No face was detected. Face the camera in good light, keep your whole face in view, and try again.'
  }
  if (parsed.code === 'CAMERA_CONSENT_REQUIRED') return 'Camera consent was not saved. Allow camera access and try again.'
  if (parsed.status === 413) return 'The photo was too large. Please try again.'
  if (parsed.status === 503) return 'The face service is unavailable right now. Please try again in a minute.'
  if (parsed.status === 429) return 'Too many requests. Please wait a moment and try again.'
  return parsed.detail ?? 'Face registration failed. Please try again.'
}
