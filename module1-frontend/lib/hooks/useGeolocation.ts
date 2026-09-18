'use client'

/**
 * Task 1.5: Geolocation & Consent Capture
 * Component tree Section 2.1: "useGeolocation() [Position retrieval + error handling - Task 1.5]"
 *
 * - Show consent prompt before calling Geolocation API (handled by the caller UI;
 *   this hook exposes `requestLocation()` to be invoked only after explicit consent).
 * - getCurrentPosition({ enableHighAccuracy: false, timeout: 10000 })
 * - Tracks consent via lib/utils/consent-tracker.ts
 * - Handles denial gracefully (status + message, allows retry).
 */

import { useCallback, useState } from 'react'
import { setConsent } from '@/lib/utils/consent-tracker'
import type { LocationData } from '@/lib/context/CheckInContext'

export type GeolocationStatus = 'idle' | 'requesting' | 'granted' | 'denied' | 'error'

export function useGeolocation() {
  const [status, setStatus] = useState<GeolocationStatus>('idle')
  const [position, setPosition] = useState<LocationData | null>(null)
  const [error, setError] = useState<string | null>(null)

  const requestLocation = useCallback((): Promise<LocationData | null> => {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        setStatus('error')
        setError('Geolocation is not supported by this browser.')
        setConsent('geolocation', false)
        resolve(null)
        return
      }

      setStatus('requesting')
      setError(null)

      navigator.geolocation.getCurrentPosition(
        (result) => {
          const data: LocationData = {
            latitude: result.coords.latitude,
            longitude: result.coords.longitude,
            accuracy: result.coords.accuracy,
          }
          setConsent('geolocation', true)
          setPosition(data)
          setStatus('granted')
          resolve(data)
        },
        (geoError) => {
          setConsent('geolocation', geoError.code !== geoError.PERMISSION_DENIED)
          if (geoError.code === geoError.PERMISSION_DENIED) {
            setStatus('denied')
            setError('Location permission was denied. Please allow location access to check in.')
          } else {
            setStatus('error')
            setError('Unable to determine your location. Please try again.')
          }
          resolve(null)
        },
        { enableHighAccuracy: false, timeout: 10000 }
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
