/** Parses backend `{detail, code}` errors and builds the login error messages. */
import axios from 'axios'
import type { RateLimitInfo } from '@/lib/utils/http-client'

export interface ParsedApiError {
  status: number | null
  code: string | null
  detail: string | null
  retryAfterSeconds: number | null
  isNetwork: boolean
}

function toSeconds(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/** Normalizes any thrown value into status, code, detail, Retry-After seconds and a network flag. */
export function parseApiError(error: unknown): ParsedApiError {
  if (!axios.isAxiosError(error)) {
    return { status: null, code: null, detail: null, retryAfterSeconds: null, isNetwork: false }
  }
  const response = error.response
  if (!response) {
    return { status: null, code: null, detail: null, retryAfterSeconds: null, isNetwork: true }
  }
  const data = (response.data ?? {}) as { detail?: unknown; code?: unknown }
  const rateLimit = (error as typeof error & { rateLimit?: RateLimitInfo }).rateLimit
  const headers = (response.headers ?? {}) as Record<string, unknown>
  return {
    status: response.status,
    code: typeof data.code === 'string' ? data.code : null,
    detail: typeof data.detail === 'string' ? data.detail : null,
    retryAfterSeconds: rateLimit?.retryAfterSeconds ?? toSeconds(headers['retry-after']),
    isNetwork: false,
  }
}

/** Converts Retry-After seconds into whole minutes, rounding up, minimum 1. */
export function minutesFromRetryAfter(seconds: number | null): number | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) return null
  return Math.max(1, Math.ceil(seconds / 60))
}

/** Returns the message shown on the login page for a failed login. */
export function loginErrorMessage(error: unknown): string {
  const parsed = parseApiError(error)
  if (parsed.isNetwork) return "Can't reach the server. Check your connection and try again."
  if (parsed.status === 429 && parsed.code === 'ACCOUNT_LOCKED') {
    const minutes = minutesFromRetryAfter(parsed.retryAfterSeconds)
    if (minutes === null) {
      return 'Too many failed sign-in attempts. This account is locked. Please try again later.'
    }
    return `Too many failed sign-in attempts. This account is locked for ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}.`
  }
  if (parsed.status === 429) {
    return parsed.retryAfterSeconds
      ? `Too many sign-in attempts from this network. Please try again in ${parsed.retryAfterSeconds} seconds.`
      : 'Too many sign-in attempts from this network. Please try again shortly.'
  }
  if (parsed.status === 401) return 'Incorrect email or password.'
  if (parsed.status === 403 && parsed.code === 'ACCOUNT_DISABLED') {
    return 'This account is disabled. Contact your instructor or administrator.'
  }
  return parsed.detail ?? 'Login failed. Please try again.'
}
