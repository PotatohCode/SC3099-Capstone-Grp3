'use client'

/**
 * Task 1.5: Geolocation & Consent Capture.
 * Component tree Section 2.1: "geolocation.tsx [Geolocation request + consent]"
 */

import { useState } from 'react'
import { useGeolocation } from '@/lib/hooks/useGeolocation'
import { setConsent } from '@/lib/utils/consent-tracker'
import type { LocationData } from '@/lib/context/CheckInContext'

interface GeolocationStepProps {
  onLocationConfirmed: (location: LocationData) => void
}

export function GeolocationStep({ onLocationConfirmed }: GeolocationStepProps) {
  const { status, position, error, requestLocation } = useGeolocation()
  const [hasPrompted, setHasPrompted] = useState(false)

  async function handleRequest() {
    setConsent('geolocation', true)
    setHasPrompted(true)
    const result = await requestLocation()
    if (result) {
      onLocationConfirmed(result)
    }
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
          onClick={handleRequest}
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
          onClick={handleRequest}
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
            <dd>{Math.round(position.accuracy)}m</dd>
          </div>
        </dl>
      </div>
    )
  }

  return null
}
