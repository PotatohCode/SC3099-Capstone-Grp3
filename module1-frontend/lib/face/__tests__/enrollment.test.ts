import { enrollErrorMessage, needsFaceEnrollment, reauthErrorMessage } from '@/lib/face/enrollment'
import { enrollFace } from '@/lib/services/face.service'
import type { User } from '@/lib/types'
import { httpError, networkError, stubAdapter } from '@/test/axios-stub'
import { setTokens } from '@/lib/utils/token-storage'

const base: User = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student' }

describe('needsFaceEnrollment', () => {
  it('is true only for a student without a registered face', () => {
    expect(needsFaceEnrollment({ ...base, face_enrolled: false })).toBe(true)
    expect(needsFaceEnrollment({ ...base })).toBe(true)
    expect(needsFaceEnrollment({ ...base, face_enrolled: true })).toBe(false)
    expect(needsFaceEnrollment({ ...base, role: 'instructor', face_enrolled: false })).toBe(false)
    expect(needsFaceEnrollment(null)).toBe(false)
  })
})

describe('reauthErrorMessage', () => {
  it('maps 401 to an incorrect-password message and reuses login wording otherwise', () => {
    expect(reauthErrorMessage(httpError(401, { code: 'INVALID_CREDENTIALS' }))).toBe('Incorrect password.')
    expect(reauthErrorMessage(httpError(429, { code: 'ACCOUNT_LOCKED' }, { 'retry-after': '900' }))).toBe(
      'Too many failed sign-in attempts. This account is locked for 15 minutes.'
    )
    expect(reauthErrorMessage(httpError(403, { code: 'ACCOUNT_DISABLED' }))).toMatch(/disabled/)
    expect(reauthErrorMessage(networkError())).toMatch(/Can't reach the server/)
  })
})

describe('enrollErrorMessage', () => {
  it.each([
    [httpError(400, { code: 'NO_FACE_DETECTED' }), /No face was detected/],
    [httpError(400, { code: 'CAMERA_CONSENT_REQUIRED' }), /Camera consent was not saved/],
    [httpError(413, { code: 'IMAGE_TOO_LARGE' }), /too large/],
    [httpError(503, { code: 'FACE_SERVICE_UNAVAILABLE' }), /unavailable/],
    [httpError(429, {}), /Too many requests/],
    [networkError(), /Can't reach the server/],
    [httpError(500, {}), /Face registration failed/],
  ])('maps %#', (error, expected) => {
    expect(enrollErrorMessage(error)).toMatch(expected)
  })
})

describe('enrollFace', () => {
  it('posts the raw base64 image with the bearer token', async () => {
    setTokens('a1', 'r1')
    const calls = stubAdapter(() => ({ status: 200, data: { success: true, message: 'ok', face_enrolled: true, quality_score: 0.8 } }))
    const result = await enrollFace('QUJD')
    expect(result.face_enrolled).toBe(true)
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'post', url: '/users/me/face/enroll', data: { image: 'QUJD' }, authorization: 'Bearer a1' })
  })
})
