'use client'

/**
 * Task 1.5: Geolocation & Consent Capture.
 * Component tree Section 2.1: "geolocation.tsx [Geolocation request + consent]"
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/lib/hooks/useAuth'
import { useGeolocation } from '@/lib/hooks/useGeolocation'
import { decideConsentGate, queryPermission, type ConsentGate } from '@/lib/utils/consent-tracker'
import type { LocationData } from '@/lib/types'

interface GeolocationStepProps {
  knownLocation: LocationData | null
  onLocationConfirmed: (location: LocationData) => void
  onContinue: () => void
}

export function GeolocationStep({ knownLocation, onLocationConfirmed, onContinue }: GeolocationStepProps) {
  const { user, saveConsent } = useAuth()
  const { status, position, error, requestLocation } = useGeolocation()
  const [gate, setGate] = useState<ConsentGate | null>(null)
  const [hasPrompted, setHasPrompted] = useState(false)

  const fetchLocation = useCallback(async (): Promise<boolean> => {
    setHasPrompted(true)
    const result = await requestLocation()
    if (result.denied) {
      await saveConsent('geolocation', false)
      setGate('blocked')
      return false
    }
    if (!result.location) return false
    await saveConsent('geolocation', true)
    setGate('proceed')
    onLocationConfirmed(result.location)
    return true
  }, [onLocationConfirmed, requestLocation, saveConsent])

  const initialConsent = useRef(user?.geolocation_consent)
  const autoFetch = useRef(knownLocation === null)
  const fetchRef = useRef(fetchLocation)
  fetchRef.current = fetchLocation

  useEffect(() => {
    let cancelled = false
    queryPermission('geolocation').then((permission) => {
      if (cancelled) return
      const decided = decideConsentGate(initialConsent.current, permission)
      setGate(decided)
      if (decided === 'proceed' && autoFetch.current) fetchRef.current()
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (gate === null) {
    return <p className="text-sm text-gray-600">Checking location access...</p>
  }

  if (gate === 'blocked' && status !== 'requesting') {
    return (
      <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-5">
        <p className="text-sm text-red-700">
          Location access is blocked for this site. Turn it on in your browser&apos;s site settings, then tap Try again.
        </p>
        <button
          type="button"
          onClick={fetchLocation}
          className="min-h-[44px] rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
        >
          Try again
        </button>
      </div>
    )
  }

  if (knownLocation && !hasPrompted) {
    return (
      <div className="space-y-3 rounded-lg border border-green-200 bg-green-50 p-5">
        <p className="text-sm font-medium text-green-800">Location captured</p>
        <p className="text-sm text-green-700">
          {knownLocation.latitude.toFixed(5)}, {knownLocation.longitude.toFixed(5)}
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onContinue}
            className="min-h-[44px] rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800"
          >
            Continue
          </button>
          <button
            type="button"
            onClick={fetchLocation}
            className="min-h-[44px] rounded-md border border-green-400 px-4 py-2 text-sm font-medium text-green-800 hover:bg-green-100"
          >
            Update my location
          </button>
        </div>
      </div>
    )
  }

  if (!hasPrompted) {
    return (
      <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Location access required</h2>
        <p className="text-sm text-gray-600">
          We use your device&apos;s location to confirm you&apos;re near the venue. Your
          coordinates are only sent with this check-in.
        </p>
        <button
          type="button"
          onClick={fetchLocation}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Share my location
        </button>
      </div>
    )
  }

  if (status === 'requesting') {
    return <p className="text-sm text-gray-600">Getting your location...</p>
  }

  if (status === 'denied' || status === 'error') {
    return (
      <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-5">
        <p className="text-sm text-red-700">{error}</p>
        <button
          type="button"
          onClick={fetchLocation}
          className="min-h-[44px] rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
        >
          Try again
        </button>
      </div>
    )
  }

  if (status === 'granted' && position) {
    return (
      <div className="space-y-3 rounded-lg border border-green-200 bg-green-50 p-5">
        <p className="text-sm font-medium text-green-800">Location captured</p>
        <dl className="grid grid-cols-3 gap-2 text-sm text-green-700">
          <div>
            <dt className="text-xs text-green-600">Latitude</dt>
            <dd>{position.latitude.toFixed(5)}</dd>
          </div>
          <div>
            <dt className="text-xs text-green-600">Longitude</dt>
            <dd>{position.longitude.toFixed(5)}</dd>
          </div>
          <div>
            <dt className="text-xs text-green-600">Accuracy</dt>
            <dd>{typeof position.accuracy === 'number' ? `${Math.round(position.accuracy)}m` : 'Unknown'}</dd>
          </div>
        </dl>
      </div>
    )
  }

  return null
}
