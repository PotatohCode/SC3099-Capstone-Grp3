import { loginErrorMessage, minutesFromRetryAfter, parseApiError } from '@/lib/utils/api-error'
import { httpError, networkError } from '@/test/axios-stub'

describe('parseApiError', () => {
  it('reads status, code, detail and Retry-After', () => {
    const parsed = parseApiError(
      httpError(429, { detail: 'Account locked', code: 'ACCOUNT_LOCKED' }, { 'retry-after': '900' })
    )
    expect(parsed).toEqual({
      status: 429,
      code: 'ACCOUNT_LOCKED',
      detail: 'Account locked',
      retryAfterSeconds: 900,
      isNetwork: false,
    })
  })

  it('prefers the interceptor rateLimit value', () => {
    const err = httpError(429, { code: 'ACCOUNT_LOCKED' }, { 'retry-after': '900' }) as ReturnType<typeof httpError> & {
      rateLimit?: { retryAfterSeconds: number | null }
    }
    err.rateLimit = { retryAfterSeconds: 120 }
    expect(parseApiError(err).retryAfterSeconds).toBe(120)
  })

  it('flags network errors and ignores non-axios errors', () => {
    expect(parseApiError(networkError()).isNetwork).toBe(true)
    expect(parseApiError(new Error('x'))).toEqual({
      status: null,
      code: null,
      detail: null,
      retryAfterSeconds: null,
      isNetwork: false,
    })
  })

  it('drops non-string detail such as a 422 list', () => {
    expect(parseApiError(httpError(422, { detail: [{ msg: 'bad' }] })).detail).toBeNull()
  })
})

describe('minutesFromRetryAfter', () => {
  it.each([
    [1, 1],
    [59, 1],
    [60, 1],
    [61, 2],
    [899, 15],
    [900, 15],
  ])('%p seconds -> %p minutes', (s, m) => {
    expect(minutesFromRetryAfter(s)).toBe(m)
  })

  it.each([null, 0, -5, Number.NaN])('returns null for %p', (s) => {
    expect(minutesFromRetryAfter(s)).toBeNull()
  })
})

describe('loginErrorMessage', () => {
  const locked = (retryAfter?: string) =>
    httpError(
      429,
      { detail: 'Account locked due to too many failed login attempts', code: 'ACCOUNT_LOCKED' },
      retryAfter ? { 'retry-after': retryAfter } : {}
    )

  it('shows the lockout in minutes', () => {
    expect(loginErrorMessage(locked('900'))).toBe(
      'Too many failed sign-in attempts. This account is locked for 15 minutes.'
    )
    expect(loginErrorMessage(locked('45'))).toBe(
      'Too many failed sign-in attempts. This account is locked for 1 minute.'
    )
  })

  it('never says wrong password when locked', () => {
    const message = loginErrorMessage(locked('600'))
    expect(message).not.toMatch(/incorrect|password|credentials/i)
  })

  it('handles a lockout without Retry-After', () => {
    expect(loginErrorMessage(locked())).toBe(
      'Too many failed sign-in attempts. This account is locked. Please try again later.'
    )
  })

  it('distinguishes the network rate limit from a lockout', () => {
    const message = loginErrorMessage(
      httpError(429, { code: 'RATE_LIMITED' }, { 'retry-after': '30' })
    )
    expect(message).toBe('Too many sign-in attempts from this network. Please try again in 30 seconds.')
    expect(message).not.toMatch(/locked/i)
  })

  it('maps wrong credentials, disabled accounts, network and unknown errors', () => {
    expect(loginErrorMessage(httpError(401, { code: 'INVALID_CREDENTIALS' }))).toBe('Incorrect email or password.')
    expect(loginErrorMessage(httpError(403, { code: 'ACCOUNT_DISABLED' }))).toBe(
      'This account is disabled. Contact your instructor or administrator.'
    )
    expect(loginErrorMessage(networkError())).toBe("Can't reach the server. Check your connection and try again.")
    expect(loginErrorMessage(httpError(500, { detail: 'Boom' }))).toBe('Boom')
    expect(loginErrorMessage(new Error('x'))).toBe('Login failed. Please try again.')
  })
})
