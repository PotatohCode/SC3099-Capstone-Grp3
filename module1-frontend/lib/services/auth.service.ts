/**
 * Component tree Section 2.1: "auth.service.ts [Login, token refresh - Task 1.6]"
 * Endpoints from API-SPECIFICATION.md: POST /auth/login, POST /auth/refresh
 */

import httpClient from '@/lib/utils/http-client'
import type { LoginRequest, LoginResponse, User, UserConsentUpdate } from '@/lib/types'
import { clearTokens, getRefreshToken } from '@/lib/utils/token-storage'

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const response = await httpClient.post<LoginResponse>('/auth/login', payload)
  return response.data
}

export async function getCurrentUser(): Promise<User> {
  const response = await httpClient.get<User>('/users/me')
  return response.data
}

/** Updates the current user's profile fields, used to record camera and location consent. */
export async function updateMe(patch: UserConsentUpdate): Promise<User> {
  const response = await httpClient.put<User>('/users/me', patch)
  return response.data
}

/** Revokes the session on the server (access token via header, refresh token in the body), then always clears local tokens. */
export async function logoutAndClear(): Promise<void> {
  const refreshToken = getRefreshToken()
  try {
    await httpClient.post('/auth/logout', refreshToken ? { refresh_token: refreshToken } : {}, {
      timeout: 5000,
      _retry: true,
    })
  } catch {
    return
  } finally {
    clearTokens()
  }
}
