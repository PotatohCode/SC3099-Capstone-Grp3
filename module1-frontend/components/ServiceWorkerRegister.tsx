'use client'

/**
 * Task 1.8: Service Worker registration.
 * Task 1.10: PWA installability depends on an active, controlling service worker.
 */

import { useEffect } from 'react'

export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!('serviceWorker' in navigator)) return

    navigator.serviceWorker.register('/service-worker.js').catch(() => {
      // Registration failures (e.g. unsupported browser, dev environment quirks)
      // should not break the app - PWA features simply degrade gracefully.
    })
  }, [])

  return null
}
