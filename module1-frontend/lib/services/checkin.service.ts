/**
 * Component tree Section 2.1: "checkin.service.ts [POST /checkins/, GET /checkins/my-checkins]"
 *
 * Task 1.8 constraint: POST /checkins/ is Network-Only (never cached/queued transparently
 * by the service worker) - see public/service-worker.js. Offline queuing here is explicit
 * application-level logic (lib/services/offline.service.ts), not SW caching.
 */

import httpClient from '@/lib/utils/http-client'
import type {
  AppealRequest,
  AppealResponse,
  CheckInHistoryItem,
  CheckInRequest,
  CheckInResponse,
  PaginatedResponse,
} from '@/lib/types'

export async function submitCheckIn(payload: CheckInRequest): Promise<CheckInResponse> {
  const response = await httpClient.post<CheckInResponse>('/checkins/', payload)
  return response.data
}

export async function getCheckIn(checkinId: string): Promise<CheckInResponse> {
  const response = await httpClient.get<CheckInResponse>(`/checkins/${checkinId}`)
  return response.data
}

export interface MyCheckInsParams {
  course_id?: string
  limit?: number
  offset?: number
}

export async function getMyCheckIns(
  params: MyCheckInsParams = {}
): Promise<CheckInHistoryItem[]> {
  const response = await httpClient.get<CheckInHistoryItem[] | PaginatedResponse<CheckInHistoryItem>>(
    '/checkins/my-checkins',
    { params }
  )
  const data = response.data
  return Array.isArray(data) ? data : data.items
}

export async function appealCheckIn(
  checkinId: string,
  payload: AppealRequest
): Promise<AppealResponse> {
  const response = await httpClient.post<AppealResponse>(`/checkins/${checkinId}/appeal`, payload)
  return response.data
}
