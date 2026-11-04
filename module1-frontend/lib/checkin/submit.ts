/** Runs one check-in submission attempt: freshness guard, payload build, live submit, and error classification. */
import { classifyCheckInError, CHALLENGE_EXPIRED_MESSAGE, OFFLINE_MESSAGE, type CheckInErrorView } from '@/lib/checkin/errors'
import { buildCheckInPayload, type CapturedMedia } from '@/lib/checkin/payload'
import { isChallengeFresh } from '@/lib/liveness/challenge'
import type { CheckInRequest, CheckInResponse, LocationData } from '@/lib/types'

export type SubmitOutcome =
  | { kind: 'success'; result: CheckInResponse }
  | { kind: 'failed'; view: CheckInErrorView }

export interface SubmitDeps {
  sessionId: string
  location: LocationData
  media: CapturedMedia
  fingerprint: string
  isOnline: boolean
  browserOnline: () => boolean
  now: () => number
  submit: (payload: CheckInRequest) => Promise<CheckInResponse>
}

/** Submits once and never stores or defers the check-in; offline attempts fail with a reconnect message. */
export async function submitAttempt(deps: SubmitDeps): Promise<SubmitOutcome> {
  let payload: CheckInRequest
  try {
    payload = buildCheckInPayload({
      sessionId: deps.sessionId,
      location: deps.location,
      fingerprint: deps.fingerprint,
      media: deps.media,
    })
  } catch (error) {
    return { kind: 'failed', view: classifyCheckInError(error, true) }
  }
  if (!deps.isOnline) return { kind: 'failed', view: { message: OFFLINE_MESSAGE, action: 'retry-capture' } }
  if (deps.media.kind === 'burst' && !isChallengeFresh(deps.media.fetchedAtMs, deps.now())) {
    return { kind: 'failed', view: { message: CHALLENGE_EXPIRED_MESSAGE, action: 'retry-capture', challengeInvalid: true } }
  }
  try {
    return { kind: 'success', result: await deps.submit(payload) }
  } catch (error) {
    return { kind: 'failed', view: classifyCheckInError(error, deps.browserOnline()) }
  }
}
