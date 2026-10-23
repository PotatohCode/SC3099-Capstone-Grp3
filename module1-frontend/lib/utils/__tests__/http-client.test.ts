import { extractErrorMessage, httpClient } from '@/lib/utils/http-client'
import { setTokens } from '@/lib/utils/token-storage'
import { stubAdapter } from '@/test/axios-stub'

describe('httpClient interceptors', () => {
  it('attaches the bearer token except on public auth paths', async () => {
    setTokens('a1', 'r1')
    const calls = stubAdapter(() => ({ status: 200 }))
    await httpClient.get('/users/me')
    await httpClient.post('/auth/login', {})
    await httpClient.post('/auth/logout', {})
    expect(calls.map((c) => [c.url, c.authorization])).toEqual([
      ['/users/me', 'Bearer a1'],
      ['/auth/login', undefined],
      ['/auth/logout', 'Bearer a1'],
    ])
  })

  it('exposes Retry-After on 429 and keeps the backend code', async () => {
    stubAdapter(() => ({ status: 429, data: { code: 'ACCOUNT_LOCKED' }, headers: { 'retry-after': '900' } }))
    const error = await httpClient.post('/auth/login', {}).catch((e) => e)
    expect(error.rateLimit).toEqual({ retryAfterSeconds: 900 })
    expect(error.response.data.code).toBe('ACCOUNT_LOCKED')
    expect(extractErrorMessage(error)).toBe('Too many requests. Please try again in 900 seconds.')
  })
})
