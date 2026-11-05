import { act, render, screen } from '@testing-library/react'
import { LocationMap, venueFromSession } from '@/components/LocationMap'
import { leafletCalls } from '@/test/leaflet-mock'

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await new Promise((r) => setTimeout(r, 0))
  })
}

const kinds = (kind: string) => leafletCalls.filter((c) => c.kind === kind)

describe('LocationMap', () => {
  beforeEach(() => {
    leafletCalls.length = 0
  })

  it('draws OpenStreetMap tiles with attribution and a marker at the student fix', async () => {
    render(<LocationMap latitude={1.2938} longitude={103.808} accuracy={56} />)
    await flush()
    const [url, opts] = kinds('tileLayer')[0].args as [string, { attribution: string }]
    expect(url).toBe('https://tile.openstreetmap.org/{z}/{x}/{y}.png')
    expect(opts.attribution).toContain('https://www.openstreetmap.org/copyright')
    expect(kinds('circleMarker')[0].args[0]).toEqual({ lat: 1.2938, lng: 103.808 })
    expect(kinds('circle')[0].args).toEqual([{ lat: 1.2938, lng: 103.808 }, expect.objectContaining({ radius: 56 })])
    expect(screen.getByRole('img', { name: 'Map of your location' })).toBeTruthy()
  })

  it('adds the venue pin and its check-in circle when the session has a venue', async () => {
    render(<LocationMap latitude={1.2938} longitude={103.808} venue={{ latitude: 1.3483, longitude: 103.6831, radius: 150 }} />)
    await flush()
    const markers = kinds('circleMarker').map((c) => c.args[0])
    expect(markers).toEqual([{ lat: 1.2938, lng: 103.808 }, { lat: 1.3483, lng: 103.6831 }])
    expect(kinds('circle').map((c) => (c.args[1] as { radius: number }).radius)).toEqual([150])
    const [bounds] = kinds('fitBounds')[0].args as [{ points: unknown[] }]
    expect(bounds.points).toContainEqual({ kind: 'toBounds', lat: 1.3483, lng: 103.6831, size: 300 })
    expect(screen.getByRole('img', { name: 'Map of your location and the venue' })).toBeTruthy()
    expect(screen.getByText(/check-in area \(150 m\)/)).toBeTruthy()
  })

  it('sets a view before adding layers and turns off one-finger panning on phones only', async () => {
    render(<LocationMap latitude={1.3} longitude={103.8} />)
    await flush()
    expect(kinds('setView')[0].args).toEqual([{ lat: 1.3, lng: 103.8 }, 17])
    expect(kinds('map')[0].args[1]).toMatchObject({ dragging: true, scrollWheelZoom: false })
  })

  it('skips the accuracy circle when accuracy is unknown', async () => {
    render(<LocationMap latitude={1.3} longitude={103.8} />)
    await flush()
    expect(kinds('circle')).toHaveLength(0)
  })

  it('removes the map on unmount', async () => {
    const { unmount } = render(<LocationMap latitude={1.3} longitude={103.8} />)
    await flush()
    unmount()
    expect(kinds('remove')).toHaveLength(1)
  })

  it('redraws when the coordinates change', async () => {
    const { rerender } = render(<LocationMap latitude={1.3} longitude={103.8} />)
    await flush()
    rerender(<LocationMap latitude={1.31} longitude={103.81} />)
    await flush()
    expect(kinds('map')).toHaveLength(2)
    expect(kinds('remove')).toHaveLength(1)
    expect(kinds('circleMarker').at(-1)?.args[0]).toEqual({ lat: 1.31, lng: 103.81 })
  })
})

describe('venueFromSession', () => {
  it('returns the venue fields when both coordinates are numbers', () => {
    expect(venueFromSession({ venue_latitude: 1.3, venue_longitude: 103.8, geofence_radius_meters: 100 })).toEqual({
      latitude: 1.3,
      longitude: 103.8,
      radius: 100,
    })
  })

  it.each([null, {}, { venue_latitude: 1.3 }, { venue_latitude: null, venue_longitude: 103.8 }])('returns null for %p', (s) => {
    expect(venueFromSession(s)).toBeNull()
  })
})
