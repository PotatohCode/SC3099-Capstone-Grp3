/** Records Leaflet calls so map components can be tested in jsdom without loading tiles. */
type Call = { kind: string; args: unknown[] }

export const leafletCalls: Call[] = []

/** Chainable layer stub that records how it was created. */
function layer(kind: string, args: unknown[]) {
  leafletCalls.push({ kind, args })
  const self = {
    addTo: () => self,
    bindTooltip: () => self,
    on: () => self,
  }
  return self
}

const L = {
  map: (el: HTMLElement, options: unknown) => {
    leafletCalls.push({ kind: 'map', args: [el, options] })
    const map = {
      setView: (...args: unknown[]) => {
        leafletCalls.push({ kind: 'setView', args })
        return map
      },
      fitBounds: (...args: unknown[]) => leafletCalls.push({ kind: 'fitBounds', args }),
      remove: () => leafletCalls.push({ kind: 'remove', args: [] }),
    }
    return map
  },
  tileLayer: (...args: unknown[]) => layer('tileLayer', args),
  circle: (...args: unknown[]) => layer('circle', args),
  circleMarker: (...args: unknown[]) => layer('circleMarker', args),
  Browser: { mobile: false },
  latLng: (lat: number, lng: number) => {
    const point = { lat, lng }
    Object.defineProperty(point, 'toBounds', { value: (size: number) => ({ kind: 'toBounds', lat, lng, size }) })
    return point
  },
  latLngBounds: (points: unknown[]) => {
    const all = [...points]
    return { extend: (p: unknown) => all.push(p), points: all }
  },
}

export default L
module.exports = L
module.exports.leafletCalls = leafletCalls
module.exports.default = L
