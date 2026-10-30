/** Signal that sends an open check-in wizard back to step 1 (the session list), used by the nav "Check In" link. */

export const CHECKIN_RESTART_EVENT = 'saiv:checkin-restart'

/** Asks a mounted check-in wizard to start over at the session list. */
export function requestCheckInRestart(): void {
  window.dispatchEvent(new Event(CHECKIN_RESTART_EVENT))
}

/** Removes resume keys left by older builds, which saved the session a student was checking in to. */
export function forgetLegacyProgress(): void {
  try {
    const keys = Object.keys(window.localStorage).filter((key) => key.startsWith('saiv_checkin_progress:'))
    for (const key of keys) window.localStorage.removeItem(key)
  } catch {
    return
  }
}
