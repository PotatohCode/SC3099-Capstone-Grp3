/** Camera and location consent: reads the browser permission state and records the student's choice on the backend (PUT /users/me). */
import { updateMe } from '@/lib/services/auth.service'
import type { User, UserConsentUpdate } from '@/lib/types'

export type ConsentType = 'camera' | 'geolocation'
export type PermissionView = 'granted' | 'denied' | 'prompt' | 'unknown'
export type ConsentGate = 'ask' | 'proceed' | 'blocked'

const LEGACY_KEY_PREFIX = 'saiv_consent_'

/** Reads navigator.permissions for the given type; any missing API or unsupported name gives 'unknown'. */
export async function queryPermission(type: ConsentType): Promise<PermissionView> {
  try {
    if (typeof navigator === 'undefined' || !navigator.permissions?.query) return 'unknown'
    const status = await navigator.permissions.query({ name: type as PermissionName })
    return status.state === 'granted' || status.state === 'denied' || status.state === 'prompt' ? status.state : 'unknown'
  } catch {
    return 'unknown'
  }
}

/** Decides whether to ask, go straight ahead, or show the blocked-in-settings message. */
export function decideConsentGate(serverConsent: boolean | undefined, permission: PermissionView): ConsentGate {
  if (permission === 'denied') return 'blocked'
  if (serverConsent === true) return 'proceed'
  return 'ask'
}

/** Sends the consent change to the backend when it differs from the server value; returns the updated user or null. */
export async function recordConsent(
  type: ConsentType,
  granted: boolean,
  serverValue: boolean | undefined,
  update: (patch: UserConsentUpdate) => Promise<User> = updateMe
): Promise<User | null> {
  clearLegacyConsent()
  if (serverValue === granted) return null
  const patch: UserConsentUpdate = type === 'camera' ? { camera_consent: granted } : { geolocation_consent: granted }
  try {
    return await update(patch)
  } catch {
    return null
  }
}

/** Removes the old browser-only consent flags, since the backend is now the record. */
export function clearLegacyConsent(): void {
  try {
    window.localStorage.removeItem(`${LEGACY_KEY_PREFIX}camera`)
    window.localStorage.removeItem(`${LEGACY_KEY_PREFIX}geolocation`)
  } catch {
    return
  }
}
