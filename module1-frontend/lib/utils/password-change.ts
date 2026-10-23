/** Change-password rules and messages: client-side checks that mirror the backend, and wording for each error it returns. */
import { loginErrorMessage, parseApiError } from '@/lib/utils/api-error'

export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 128

export interface PasswordChangeForm {
  current: string
  next: string
  confirm: string
}

/** Returns the first problem with the form, or null when it can be sent. */
export function validatePasswordChange(form: PasswordChangeForm): string | null {
  if (!form.current) return 'Enter your current password.'
  const length = Array.from(form.next).length
  if (length < PASSWORD_MIN_LENGTH) return `New password must be at least ${PASSWORD_MIN_LENGTH} characters.`
  if (length > PASSWORD_MAX_LENGTH) return `New password must be at most ${PASSWORD_MAX_LENGTH} characters.`
  if (form.next !== form.confirm) return "The new passwords don't match."
  if (form.next === form.current) return 'New password must be different from your current one.'
  return null
}

/** Message for a failed POST /users/me/password. */
export function changePasswordErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.isNetwork) return "Can't reach the server. Check your connection and try again."
  if (parsed.status === 403 && parsed.code === 'PASSWORD_INCORRECT') {
    return 'Current password is incorrect. Repeated wrong attempts lock your account for 15 minutes.'
  }
  if (parsed.code === 'PASSWORD_UNCHANGED') return 'New password must be different from your current one.'
  if (parsed.status === 422) return `Passwords must be ${PASSWORD_MIN_LENGTH} to ${PASSWORD_MAX_LENGTH} characters.`
  if (parsed.status === 429 && parsed.code === 'ACCOUNT_LOCKED') return loginErrorMessage(error)
  if (parsed.status === 429) return 'Too many requests. Please wait a moment and try again.'
  return parsed.detail ?? "Couldn't change your password. Please try again."
}
