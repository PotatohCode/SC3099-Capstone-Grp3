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
  LivenessChallenge,
  PaginatedResponse,
  VerifyChallengeResponse,
} from '@/lib/types'

export async function submitCheckIn(payload: CheckInRequest): Promise<CheckInResponse> {
  const response = await httpClient.post<CheckInResponse>('/checkins/', payload)
  return response.data
}

/** Requests a single-use liveness challenge for the session (POST /checkins/challenge). */
export async function requestChallenge(sessionId: string): Promise<LivenessChallenge> {
  const response = await httpClient.post<LivenessChallenge>('/checkins/challenge', { session_id: sessionId })
  return response.data
}

/** Checks a captured burst before the check-in (POST /checkins/challenge/{id}/verify); each challenge can be verified once. */
export async function verifyChallenge(challengeId: string, frames: string[], signal?: AbortSignal): Promise<VerifyChallengeResponse> {
  const response = await httpClient.post<VerifyChallengeResponse>(
    `/checkins/challenge/${encodeURIComponent(challengeId)}/verify`,
    { frames },
    { signal }
  )
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
