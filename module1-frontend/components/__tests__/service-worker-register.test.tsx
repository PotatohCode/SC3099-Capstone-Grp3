import { render } from '@testing-library/react'
import { ServiceWorkerRegister } from '@/components/ServiceWorkerRegister'

describe('ServiceWorkerRegister', () => {
  afterEach(() => {
    delete (navigator as { serviceWorker?: unknown }).serviceWorker
    jest.restoreAllMocks()
  })

  it('logs a warning when registration fails instead of failing silently', async () => {
    const error = new Error('SecurityError: An SSL certificate error occurred when fetching the script')
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { register: jest.fn(() => Promise.reject(error)) } })
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined)
    render(<ServiceWorkerRegister />)
    await Promise.resolve()
    await Promise.resolve()
    expect(warn).toHaveBeenCalledWith('Service worker registration failed; offline support is unavailable.', error)
  })
})
