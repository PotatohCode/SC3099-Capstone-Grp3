/**
 * Task 1.6 / Decision 1 (IMPLEMENTATION_PLAN.html Section 9):
 * "Access Token Storage: sessionStorage (survives page refresh, cleared on close)"
 *
 * Section 4, Task 1.6: "Store access_token in sessionStorage" / "Refresh token stored
 * in HttpOnly cookie by backend".
 *
 * DEVIATION NOTE (flagged in final report): docs/API-SPECIFICATION.md's actual
 * POST /auth/login and POST /auth/refresh contracts return/require the refresh token
 * as a JSON body field rather than issuing it via a Set-Cookie header. There is no
 * documented HttpOnly cookie mechanism we can rely on from the frontend. To keep the
 * check-in flow functional against the real backend contract while staying as close
 * to the plan's intent as possible, the refresh token is kept out of localStorage
 * (which persists indefinitely and is the highest-risk XSS target) and stored in
 * sessionStorage alongside the access token, cleared on tab close and on logout.
 *
 * CRITICAL: Never console.log() any token value anywhere in this codebase.
 */

const ACCESS_TOKEN_KEY = 'saiv_access_token'
const REFRESH_TOKEN_KEY = 'saiv_refresh_token'
const CACHED_USER_KEY = 'saiv_cached_user'

function isBrowser(): boolean {
  return typeof window !== 'undefined'
}

export function getAccessToken(): string | null {
  if (!isBrowser()) return null
  return window.sessionStorage.getItem(ACCESS_TOKEN_KEY)
}

export function setAccessToken(token: string): void {
  if (!isBrowser()) return
  window.sessionStorage.setItem(ACCESS_TOKEN_KEY, token)
}

export function getRefreshToken(): string | null {
  if (!isBrowser()) return null
  return window.sessionStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setRefreshToken(token: string): void {
  if (!isBrowser()) return
  window.sessionStorage.setItem(REFRESH_TOKEN_KEY, token)
}

export function setTokens(accessToken: string, refreshToken: string): void {
  setAccessToken(accessToken)
  setRefreshToken(refreshToken)
}

export function clearTokens(): void {
  if (!isBrowser()) return
  window.sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  window.sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  window.sessionStorage.removeItem(CACHED_USER_KEY)
}

/** Keeps the signed-in profile beside the tokens so an offline reload can still show who is signed in. */
export function setCachedUser<T>(user: T): void {
  if (!isBrowser()) return
  window.sessionStorage.setItem(CACHED_USER_KEY, JSON.stringify(user))
}

/** Returns the profile saved by setCachedUser, or null when missing or unreadable. */
export function getCachedUser<T>(): T | null {
  if (!isBrowser()) return null
  try {
    return JSON.parse(window.sessionStorage.getItem(CACHED_USER_KEY) ?? 'null') as T | null
  } catch {
    return null
  }
}

export function hasAccessToken(): boolean {
  return !!getAccessToken()
}
