/**
 * Component tree Section 2.1: "session.service.ts [GET /sessions/my-sessions]"
 */

import httpClient from '@/lib/utils/http-client'
import type { PaginatedResponse, SessionSummary } from '@/lib/types'

export interface MySessionsParams {
  status?: string
  upcoming?: boolean
  limit?: number
}

export async function getMySessions(
  params: MySessionsParams = {}
): Promise<SessionSummary[]> {
  const response = await httpClient.get<SessionSummary[] | PaginatedResponse<SessionSummary>>(
    '/sessions/my-sessions',
    { params }
  )
  const data = response.data
  return Array.isArray(data) ? data : data.items
}

export async function getSession(sessionId: string): Promise<SessionSummary> {
  const response = await httpClient.get<SessionSummary>(`/sessions/${sessionId}`)
  return response.data
}
