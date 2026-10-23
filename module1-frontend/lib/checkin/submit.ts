/** Runs one check-in submission attempt: freshness guard, payload build, online submit or offline queue, and error classification. */
import { classifyCheckInError, CHALLENGE_EXPIRED_MESSAGE, type CheckInErrorView } from '@/lib/checkin/errors'
import { buildCheckInPayload, type CapturedMedia } from '@/lib/checkin/payload'
import { isChallengeFresh } from '@/lib/liveness/challenge'
import type { CheckInRequest, CheckInResponse, LocationData } from '@/lib/types'

export type SubmitOutcome =
  | { kind: 'success'; result: CheckInResponse }
  | { kind: 'queued' }
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
  queue: (payload: CheckInRequest) => Promise<unknown>
}

/** Submits once; never reuses media, only queues when the browser is actually offline, and checks challenge freshness only for online sends. */
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
  if (!deps.isOnline) return queueOrFail(deps, payload)
  if (deps.media.kind === 'burst' && !isChallengeFresh(deps.media.fetchedAtMs, deps.now())) {
    return { kind: 'failed', view: { message: CHALLENGE_EXPIRED_MESSAGE, action: 'retry-capture', challengeInvalid: true } }
  }
  try {
    return { kind: 'success', result: await deps.submit(payload) }
  } catch (error) {
    const view = classifyCheckInError(error, deps.browserOnline())
    if (view.action === 'queue-offline') return queueOrFail(deps, payload)
    return { kind: 'failed', view }
  }
}

async function queueOrFail(deps: SubmitDeps, payload: CheckInRequest): Promise<SubmitOutcome> {
  try {
    await deps.queue(payload)
    return { kind: 'queued' }
  } catch {
    return { kind: 'failed', view: { message: "We couldn't save your check-in for later. Please try again.", action: 'retry-capture' } }
  }
}
