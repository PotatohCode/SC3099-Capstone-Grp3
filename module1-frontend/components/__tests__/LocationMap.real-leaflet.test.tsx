import { act, render, screen } from '@testing-library/react'
import { LocationMap } from '@/components/LocationMap'

// jsdom lacks SVG geometry; Leaflet checks createSVGRect before using its SVG renderer
jest.mock('leaflet', () => {
  ;(SVGElement.prototype as unknown as { createSVGRect: () => object }).createSVGRect = () => ({})
  return jest.requireActual('leaflet/dist/leaflet-src.js')
})

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20))
  })
}

// Tile attribution only appears once the map has loaded
const loaded = (el: HTMLElement) => /OpenStreetMap/.test(el.querySelector('.leaflet-control-attribution')?.textContent ?? '')

describe('LocationMap with the real Leaflet library', () => {
  it('draws the map when the venue has a check-in radius', async () => {
    render(<LocationMap latitude={1.2938} longitude={103.808} accuracy={56} venue={{ latitude: 1.3483, longitude: 103.6831, radius: 150 }} />)
    await settle()
    const map = screen.getByTestId('location-map')
    expect(map.classList.contains('leaflet-container')).toBe(true)
    expect(map.querySelector('.leaflet-tile-pane')).toBeTruthy()
    expect(loaded(map)).toBe(true)
    expect(screen.queryByText(/Map unavailable/)).toBeNull()
  })

  it('draws the map without a venue', async () => {
    render(<LocationMap latitude={1.3} longitude={103.8} accuracy={10} />)
    await settle()
    expect(loaded(screen.getByTestId('location-map'))).toBe(true)
  })
})
