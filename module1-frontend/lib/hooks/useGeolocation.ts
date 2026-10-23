'use client'

/**
 * Task 1.5: Geolocation & Consent Capture
 * Component tree Section 2.1: "useGeolocation() [Position retrieval + error handling - Task 1.5]"
 *
 * - Show consent prompt before calling Geolocation API (handled by the caller UI;
 *   this hook exposes `requestLocation()` to be invoked only after explicit consent).
 * - getCurrentPosition(GEO_OPTIONS from lib/utils/geo.ts)
 * - Reports permission denial so the caller can record consent on the backend.
 * - Handles denial gracefully (status + message, allows retry).
 */

import { useCallback, useState } from 'react'
import type { LocationData } from '@/lib/types'
import { GEO_OPTIONS, toLocationData } from '@/lib/utils/geo'

export type GeolocationStatus = 'idle' | 'requesting' | 'granted' | 'denied' | 'error'

export interface LocationResult {
  location: LocationData | null
  denied: boolean
}

export function useGeolocation() {
  const [status, setStatus] = useState<GeolocationStatus>('idle')
  const [position, setPosition] = useState<LocationData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const requestLocation = useCallback((): Promise<LocationResult> => {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        setStatus('error')
        setError('Geolocation is not supported by this browser.')
        resolve({ location: null, denied: false })
        return
      }

      setStatus('requesting')
      setError(null)

      navigator.geolocation.getCurrentPosition(
        (result) => {
          const data = toLocationData(result.coords)
          setPosition(data)
          setStatus('granted')
          resolve({ location: data, denied: false })
        },
        (geoError) => {
          const denied = geoError.code === geoError.PERMISSION_DENIED
          if (denied) {
            setStatus('denied')
            setError('Location permission was denied. Please allow location access to check in.')
          } else {
            setStatus('error')
            setError('Unable to determine your location. Please try again.')
          }
          resolve({ location: null, denied })
        },
        GEO_OPTIONS
      )
    })
  }, [])

  const reset = useCallback(() => {
    setStatus('idle')
    setPosition(null)
    setError(null)
  }, [])

  return { status, position, error, requestLocation, reset }
}
