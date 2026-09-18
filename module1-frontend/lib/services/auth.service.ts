/**
 * Component tree Section 2.1: "auth.service.ts [Login, register, token refresh - Task 1.6]"
 * Endpoints from API-SPECIFICATION.md: POST /auth/register, POST /auth/login, POST /auth/refresh
 */

import httpClient from '@/lib/utils/http-client'
import type { LoginRequest, LoginResponse, RegisterRequest, User } from '@/lib/types'

export async function register(payload: RegisterRequest): Promise<User> {
  const response = await httpClient.post<User>('/auth/register', payload)
  return response.data
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const response = await httpClient.post<LoginResponse>('/auth/login', payload)
  return response.data
}

export async function getCurrentUser(): Promise<User> {
  const response = await httpClient.get<User>('/users/me')
  return response.data
}
