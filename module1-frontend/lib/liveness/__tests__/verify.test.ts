import { attemptsUsed, clearAttempts, decideAttempt, MAX_ATTEMPTS, RETRY_MESSAGE, resetVerifyCalls, startAttempt, undoAttempt } from '@/lib/liveness/verify'
import { httpError, networkError } from '@/test/axios-stub'

const verified = (result: 'passed' | 'failed' | 'unverified', attempts_left: number | null, failed_step?: string | null) =>
  ({ kind: 'verified', response: { result, attempts_left, failed_step } }) as const

describe('startAttempt', () => {
  beforeEach(() => resetVerifyCalls())

  it('numbers each Start per student and session, and reset clears them', () => {
    expect(startAttempt('u1', 's1')).toBe(1)
    expect(startAttempt('u1', 's1')).toBe(2)
    expect(startAttempt('u1', 's2')).toBe(1)
    expect(startAttempt('u2', 's1')).toBe(1)
    resetVerifyCalls()
    expect(startAttempt('u1', 's1')).toBe(1)
  })

  it('keeps the count in localStorage across a reload, a new tab and a logout, and clears one session after submit', () => {
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    startAttempt('u1', 's2')
    window.sessionStorage.clear()
    jest.isolateModules(() => {
      const fresh = require('@/lib/liveness/verify') as typeof import('@/lib/liveness/verify')
      expect(fresh.attemptsUsed('u1', 's1')).toBe(2)
      expect(fresh.startAttempt('u1', 's1')).toBe(3)
    })
    expect(window.localStorage.getItem('saiv_liveness_attempts:u1:s1')).toBe('3')
    clearAttempts('u1', 's1')
    expect(attemptsUsed('u1', 's1')).toBe(0)
    expect(attemptsUsed('u1', 's2')).toBe(1)
    resetVerifyCalls()
    expect(Object.keys(window.localStorage).filter((k) => k.startsWith('saiv_liveness_attempts:'))).toHaveLength(0)
  })

  it('follows localStorage when another tab clears the count, and removes the key at zero', () => {
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    window.localStorage.removeItem('saiv_liveness_attempts:u1:s1')
    expect(attemptsUsed('u1', 's1')).toBe(0)
    startAttempt('u1', 's1')
    undoAttempt('u1', 's1')
    expect(window.localStorage.getItem('saiv_liveness_attempts:u1:s1')).toBeNull()
  })

  it('gives back a Start that never reached the liveness check', () => {
    startAttempt('u1', 's1')
    undoAttempt('u1', 's1')
    undoAttempt('u1', 's1')
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })
})

describe('decideAttempt', () => {
  it('submits a pass on any attempt', () => {
    for (const attempt of [1, 2, 3]) {
      expect(decideAttempt(verified('passed', 2), attempt)).toEqual({ kind: 'submit', media: 'burst', verification: 'passed', restartFreshness: true })
    }
  })

  it.each([
    [verified('unverified', 3)],
    [verified('failed', 2)],
    [verified('failed', null)],
    [{ kind: 'no-capture' } as const],
    [{ kind: 'verify-error', error: networkError() } as const],
    [{ kind: 'verify-error', error: httpError(429, {}) } as const],
  ])('asks for another Start on the first two attempts (%#)', (outcome) => {
    expect(decideAttempt(outcome, 1)).toEqual({ kind: 'retry', message: RETRY_MESSAGE, secondary: '2 tries left.' })
    expect(decideAttempt(outcome, 2)).toEqual({ kind: 'retry', message: RETRY_MESSAGE, secondary: '1 try left.' })
  })

  it('adds the missed step when one is reported', () => {
    expect(decideAttempt(verified('failed', 2, 'blink'), 1)).toEqual({
      kind: 'retry',
      message: 'Unsuccessful capture, please retry.',
      secondary: "We couldn't see you blink. 2 tries left.",
    })
    expect(decideAttempt(verified('failed', 2, 'nod'), 1)).toMatchObject({ secondary: '2 tries left.' })
  })

  it.each([
    [verified('unverified', 3), { media: 'burst', restartFreshness: true }],
    [verified('failed', 1), { media: 'burst', restartFreshness: true }],
    [{ kind: 'no-capture' } as const, { media: 'none', restartFreshness: false }],
    [{ kind: 'verify-error', error: networkError() } as const, { media: 'burst', restartFreshness: false }],
    [{ kind: 'verify-error', error: httpError(500, {}) } as const, { media: 'burst', restartFreshness: false }],
    [{ kind: 'verify-error', error: httpError(400, { code: 'CHALLENGE_INVALID' }) } as const, { media: 'frame', restartFreshness: false }],
    [{ kind: 'verify-error', error: httpError(413, {}) } as const, { media: 'frame', restartFreshness: false }],
    [{ kind: 'verify-error', error: httpError(422, {}) } as const, { media: 'frame', restartFreshness: false }],
    [{ kind: 'verify-error', error: httpError(429, {}) } as const, { media: 'frame', restartFreshness: false }],
  ])('ends the check for review on the third attempt (%#)', (outcome, expected) => {
    expect(decideAttempt(outcome, MAX_ATTEMPTS)).toEqual({ kind: 'submit', verification: 'review', ...expected })
  })

  it('ends at once when the server has no tries left', () => {
    expect(decideAttempt(verified('failed', 0), 1)).toEqual({ kind: 'submit', media: 'burst', verification: 'review', restartFreshness: true })
    expect(decideAttempt({ kind: 'verify-error', error: httpError(409, { code: 'LIVENESS_ATTEMPTS_EXHAUSTED' }) }, 1)).toEqual({
      kind: 'submit',
      media: 'frame',
      verification: 'review',
      restartFreshness: false,
    })
  })
})
