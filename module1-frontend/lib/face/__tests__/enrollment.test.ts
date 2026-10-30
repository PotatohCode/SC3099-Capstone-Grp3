import {
  enrollErrorMessage,
  formatTimeLeft,
  needsFaceEnrollment,
  normalizeResetCode,
  reauthErrorMessage,
  resetCodeCheckErrorMessage,
} from '@/lib/face/enrollment'
import { checkResetCode, enrollFace } from '@/lib/services/face.service'
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
    [httpError(403, { code: 'FACE_RESET_CODE_INVALID' }), /reset code is wrong, expired or already used/],
    [httpError(403, { code: 'FACE_RESET_CODE_REQUIRED' }), /need a reset code from your instructor/],
    [httpError(503, { code: 'FACE_RESET_CODE_UNAVAILABLE' }), /Reset codes can't be checked right now/],
    [networkError(), /Can't reach the server/],
    [httpError(500, {}), /Face registration failed/],
  ])('maps %#', (error, expected) => {
    expect(enrollErrorMessage(error)).toMatch(expected)
  })
})

describe('resetCodeCheckErrorMessage', () => {
  it.each([
    [httpError(403, { code: 'FACE_RESET_CODE_INVALID' }), /reset code is wrong, expired or already used/],
    [httpError(422, {}), /reset code is wrong, expired or already used/],
    [httpError(429, { code: 'RATE_LIMITED' }, { 'retry-after': '90' }), /wait 2 minutes/],
    [httpError(429, {}), /wait a minute/],
    [httpError(503, { code: 'FACE_RESET_CODE_UNAVAILABLE' }), /can't be checked right now/],
    [networkError(), /Can't reach the server/],
    [httpError(500, {}), /Couldn't check the reset code/],
  ])('maps %#', (error, expected) => {
    expect(resetCodeCheckErrorMessage(error)).toMatch(expected)
  })
})

describe('checkResetCode', () => {
  it('posts the code to the check endpoint and returns the result', async () => {
    setTokens('a1', 'r1')
    const calls = stubAdapter(() => ({ status: 200, data: { required: true, valid: true } }))
    expect(await checkResetCode('K7QM4XPA')).toEqual({ required: true, valid: true })
    expect(calls[0]).toMatchObject({ method: 'post', url: '/users/me/face/reset-code/check', data: { reset_code: 'K7QM4XPA' } })
  })
})

describe('normalizeResetCode', () => {
  it('uppercases and strips spaces and hyphens like the backend', () => {
    expect(normalizeResetCode(' k7qm-4xpa ')).toBe('K7QM4XPA')
    expect(normalizeResetCode('K7QM 4XPA')).toBe('K7QM4XPA')
    expect(normalizeResetCode(' - ')).toBe('')
  })
})

describe('formatTimeLeft', () => {
  it('shows m:ss rounded up and never negative', () => {
    expect(formatTimeLeft(300000)).toBe('5:00')
    expect(formatTimeLeft(299001)).toBe('5:00')
    expect(formatTimeLeft(65000)).toBe('1:05')
    expect(formatTimeLeft(0)).toBe('0:00')
    expect(formatTimeLeft(-5000)).toBe('0:00')
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

  it('adds reset_code only when one is given', async () => {
    setTokens('a1', 'r1')
    const calls = stubAdapter(() => ({ status: 200, data: { success: true, message: 'ok', face_enrolled: true, quality_score: 0.8 } }))
    await enrollFace('QUJD', 'K7QM4XPA')
    await enrollFace('QUJD', '')
    expect(calls[0].data).toEqual({ image: 'QUJD', reset_code: 'K7QM4XPA' })
    expect(calls[1].data).toEqual({ image: 'QUJD' })
  })
})
