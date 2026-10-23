/** Builds POST /checkins/ payloads from the captured media and location, enforcing Module 2's frame and size limits. */
import { HARD_MAX_FRAMES } from '@/lib/liveness/challenge'
import type { CheckInRequest, LocationData } from '@/lib/types'

export type CapturedMedia =
  | { kind: 'burst'; challengeId: string; sequence: string[]; frames: string[]; fetchedAtMs: number; maxFrames: number }
  | { kind: 'photo'; photo: string }

export const LIMITS = { maxFrameChars: 10_000_000, maxBodyChars: 14_000_000 } as const

export class PayloadTooLargeError extends Error {}

export interface BuildPayloadArgs {
  sessionId: string
  location: LocationData
  fingerprint: string
  media: CapturedMedia
}

/** Returns the middle frame of a burst, the image Module 2 also uses as its primary image. */
export function middleFrame(frames: string[]): string {
  return frames[Math.floor(frames.length / 2)]
}

function assertImages(images: string[], maxFrames: number, frameCount: number): void {
  if (frameCount > maxFrames) throw new PayloadTooLargeError(`Too many frames: ${frameCount} > ${maxFrames}`)
  let total = 0
  for (const image of images) {
    if (image.startsWith('data:')) throw new Error('Images must be raw base64 without a data: prefix')
    if (image.length >= LIMITS.maxFrameChars) throw new PayloadTooLargeError('Image too large')
    total += image.length
  }
  if (total > LIMITS.maxBodyChars) throw new PayloadTooLargeError('Check-in payload too large')
}

/** Builds the check-in body; accuracy is sent unchanged only when the browser reported a real value. */
export function buildCheckInPayload({ sessionId, location, fingerprint, media }: BuildPayloadArgs): CheckInRequest {
  const payload: CheckInRequest = {
    session_id: sessionId,
    latitude: location.latitude,
    longitude: location.longitude,
    device_fingerprint: fingerprint,
  }
  const accuracy = location.accuracy
  if (typeof accuracy === 'number' && Number.isFinite(accuracy) && accuracy >= 0) {
    payload.location_accuracy_meters = accuracy
  }
  if (media.kind === 'photo') {
    assertImages([media.photo], HARD_MAX_FRAMES, 0)
    payload.liveness_challenge_response = media.photo
    return payload
  }
  const cap = Math.min(Number.isFinite(media.maxFrames) ? media.maxFrames : HARD_MAX_FRAMES, HARD_MAX_FRAMES)
  if (media.frames.length === 0) throw new Error('A burst needs at least one frame')
  const primary = middleFrame(media.frames)
  assertImages([...media.frames, primary], cap, media.frames.length)
  payload.liveness_challenge_frames = [...media.frames]
  payload.challenge_id = media.challengeId
  payload.challenge_type = 'sequence'
  payload.liveness_challenge_response = primary
  return payload
}

/** Strips challenge fields and keeps a single image, since a queued check-in cannot reuse an expiring single-use challenge. */
export function toOfflinePayload(payload: CheckInRequest): CheckInRequest {
  const rest: CheckInRequest = { ...payload }
  const frames = rest.liveness_challenge_frames
  delete rest.challenge_id
  delete rest.challenge_type
  delete rest.liveness_challenge_frames
  const image = rest.liveness_challenge_response ?? (frames && frames.length > 0 ? middleFrame(frames) : undefined)
  return image ? { ...rest, liveness_challenge_response: image } : rest
}
