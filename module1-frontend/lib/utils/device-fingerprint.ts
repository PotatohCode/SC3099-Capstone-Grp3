/** Per-install random device id (web-<uuid>) kept in localStorage, plus platform detection for device registration. */

export const DEVICE_FINGERPRINT_KEY = 'saiv_device_fingerprint'

const VALID_ID = /^web-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

let memoryFallback: string | null = null

function uuidFromRandomValues(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** Generates a new random id; randomUUID needs a secure context, so getRandomValues is the fallback. */
export function newDeviceId(): string {
  const uuid =
    typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : uuidFromRandomValues()
  return `web-${uuid.toLowerCase()}`
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(DEVICE_FINGERPRINT_KEY)
  } catch {
    return null
  }
}

function store(id: string): void {
  memoryFallback = id
  try {
    window.localStorage.setItem(DEVICE_FINGERPRINT_KEY, id)
  } catch {
    return
  }
}

function clearLegacySessionCopy(): void {
  try {
    window.sessionStorage.removeItem(DEVICE_FINGERPRINT_KEY)
  } catch {
    return
  }
}

/** Returns this install's device id, creating and persisting one if missing or malformed. */
export function getOrCreateDeviceFingerprint(): string {
  if (typeof window === 'undefined') return 'web-server'
  clearLegacySessionCopy()
  const stored = readStored()
  if (stored && VALID_ID.test(stored)) return stored
  if (memoryFallback && VALID_ID.test(memoryFallback)) return memoryFallback
  const id = newDeviceId()
  store(id)
  return id
}

/** Replaces this install's device id, used when the backend reports the id belongs to another user. */
export function rotateDeviceFingerprint(): string {
  const id = newDeviceId()
  store(id)
  return id
}

export function detectPlatform(): 'ios' | 'android' | 'web' | 'desktop' {
  if (typeof navigator === 'undefined') return 'web'
  const ua = navigator.userAgent.toLowerCase()
  if (/iphone|ipad|ipod/.test(ua)) return 'ios'
  if (/android/.test(ua)) return 'android'
  if (/mobi/.test(ua)) return 'web'
  return 'desktop'
}
