import { logoutAndClear, updateMe } from '@/lib/services/auth.service'
import { getAccessToken, getRefreshToken, setTokens } from '@/lib/utils/token-storage'
import { stubAdapter } from '@/test/axios-stub'

describe('logoutAndClear', () => {
  it('posts the refresh token with the bearer header before clearing tokens', async () => {
    setTokens('a1', 'r1')
    const tokensAtRequest: Array<[string | null, string | null]> = []
    const calls = stubAdapter(() => {
      tokensAtRequest.push([getAccessToken(), getRefreshToken()])
      return { status: 204 }
    })
    await logoutAndClear()
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({
      method: 'post',
      url: '/auth/logout',
      data: { refresh_token: 'r1' },
      authorization: 'Bearer a1',
      timeout: 5000,
    })
    expect(tokensAtRequest).toEqual([['a1', 'r1']])
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  it.each([
    ['a network error', { network: true } as const],
    ['a server error', { status: 500 }],
    ['an expired token', { status: 401 }],
  ])('still clears tokens after %s and does not throw', async (_label, reply) => {
    setTokens('a1', 'r1')
    const calls = stubAdapter(() => reply)
    await expect(logoutAndClear()).resolves.toBeUndefined()
    expect(calls).toHaveLength(1)
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  it('sends an empty body when there is no refresh token', async () => {
    const calls = stubAdapter(() => ({ status: 204 }))
    await logoutAndClear()
    expect(calls[0].data).toEqual({})
  })

  it('never logs tokens', async () => {
    setTokens('secret-access', 'secret-refresh')
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => jest.spyOn(console, m).mockImplementation(() => undefined))
    stubAdapter(() => ({ status: 500 }))
    await logoutAndClear()
    const logged = JSON.stringify(spies.flatMap((s) => s.mock.calls))
    expect(logged).not.toContain('secret-')
    spies.forEach((s) => s.mockRestore())
  })
})

describe('updateMe', () => {
  it('sends a PUT to /users/me with exactly the patch', async () => {
    const calls = stubAdapter(() => ({ status: 200, data: { id: 'u1', camera_consent: true } }))
    const user = await updateMe({ camera_consent: true })
    expect(calls[0]).toMatchObject({ method: 'put', url: '/users/me', data: { camera_consent: true } })
    expect(user.camera_consent).toBe(true)
  })
})
