/**
 * Task 1.7: Device Fingerprinting & Binding
 * "Create lib/utils/device-fingerprint.ts to collect: user agent, screen size,
 *  time zone, platform" / "Store device_fingerprint in sessionStorage"
 *
 * This is a lightweight, non-cryptographic client fingerprint used purely to help the
 * backend's risk engine recognize returning devices. It intentionally collects only
 * coarse, non-PII device attributes (never camera/mic data, never precise hardware IDs).
 */

const DEVICE_FINGERPRINT_KEY = 'saiv_device_fingerprint'

export interface DeviceAttributes {
  userAgent: string
  screenWidth: number
  screenHeight: number
  timezone: string
  platform: string
  language: string
}

function collectDeviceAttributes(): DeviceAttributes {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return {
      userAgent: 'unknown',
      screenWidth: 0,
      screenHeight: 0,
      timezone: 'unknown',
      platform: 'unknown',
      language: 'unknown',
    }
  }

  return {
    userAgent: navigator.userAgent,
    screenWidth: window.screen?.width ?? 0,
    screenHeight: window.screen?.height ?? 0,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'unknown',
    platform: navigator.platform ?? 'unknown',
    language: navigator.language ?? 'unknown',
  }
}

/** Simple deterministic string hash (djb2) - good enough for a client fingerprint. */
function hashString(input: string): string {
  let hash = 5381
  for (let i = 0; i < input.length; i++) {
    hash = (hash * 33) ^ input.charCodeAt(i)
  }
  // Convert to unsigned 32-bit hex, then pad for a stable-looking identifier.
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/** Builds a stable fingerprint string from collected device attributes. */
export function generateDeviceFingerprint(): string {
  const attrs = collectDeviceAttributes()
  const raw = [
    attrs.userAgent,
    `${attrs.screenWidth}x${attrs.screenHeight}`,
    attrs.timezone,
    attrs.platform,
    attrs.language,
  ].join('|')
  return `web-${hashString(raw)}`
}

export function getStoredDeviceFingerprint(): string | null {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem(DEVICE_FINGERPRINT_KEY)
}

export function storeDeviceFingerprint(fingerprint: string): void {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(DEVICE_FINGERPRINT_KEY, fingerprint)
}

/** Returns the cached fingerprint, generating and caching one if it doesn't exist yet. */
export function getOrCreateDeviceFingerprint(): string {
  const existing = getStoredDeviceFingerprint()
  if (existing) return existing
  const generated = generateDeviceFingerprint()
  storeDeviceFingerprint(generated)
  return generated
}

export function detectPlatform(): 'ios' | 'android' | 'web' | 'desktop' {
  if (typeof navigator === 'undefined') return 'web'
  const ua = navigator.userAgent.toLowerCase()
  if (/iphone|ipad|ipod/.test(ua)) return 'ios'
  if (/android/.test(ua)) return 'android'
  if (/mobi/.test(ua)) return 'web'
  return 'desktop'
}
