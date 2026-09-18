/**
 * Component tree Section 2.1: "consent-tracker.ts [Track camera/geo consent]"
 * Task 1.5: "Track consent in localStorage"
 * Privacy Requirements (CLAUDE.md): "Track consent for camera and geolocation"
 *
 * Consent flags are intentionally stored in localStorage (persist across sessions,
 * so the user isn't re-prompted with the same consent dialog on every login) - unlike
 * auth tokens, these are not sensitive values.
 */

export type ConsentType = 'camera' | 'geolocation'

const CONSENT_KEY_PREFIX = 'saiv_consent_'

export interface ConsentRecord {
  granted: boolean
  timestamp: string
}

export function getConsent(type: ConsentType): ConsentRecord | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(`${CONSENT_KEY_PREFIX}${type}`)
  if (!raw) return null
  try {
    return JSON.parse(raw) as ConsentRecord
  } catch {
    return null
  }
}

export function setConsent(type: ConsentType, granted: boolean): void {
  if (typeof window === 'undefined') return
  const record: ConsentRecord = { granted, timestamp: new Date().toISOString() }
  window.localStorage.setItem(`${CONSENT_KEY_PREFIX}${type}`, JSON.stringify(record))
}

export function hasConsented(type: ConsentType): boolean {
  return getConsent(type)?.granted === true
}

export function clearConsent(type: ConsentType): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(`${CONSENT_KEY_PREFIX}${type}`)
}
