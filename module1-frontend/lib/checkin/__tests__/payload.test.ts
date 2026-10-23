import {
  buildCheckInPayload,
  LIMITS,
  middleFrame,
  PayloadTooLargeError,
  toOfflinePayload,
  type CapturedMedia,
} from '@/lib/checkin/payload'

const location = { latitude: 1.3483123, longitude: 103.6831456, accuracy: 12.3456 }
const frames = Array.from({ length: 16 }, (_, i) => `frame${i}`)
const burst: CapturedMedia = { kind: 'burst', challengeId: 'ch-1', sequence: ['blink', 'turn_left'], frames, fetchedAtMs: 0, maxFrames: 30 }
const base = { sessionId: 's1', location, fingerprint: 'web-x' }

describe('buildCheckInPayload', () => {
  it('builds a burst payload with challenge fields and frames oldest first', () => {
    const p = buildCheckInPayload({ ...base, media: burst })
    expect(p).toEqual({
      session_id: 's1',
      latitude: 1.3483123,
      longitude: 103.6831456,
      location_accuracy_meters: 12.3456,
      device_fingerprint: 'web-x',
      liveness_challenge_frames: frames,
      challenge_id: 'ch-1',
      challenge_type: 'sequence',
      liveness_challenge_response: 'frame8',
    })
  })

  it('builds a single-photo payload without challenge fields', () => {
    const p = buildCheckInPayload({ ...base, media: { kind: 'photo', photo: 'photo1' } })
    expect(p.liveness_challenge_response).toBe('photo1')
    expect(p).not.toHaveProperty('challenge_id')
    expect(p).not.toHaveProperty('challenge_type')
    expect(p).not.toHaveProperty('liveness_challenge_frames')
  })

  it('sends accuracy unrounded, keeps 0 and omits missing or invalid values', () => {
    const at = (accuracy?: number) =>
      buildCheckInPayload({ ...base, location: { latitude: 1.35, longitude: 103.8, accuracy }, media: { kind: 'photo', photo: 'p' } })
    expect(at(12.3456).location_accuracy_meters).toBe(12.3456)
    expect(at(0).location_accuracy_meters).toBe(0)
    for (const bad of [undefined, Number.NaN, -1, Number.POSITIVE_INFINITY]) {
      expect('location_accuracy_meters' in at(bad)).toBe(false)
    }
  })

  it('does not round coordinates', () => {
    const p = buildCheckInPayload({ ...base, media: { kind: 'photo', photo: 'p' } })
    expect(p.latitude).toBe(1.3483123)
    expect(p.longitude).toBe(103.6831456)
  })

  it('rejects data: prefixed images', () => {
    expect(() => buildCheckInPayload({ ...base, media: { kind: 'photo', photo: 'data:image/jpeg;base64,AAAA' } })).toThrow(/data:/)
    expect(() =>
      buildCheckInPayload({ ...base, media: { ...burst, frames: ['data:image/jpeg;base64,AA'] } as CapturedMedia })
    ).toThrow(/data:/)
  })

  it('enforces the frame cap from max_frames and the hard cap of 30', () => {
    const many = (n: number, maxFrames: number) =>
      ({ ...burst, maxFrames, frames: Array.from({ length: n }, (_, i) => `f${i}`) }) as CapturedMedia
    expect(() => buildCheckInPayload({ ...base, media: many(31, 40) })).toThrow(PayloadTooLargeError)
    expect(() => buildCheckInPayload({ ...base, media: many(11, 10) })).toThrow(PayloadTooLargeError)
    expect(buildCheckInPayload({ ...base, media: many(30, 30) }).liveness_challenge_frames).toHaveLength(30)
  })

  it('enforces per-image and total size limits', () => {
    const huge = 'A'.repeat(LIMITS.maxFrameChars)
    expect(() => buildCheckInPayload({ ...base, media: { kind: 'photo', photo: huge } })).toThrow(PayloadTooLargeError)
    const big = 'B'.repeat(1_000_000)
    const heavy = { ...burst, frames: Array.from({ length: 14 }, () => big) } as CapturedMedia
    expect(() => buildCheckInPayload({ ...base, media: heavy })).toThrow(PayloadTooLargeError)
  })

  it('rejects an empty burst', () => {
    expect(() => buildCheckInPayload({ ...base, media: { ...burst, frames: [] } as CapturedMedia })).toThrow()
  })

})

describe('middleFrame', () => {
  it('picks floor(n/2)', () => {
    expect(middleFrame(['a'])).toBe('a')
    expect(middleFrame(['a', 'b'])).toBe('b')
    expect(middleFrame(['a', 'b', 'c'])).toBe('b')
  })
})

describe('toOfflinePayload', () => {
  it('drops challenge fields and keeps exactly one image', () => {
    const online = buildCheckInPayload({ ...base, media: burst })
    const offline = toOfflinePayload(online)
    expect(offline).not.toHaveProperty('challenge_id')
    expect(offline).not.toHaveProperty('challenge_type')
    expect(offline).not.toHaveProperty('liveness_challenge_frames')
    expect(offline.liveness_challenge_response).toBe('frame8')
    expect(offline.location_accuracy_meters).toBe(12.3456)
  })

  it('uses the middle frame when no single image was set', () => {
    const offline = toOfflinePayload({ session_id: 's', latitude: 1, longitude: 2, device_fingerprint: 'd', liveness_challenge_frames: ['a', 'b', 'c'] })
    expect(offline.liveness_challenge_response).toBe('b')
  })

  it('leaves a photo payload unchanged', () => {
    const photo = buildCheckInPayload({ ...base, media: { kind: 'photo', photo: 'p' } })
    expect(toOfflinePayload(photo)).toEqual(photo)
  })
})
