/**
 * Task 1.6 - Axios instance with request/response interceptors.
 * IMPLEMENTATION_PLAN.html Section 2.2 "HTTP Interceptor Strategy":
 *
 *   Request Interceptor:
 *     - Attach Authorization: Bearer <access_token> header
 *     - Skip for public endpoints (/auth/login, /auth/register, /auth/refresh)
 *   Response Interceptor:
 *     - 401 Unauthorized -> POST /auth/refresh (once, silent)
 *         - Success: retry original request with new token
 *         - Failure: redirect to /auth/login
 *     - 429 Too Many Requests -> read Retry-After header, show rate-limit message,
 *       do NOT retry immediately
 *     - Other errors: pass through to caller
 *
 * CRITICAL: never console.log() request/response bodies here - they may carry tokens.
 */

import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios'
import { API_BASE_URL, PUBLIC_AUTH_PATHS } from '@/lib/config'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from '@/lib/utils/token-storage'
import type { RefreshResponse } from '@/lib/types'

/** Thrown (as `.rateLimited`/`.retryAfterSeconds` on the AxiosError) when a 429 occurs. */
export interface RateLimitInfo {
  retryAfterSeconds: number | null
}

declare module 'axios' {
  export interface AxiosRequestConfig {
    _retry?: boolean
  }
}

function isPublicAuthPath(url: string | undefined): boolean {
  if (!url) return false
  return PUBLIC_AUTH_PATHS.some((path) => url.includes(path))
}

export const httpClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000, // Section 6.2 Retry & Timeout Strategy: standard API call = 30s
  withCredentials: true,
})

// Separate, un-intercepted client used only for the refresh call itself, so a failed
// refresh never re-triggers the same 401 handling loop.
const refreshClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
})

httpClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (!isPublicAuthPath(config.url)) {
    const token = getAccessToken()
    if (token) {
      config.headers = config.headers ?? {}
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// --- 401 refresh-and-retry coordination -----------------------------------------
let isRefreshing = false
let pendingQueue: Array<{
  resolve: (token: string | null) => void
  reject: (error: unknown) => void
}> = []

function flushQueue(error: unknown, token: string | null) {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  pendingQueue = []
}

function redirectToLogin() {
  clearTokens()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('saiv:auth-expired'))
    if (window.location.pathname !== '/auth/login') {
      window.location.href = '/auth/login'
    }
  }
}

async function performRefresh(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    return null
  }
  const response = await refreshClient.post<RefreshResponse>('/auth/refresh', {
    refresh_token: refreshToken,
  })
  const { access_token, refresh_token } = response.data
  setTokens(access_token, refresh_token)
  return access_token
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const { response, config } = error

    if (!response || !config) {
      return Promise.reject(error)
    }

    // --- 429 Too Many Requests: never auto-retry, surface Retry-After to caller ---
    if (response.status === 429) {
      const retryAfterHeader = response.headers?.['retry-after']
      const retryAfterSeconds = retryAfterHeader ? Number(retryAfterHeader) : null
      const rateLimitError = error as AxiosError & { rateLimit?: RateLimitInfo }
      rateLimitError.rateLimit = {
        retryAfterSeconds: Number.isFinite(retryAfterSeconds) ? retryAfterSeconds : null,
      }
      return Promise.reject(rateLimitError)
    }

    // --- 401 Unauthorized: try one silent refresh, then retry original request ---
    if (response.status === 401 && !config._retry && !isPublicAuthPath(config.url)) {
      config._retry = true

      if (isRefreshing) {
        // Another request already triggered a refresh; wait for it.
        return new Promise((resolve, reject) => {
          pendingQueue.push({
            resolve: (token) => {
              if (token) {
                config.headers = config.headers ?? {}
                config.headers.Authorization = `Bearer ${token}`
                resolve(httpClient(config))
              } else {
                reject(error)
              }
            },
            reject,
          })
        })
      }

      isRefreshing = true
      try {
        const newToken = await performRefresh()
        isRefreshing = false
        if (!newToken) {
          flushQueue(error, null)
          redirectToLogin()
          return Promise.reject(error)
        }
        flushQueue(null, newToken)
        config.headers = config.headers ?? {}
        config.headers.Authorization = `Bearer ${newToken}`
        return httpClient(config)
      } catch (refreshError) {
        isRefreshing = false
        flushQueue(refreshError, null)
        redirectToLogin()
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

/** Extracts a user-friendly message from a backend ApiErrorBody-shaped error. */
export function extractErrorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (axios.isAxiosError(error)) {
    const rateLimit = (error as AxiosError & { rateLimit?: RateLimitInfo }).rateLimit
    if (rateLimit) {
      return rateLimit.retryAfterSeconds
        ? `Too many requests. Please try again in ${rateLimit.retryAfterSeconds} seconds.`
        : 'Too many requests. Please try again shortly.'
    }
    const detail = error.response?.data && (error.response.data as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string }
      if (first?.msg) return first.msg
    }
    if (error.message) return error.message
  }
  return fallback
}

export default httpClient
