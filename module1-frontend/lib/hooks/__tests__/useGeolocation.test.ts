import { act, renderHook } from '@testing-library/react'
import { useGeolocation } from '@/lib/hooks/useGeolocation'

type Success = (p: { coords: { latitude: number; longitude: number; accuracy: number } }) => void
type Failure = (e: { code: number; PERMISSION_DENIED: number }) => void

function setGeolocation(impl: (ok: Success, err: Failure, opts: PositionOptions) => void) {
  const getCurrentPosition = jest.fn(impl)
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition } })
  return getCurrentPosition
}

describe('useGeolocation', () => {
  it('returns the exact coordinates and accuracy with fresh high-accuracy options', async () => {
    const get = setGeolocation((ok) => ok({ coords: { latitude: 1.3483123, longitude: 103.6831456, accuracy: 7.25 } }))
    const { result } = renderHook(() => useGeolocation())
    let outcome: Awaited<ReturnType<typeof result.current.requestLocation>> | undefined
    await act(async () => {
      outcome = await result.current.requestLocation()
    })
    expect(outcome).toEqual({ location: { latitude: 1.3483123, longitude: 103.6831456, accuracy: 7.25 }, denied: false })
    expect(get.mock.calls[0][2]).toEqual({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 })
    expect(result.current.status).toBe('granted')
  })

  it('reports a permission denial', async () => {
    setGeolocation((_ok, err) => err({ code: 1, PERMISSION_DENIED: 1 }))
    const { result } = renderHook(() => useGeolocation())
    let outcome: Awaited<ReturnType<typeof result.current.requestLocation>> | undefined
    await act(async () => {
      outcome = await result.current.requestLocation()
    })
    expect(outcome).toEqual({ location: null, denied: true })
    expect(result.current.status).toBe('denied')
  })

  it('reports other failures without calling them a denial', async () => {
    setGeolocation((_ok, err) => err({ code: 3, PERMISSION_DENIED: 1 }))
    const { result } = renderHook(() => useGeolocation())
    let outcome: Awaited<ReturnType<typeof result.current.requestLocation>> | undefined
    await act(async () => {
      outcome = await result.current.requestLocation()
    })
    expect(outcome).toEqual({ location: null, denied: false })
    expect(result.current.status).toBe('error')
    expect(result.current.error).toBe('Unable to determine your location. Please try again.')
  })
})
