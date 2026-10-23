import type { CapturedMedia } from '@/lib/checkin/payload'
import { submitAttempt, type SubmitDeps } from '@/lib/checkin/submit'
import type { CheckInRequest, CheckInResponse } from '@/lib/types'
import { httpError, networkError } from '@/test/axios-stub'

const burst: CapturedMedia = { kind: 'burst', challengeId: 'ch', sequence: ['blink'], frames: ['f0', 'f1'], fetchedAtMs: 1000, maxFrames: 30 }

function deps(overrides: Partial<SubmitDeps> = {}): SubmitDeps & { submit: jest.Mock; queue: jest.Mock } {
  return {
    sessionId: 's1',
    location: { latitude: 1.35, longitude: 103.8, accuracy: 8.5 },
    media: burst,
    fingerprint: 'web-x',
    isOnline: true,
    browserOnline: () => true,
    now: () => 2000,
    submit: jest.fn(async () => ({ id: 'c1', status: 'flagged' }) as CheckInResponse),
    queue: jest.fn(async () => undefined),
    ...overrides,
  } as SubmitDeps & { submit: jest.Mock; queue: jest.Mock }
}

describe('submitAttempt', () => {
  it('submits the built payload and returns the result', async () => {
    const d = deps()
    const outcome = await submitAttempt(d)
    expect(outcome).toEqual({ kind: 'success', result: { id: 'c1', status: 'flagged' } })
    const payload = d.submit.mock.calls[0][0] as CheckInRequest
    expect(payload).toMatchObject({ challenge_id: 'ch', challenge_type: 'sequence', location_accuracy_meters: 8.5 })
  })

  it('refuses a stale challenge without calling the API', async () => {
    const d = deps({ now: () => 1000 + 80_000 })
    const outcome = await submitAttempt(d)
    expect(outcome).toEqual({
      kind: 'failed',
      view: { message: "That check took too long. Let's try again.", action: 'retry-capture', challengeInvalid: true },
    })
    expect(d.submit).not.toHaveBeenCalled()
  })

  it('queues when offline instead of calling the API', async () => {
    const d = deps({ isOnline: false })
    expect(await submitAttempt(d)).toEqual({ kind: 'queued' })
    expect(d.submit).not.toHaveBeenCalled()
    expect(d.queue).toHaveBeenCalledTimes(1)
  })

  it('queues after a network error only when the browser reports offline', async () => {
    const offline = deps({ submit: jest.fn(async () => Promise.reject(networkError())), browserOnline: () => false })
    expect(await submitAttempt(offline)).toEqual({ kind: 'queued' })
    const online = deps({ submit: jest.fn(async () => Promise.reject(networkError())) })
    const outcome = await submitAttempt(online)
    expect(outcome.kind).toBe('failed')
    expect(online.queue).not.toHaveBeenCalled()
  })

  it('returns the Singapore view on 403 OUTSIDE_SINGAPORE', async () => {
    const d = deps({ submit: jest.fn(async () => Promise.reject(httpError(403, { code: 'OUTSIDE_SINGAPORE' }))) })
    const outcome = await submitAttempt(d)
    expect(outcome.kind === 'failed' && outcome.view.title).toBe('Check-in not available here')
  })

  it('reports an oversized capture without calling the API', async () => {
    const d = deps({ media: { kind: 'photo', photo: 'A'.repeat(10_000_000) } })
    const outcome = await submitAttempt(d)
    expect(outcome.kind === 'failed' && outcome.view.message).toBe('Photo too large, please retake.')
    expect(d.submit).not.toHaveBeenCalled()
  })

  it('reports a failure instead of hanging when the offline queue cannot save', async () => {
    const d = deps({ isOnline: false, queue: jest.fn(async () => Promise.reject(new Error('QuotaExceededError'))) })
    await expect(submitAttempt(d)).resolves.toEqual({
      kind: 'failed',
      view: { message: "We couldn't save your check-in for later. Please try again.", action: 'retry-capture' },
    })
  })

  it('still queues a burst whose challenge has gone stale when offline', async () => {
    const d = deps({ isOnline: false, now: () => 1000 + 120_000 })
    expect(await submitAttempt(d)).toEqual({ kind: 'queued' })
  })
})
