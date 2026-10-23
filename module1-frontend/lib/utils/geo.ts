/** Geolocation helpers: browser options and conversion of coordinates without rounding or invented accuracy. */
import type { LocationData } from '@/lib/types'

export const GEO_OPTIONS: PositionOptions = { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }

/** Copies latitude, longitude and accuracy as reported; a missing or invalid accuracy is left out. */
export function toLocationData(coords: Pick<GeolocationCoordinates, 'latitude' | 'longitude' | 'accuracy'>): LocationData {
  const data: LocationData = { latitude: coords.latitude, longitude: coords.longitude }
  if (typeof coords.accuracy === 'number' && Number.isFinite(coords.accuracy) && coords.accuracy >= 0) {
    data.accuracy = coords.accuracy
  }
  return data
}
