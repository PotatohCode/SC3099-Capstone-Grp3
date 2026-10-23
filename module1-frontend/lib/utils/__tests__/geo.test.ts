import { GEO_OPTIONS, toLocationData } from '@/lib/utils/geo'

describe('toLocationData', () => {
  it('copies coordinates and accuracy without rounding', () => {
    expect(toLocationData({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 12.3456 })).toEqual({
      latitude: 1.3483123,
      longitude: 103.6831456,
      accuracy: 12.3456,
    })
  })

  it('keeps an accuracy of 0 as reported', () => {
    expect(toLocationData({ latitude: 1, longitude: 2, accuracy: 0 }).accuracy).toBe(0)
  })

  it('omits missing or invalid accuracy instead of inventing one', () => {
    for (const accuracy of [Number.NaN, -3, null as unknown as number, undefined as unknown as number]) {
      expect('accuracy' in toLocationData({ latitude: 1, longitude: 2, accuracy })).toBe(false)
    }
  })
})

describe('GEO_OPTIONS', () => {
  it('asks for a fresh high-accuracy fix', () => {
    expect(GEO_OPTIONS).toEqual({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 })
  })
})
