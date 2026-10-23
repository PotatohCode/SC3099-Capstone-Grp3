import { clearLegacyConsent, decideConsentGate, queryPermission, recordConsent } from '@/lib/utils/consent-tracker'
import type { User } from '@/lib/types'
import { stubAdapter } from '@/test/axios-stub'

function setPermissions(value: unknown) {
  Object.defineProperty(navigator, 'permissions', { configurable: true, value })
}

describe('queryPermission', () => {
  afterEach(() => setPermissions(undefined))

  it.each(['granted', 'denied', 'prompt'])('passes through %p', async (state) => {
    setPermissions({ query: jest.fn().mockResolvedValue({ state }) })
    await expect(queryPermission('camera')).resolves.toBe(state)
  })

  it('queries by the given permission name', async () => {
    const query = jest.fn().mockResolvedValue({ state: 'granted' })
    setPermissions({ query })
    await queryPermission('geolocation')
    expect(query).toHaveBeenCalledWith({ name: 'geolocation' })
  })

  it('returns unknown when the API is missing or rejects the name', async () => {
    setPermissions(undefined)
    await expect(queryPermission('camera')).resolves.toBe('unknown')
    setPermissions({ query: jest.fn().mockRejectedValue(new TypeError('camera is not a valid name')) })
    await expect(queryPermission('camera')).resolves.toBe('unknown')
  })
})

describe('decideConsentGate', () => {
  it.each([
    [true, 'granted', 'proceed'],
    [true, 'prompt', 'proceed'],
    [true, 'unknown', 'proceed'],
    [true, 'denied', 'blocked'],
    [false, 'granted', 'ask'],
    [false, 'prompt', 'ask'],
    [false, 'unknown', 'ask'],
    [false, 'denied', 'blocked'],
    [undefined, 'granted', 'ask'],
    [undefined, 'unknown', 'ask'],
    [undefined, 'denied', 'blocked'],
  ] as const)('server %p + browser %p -> %p', (server, permission, gate) => {
    expect(decideConsentGate(server, permission)).toBe(gate)
  })
})

describe('recordConsent', () => {
  it('sends only the changed consent key to PUT /users/me', async () => {
    const calls = stubAdapter(() => ({ status: 200, data: { id: 'u1', camera_consent: true } }))
    const user = await recordConsent('camera', true, false)
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'put', url: '/users/me', data: { camera_consent: true } })
    expect(user?.camera_consent).toBe(true)
  })

  it('records a geolocation denial as false', async () => {
    const update = jest.fn(async () => ({ id: 'u1', geolocation_consent: false }) as User)
    await recordConsent('geolocation', false, true, update)
    expect(update).toHaveBeenCalledWith({ geolocation_consent: false })
  })

  it('skips the call when the server already has the value', async () => {
    const update = jest.fn()
    await expect(recordConsent('camera', true, true, update)).resolves.toBeNull()
    expect(update).not.toHaveBeenCalled()
  })

  it('never throws when the backend call fails', async () => {
    const update = jest.fn(async () => Promise.reject(new Error('down')))
    await expect(recordConsent('camera', true, undefined, update)).resolves.toBeNull()
  })

  it('removes the old browser-only consent flags', async () => {
    window.localStorage.setItem('saiv_consent_camera', '{"granted":true}')
    window.localStorage.setItem('saiv_consent_geolocation', '{"granted":true}')
    window.localStorage.setItem('other', 'x')
    await recordConsent('camera', true, true, jest.fn())
    expect(window.localStorage.getItem('saiv_consent_camera')).toBeNull()
    expect(window.localStorage.getItem('saiv_consent_geolocation')).toBeNull()
    expect(window.localStorage.getItem('other')).toBe('x')
    clearLegacyConsent()
  })
})
