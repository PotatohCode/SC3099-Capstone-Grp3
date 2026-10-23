const UUID_A = '11111111-1111-4111-8111-111111111111'
const UUID_B = '22222222-2222-4222-9222-222222222222'
const ID_FORMAT = /^web-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const KEY = 'saiv_device_fingerprint'

type FingerprintModule = typeof import('@/lib/utils/device-fingerprint')

function freshModule(): FingerprintModule {
  let mod: FingerprintModule | undefined
  jest.isolateModules(() => {
    mod = require('@/lib/utils/device-fingerprint')
  })
  return mod as FingerprintModule
}

function mockCrypto(uuids: string[] | null) {
  const queue = uuids ? [...uuids] : []
  Object.defineProperty(crypto, 'randomUUID', {
    configurable: true,
    writable: true,
    value: uuids ? () => queue.shift() : undefined,
  })
}

describe('device fingerprint', () => {
  afterEach(() => {
    jest.restoreAllMocks()
    delete (crypto as { randomUUID?: unknown }).randomUUID
  })

  it('creates a random web-<uuid> id and stores it in localStorage', () => {
    mockCrypto([UUID_A])
    const id = freshModule().getOrCreateDeviceFingerprint()
    expect(id).toBe(`web-${UUID_A}`)
    expect(id.length).toBeLessThanOrEqual(64)
    expect(window.localStorage.getItem(KEY)).toBe(id)
  })

  it('returns the same id after a reload', () => {
    mockCrypto([UUID_A, UUID_B])
    const first = freshModule().getOrCreateDeviceFingerprint()
    expect(freshModule().getOrCreateDeviceFingerprint()).toBe(first)
  })

  it('gives a different id on another install', () => {
    mockCrypto([UUID_A, UUID_B])
    const first = freshModule().getOrCreateDeviceFingerprint()
    window.localStorage.clear()
    expect(freshModule().getOrCreateDeviceFingerprint()).not.toBe(first)
  })

  it('does not read browser traits', () => {
    mockCrypto([UUID_A])
    const ua = jest.spyOn(window.navigator, 'userAgent', 'get')
    freshModule().getOrCreateDeviceFingerprint()
    expect(ua).not.toHaveBeenCalled()
  })

  it('falls back to getRandomValues without randomUUID and never uses Math.random', () => {
    mockCrypto(null)
    const random = jest.spyOn(Math, 'random')
    expect(freshModule().newDeviceId()).toMatch(ID_FORMAT)
    expect(random).not.toHaveBeenCalled()
  })

  it('replaces a malformed stored value such as the old djb2 format', () => {
    mockCrypto([UUID_A])
    window.localStorage.setItem(KEY, 'web-1a2b3c4d')
    expect(freshModule().getOrCreateDeviceFingerprint()).toBe(`web-${UUID_A}`)
  })

  it('removes the legacy sessionStorage copy', () => {
    mockCrypto([UUID_A])
    window.localStorage.setItem(KEY, `web-${UUID_A}`)
    window.sessionStorage.setItem(KEY, 'web-1a2b3c4d')
    freshModule().getOrCreateDeviceFingerprint()
    expect(window.sessionStorage.getItem(KEY)).toBeNull()
  })

  it('keeps a stable in-memory id when localStorage is unavailable', () => {
    mockCrypto([UUID_A, UUID_B])
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const mod = freshModule()
    const first = mod.getOrCreateDeviceFingerprint()
    expect(mod.getOrCreateDeviceFingerprint()).toBe(first)
  })

  it('rotates to a new stored id', () => {
    mockCrypto([UUID_A, UUID_B])
    const mod = freshModule()
    const first = mod.getOrCreateDeviceFingerprint()
    const rotated = mod.rotateDeviceFingerprint()
    expect(rotated).toBe(`web-${UUID_B}`)
    expect(rotated).not.toBe(first)
    expect(mod.getOrCreateDeviceFingerprint()).toBe(rotated)
  })

  it('detects platforms from the user agent', () => {
    const ua = jest.spyOn(window.navigator, 'userAgent', 'get')
    const mod = freshModule()
    ua.mockReturnValue('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)')
    expect(mod.detectPlatform()).toBe('ios')
    ua.mockReturnValue('Mozilla/5.0 (Linux; Android 14)')
    expect(mod.detectPlatform()).toBe('android')
    ua.mockReturnValue('Mozilla/5.0 (X11; Linux x86_64)')
    expect(mod.detectPlatform()).toBe('desktop')
  })
})
