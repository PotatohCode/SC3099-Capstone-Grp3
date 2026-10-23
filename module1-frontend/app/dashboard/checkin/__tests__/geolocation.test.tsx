import { act, fireEvent, render, screen } from '@testing-library/react'
import { GeolocationStep } from '@/app/dashboard/checkin/geolocation'
import { installGeolocation, installPermissions } from '@/test/browser-mocks'

const saveConsent = jest.fn(async () => undefined)
let geoConsent: boolean | undefined = false

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'student', geolocation_consent: geoConsent }, saveConsent }),
}))

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('GeolocationStep', () => {
  beforeEach(() => {
    saveConsent.mockClear()
    geoConsent = false
  })

  it('asks first, records consent, then passes the exact reading on', async () => {
    installPermissions('prompt')
    const get = installGeolocation({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 4.2 })
    const onLocationConfirmed = jest.fn()
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={onLocationConfirmed} onContinue={jest.fn()} />)
    await flush()
    expect(get).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Share my location' }))
    await flush()
    expect(saveConsent).toHaveBeenCalledWith('geolocation', true)
    expect(get.mock.invocationCallOrder[0]).toBeLessThan(saveConsent.mock.invocationCallOrder[0])
    expect(onLocationConfirmed).toHaveBeenCalledWith({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 4.2 })
  })

  it('goes straight to the reading when consent is on record', async () => {
    geoConsent = true
    installPermissions('granted')
    const get = installGeolocation({ latitude: 1.35, longitude: 103.8, accuracy: 9 })
    const onLocationConfirmed = jest.fn()
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={onLocationConfirmed} onContinue={jest.fn()} />)
    await flush()
    await flush()
    expect(get).toHaveBeenCalledTimes(1)
    expect(onLocationConfirmed).toHaveBeenCalled()
    expect(saveConsent).not.toHaveBeenCalledWith('geolocation', false)
  })

  it('records a denial as consent false and shows how to unblock', async () => {
    installPermissions(null)
    installGeolocation({ errorCode: 1 })
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={jest.fn()} onContinue={jest.fn()} />)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Share my location' }))
    await flush()
    expect(saveConsent).not.toHaveBeenCalledWith('geolocation', true)
    expect(saveConsent).toHaveBeenCalledWith('geolocation', false)
    expect(screen.getByText(/Location access is blocked for this site/)).toBeTruthy()
  })

  it('shows the blocked message when the browser already denies location', async () => {
    installPermissions('denied')
    const get = installGeolocation({ latitude: 1, longitude: 2, accuracy: 3 })
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={jest.fn()} onContinue={jest.fn()} />)
    await flush()
    expect(screen.getByText(/Location access is blocked for this site/)).toBeTruthy()
    expect(get).not.toHaveBeenCalled()
  })

  it('shows the known location with Continue instead of fetching again', async () => {
    geoConsent = true
    installPermissions('granted')
    const get = installGeolocation({ latitude: 1.35, longitude: 103.8, accuracy: 9 })
    const onContinue = jest.fn()
    render(<GeolocationStep knownLocation={{ latitude: 1.35, longitude: 103.8, accuracy: 9 }} onLocationConfirmed={jest.fn()} onContinue={onContinue} />)
    await flush()
    await flush()
    expect(get).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onContinue).toHaveBeenCalled()
  })

  it('retrying from blocked saves consent only after the browser returns a position', async () => {
    installPermissions('denied')
    installGeolocation({ errorCode: 1 })
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={jest.fn()} onContinue={jest.fn()} />)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await flush()
    expect(saveConsent).not.toHaveBeenCalledWith('geolocation', true)
  })

  it('leaves the blocked screen and saves consent once a retry gets a position', async () => {
    installPermissions('denied')
    installGeolocation({ latitude: 1.35, longitude: 103.8, accuracy: 9 })
    const onLocationConfirmed = jest.fn()
    render(<GeolocationStep knownLocation={null} onLocationConfirmed={onLocationConfirmed} onContinue={jest.fn()} />)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await flush()
    expect(onLocationConfirmed).toHaveBeenCalled()
    expect(saveConsent).toHaveBeenCalledWith('geolocation', true)
    expect(screen.queryByText(/Location access is blocked for this site/)).toBeNull()
    expect(screen.getByText('Location captured')).toBeTruthy()
  })
})
