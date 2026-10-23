import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { AuthProvider } from '@/lib/context/AuthContext'
import { useAuth } from '@/lib/hooks/useAuth'
import { getAccessToken, setTokens } from '@/lib/utils/token-storage'
import { stubAdapter, type RecordedRequest } from '@/test/axios-stub'

const clearOfflineQueue = jest.fn(async () => undefined)
jest.mock('@/lib/services/offline.service', () => ({ clearOfflineQueue: () => clearOfflineQueue() }))

const push = jest.fn()
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: jest.fn() }) }))

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>
const student = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student', camera_consent: false, geolocation_consent: false }

async function settle() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('AuthContext', () => {
  beforeEach(() => push.mockClear())

  it('shows the lockout message on 429 ACCOUNT_LOCKED', async () => {
    stubAdapter(() => ({ status: 429, data: { code: 'ACCOUNT_LOCKED' }, headers: { 'retry-after': '600' } }))
    const { result } = renderHook(() => useAuth(), { wrapper })
    await settle()
    await expect(result.current.login({ email: 's@e.edu', password: 'x' })).rejects.toThrow(
      'Too many failed sign-in attempts. This account is locked for 10 minutes.'
    )
  })

  it('logs in, registers the device, and logs out through the API', async () => {
    const calls = stubAdapter((req: RecordedRequest) => {
      if (req.url === '/auth/login') return { status: 200, data: { access_token: 'a1', refresh_token: 'r1', token_type: 'bearer', user: student } }
      if (req.url === '/devices/register') return { status: 201, data: {} }
      if (req.url === '/auth/logout') return { status: 204 }
      return { status: 404 }
    })
    const { result } = renderHook(() => useAuth(), { wrapper })
    await settle()
    await act(async () => {
      await result.current.login({ email: 's@e.edu', password: 'pw' })
    })
    expect(result.current.isAuthenticated).toBe(true)
    expect(calls.map((c) => c.url)).toEqual(['/auth/login', '/devices/register'])
    await act(async () => {
      await result.current.logout()
    })
    expect(calls[2]).toMatchObject({ url: '/auth/logout', authorization: 'Bearer a1', data: { refresh_token: 'r1' } })
    expect(getAccessToken()).toBeNull()
    expect(result.current.user).toBeNull()
    expect(clearOfflineQueue).toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith('/auth/login')
  })

  it('saveConsent sends the change and updates the user', async () => {
    setTokens('a1', 'r1')
    const calls = stubAdapter((req: RecordedRequest) => {
      if (req.url === '/users/me' && req.method === 'get') return { status: 200, data: student }
      if (req.url === '/users/me' && req.method === 'put') return { status: 200, data: { ...student, camera_consent: true } }
      return { status: 404 }
    })
    const { result } = renderHook(() => useAuth(), { wrapper })
    await settle()
    await settle()
    expect(result.current.user?.camera_consent).toBe(false)
    await act(async () => {
      await result.current.saveConsent('camera', true)
    })
    expect(calls.find((c) => c.method === 'put')?.data).toEqual({ camera_consent: true })
    expect(result.current.user?.camera_consent).toBe(true)
    await act(async () => {
      await result.current.saveConsent('camera', true)
    })
    expect(calls.filter((c) => c.method === 'put')).toHaveLength(1)
  })
})
