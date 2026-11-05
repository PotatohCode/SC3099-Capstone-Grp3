'use client'

/** OpenStreetMap view of the student's location fix, with its accuracy and, when known, the venue and its check-in radius. */

import { useEffect, useRef, useState } from 'react'
import 'leaflet/dist/leaflet.css'

export interface MapVenue {
  latitude: number
  longitude: number
  radius?: number | null
}

interface LocationMapProps {
  latitude: number
  longitude: number
  accuracy?: number
  venue?: MapVenue | null
}

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/** Picks the venue fields a map needs from a session, or null when the session has no venue coordinates. */
export function venueFromSession(session: {
  venue_latitude?: number | null
  venue_longitude?: number | null
  geofence_radius_meters?: number | null
} | null): MapVenue | null {
  if (!session || typeof session.venue_latitude !== 'number' || typeof session.venue_longitude !== 'number') return null
  return { latitude: session.venue_latitude, longitude: session.venue_longitude, radius: session.geofence_radius_meters }
}

/** Renders a small Leaflet map; Leaflet loads in the browser only, so server rendering never touches window. */
export function LocationMap({ latitude, longitude, accuracy, venue }: LocationMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const venueLat = venue?.latitude
  const venueLon = venue?.longitude
  const venueRadius = venue?.radius
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let map: import('leaflet').Map | null = null
    setProblem(null)
    import('leaflet')
      .then((L) => {
        if (cancelled || !containerRef.current) return
        const you = L.latLng(latitude, longitude)
        // Set a view first so layers attach immediately
        map = L.map(containerRef.current, { scrollWheelZoom: false, dragging: !L.Browser.mobile }).setView(you, 17)
        L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION })
          .on('tileerror', () => !cancelled && setProblem('Map tiles could not load. Your coordinates are shown above.'))
          .addTo(map)
        const bounds = L.latLngBounds([you, you])
        if (typeof accuracy === 'number' && accuracy > 0) {
          L.circle(you, { radius: accuracy, color: '#2563eb', weight: 1, fillOpacity: 0.1 }).addTo(map)
        }
        L.circleMarker(you, { radius: 7, color: '#ffffff', weight: 2, fillColor: '#2563eb', fillOpacity: 1 })
          .bindTooltip('You')
          .addTo(map)
        if (typeof venueLat === 'number' && typeof venueLon === 'number') {
          const place = L.latLng(venueLat, venueLon)
          if (typeof venueRadius === 'number' && venueRadius > 0) {
            L.circle(place, { radius: venueRadius, color: '#0f766e', weight: 2, fillOpacity: 0.15 }).addTo(map)
            bounds.extend(place.toBounds(venueRadius * 2))
          }
          L.circleMarker(place, { radius: 7, color: '#ffffff', weight: 2, fillColor: '#dc2626', fillOpacity: 1 })
            .bindTooltip('Venue')
            .addTo(map)
          bounds.extend(place)
        }
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 17 })
      })
      .catch((err) => {
        console.warn('Location map failed', err)
        if (!cancelled) setProblem('Map unavailable. Your coordinates are shown above.')
      })
    return () => {
      cancelled = true
      map?.remove()
    }
  }, [latitude, longitude, accuracy, venueLat, venueLon, venueRadius])

  const hasVenue = typeof venueLat === 'number' && typeof venueLon === 'number'
  return (
    <figure className="space-y-1">
      <div
        ref={containerRef}
        role="img"
        aria-label={hasVenue ? 'Map of your location and the venue' : 'Map of your location'}
        className="relative z-0 h-48 w-full overflow-hidden rounded-md border border-gray-200 bg-gray-100"
        data-testid="location-map"
      />
      {problem && (
        <p className="text-xs text-amber-700" role="status">
          {problem}
        </p>
      )}
      <figcaption className="flex flex-wrap items-center gap-x-1 text-xs text-gray-600">
        <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full bg-blue-600" /> You
        {hasVenue && (
          <>
            {' '}&middot; <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full bg-red-600" /> Venue
            {typeof venueRadius === 'number' && venueRadius > 0 && <> &middot; shaded circle: check-in area ({Math.round(venueRadius)} m)</>}
          </>
        )}
      </figcaption>
    </figure>
  )
}
