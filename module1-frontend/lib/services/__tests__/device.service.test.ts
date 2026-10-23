import { registerCurrentDevice } from '@/lib/services/device.service'
import { DEVICE_FINGERPRINT_KEY } from '@/lib/utils/device-fingerprint'
import { stubAdapter } from '@/test/axios-stub'

describe('registerCurrentDevice', () => {
  it('registers the stored id with platform and name', async () => {
    const calls = stubAdapter(() => ({ status: 201, data: { id: 'd1' } }))
    await registerCurrentDevice()
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/devices/register')
    expect(calls[0].data).toMatchObject({
      device_fingerprint: window.localStorage.getItem(DEVICE_FINGERPRINT_KEY),
      device_name: 'Web Browser',
    })
  })

  it('rotates the id and retries once when another user owns it', async () => {
    let n = 0
    const calls = stubAdapter(() =>
      n++ === 0 ? { status: 400, data: { code: 'DEVICE_FINGERPRINT_TAKEN' } } : { status: 201, data: {} }
    )
    await registerCurrentDevice()
    expect(calls).toHaveLength(2)
    const [first, second] = calls.map((c) => (c.data as { device_fingerprint: string }).device_fingerprint)
    expect(second).not.toBe(first)
    expect(window.localStorage.getItem(DEVICE_FINGERPRINT_KEY)).toBe(second)
  })

  it('does not retry other errors', async () => {
    const calls = stubAdapter(() => ({ status: 500, data: {} }))
    await expect(registerCurrentDevice()).rejects.toBeDefined()
    expect(calls).toHaveLength(1)
  })
})
