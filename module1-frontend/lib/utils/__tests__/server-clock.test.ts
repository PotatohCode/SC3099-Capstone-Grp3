import { serverNow, serverOffsetMs, setServerOffsetForTests, syncServerClock } from '@/lib/utils/server-clock'
import { stubAdapter } from '@/test/axios-stub'

describe('server clock', () => {
  beforeEach(() => {
    setServerOffsetForTests(0)
    jest.useFakeTimers({ now: Date.parse('2026-11-05T10:00:00Z') })
  })
  afterEach(() => jest.useRealTimers())

  it('adopts the server time when the phone clock is 10 minutes slow', async () => {
    stubAdapter((req) => (req.url === '/health' ? { status: 200, data: {}, headers: { date: 'Thu, 05 Nov 2026 10:10:00 GMT' } } : { status: 404 }))
    await syncServerClock()
    expect(serverOffsetMs()).toBe(600_500)
    expect(serverNow()).toBe(Date.parse('2026-11-05T10:10:00.500Z'))
  })

  it('adopts the server time when the phone clock is fast', async () => {
    stubAdapter(() => ({ status: 200, data: {}, headers: { date: 'Thu, 05 Nov 2026 09:55:00 GMT' } }))
    await syncServerClock()
    expect(serverNow()).toBe(Date.parse('2026-11-05T09:55:00.500Z'))
  })

  it('falls back to the device clock without a readable Date header', async () => {
    stubAdapter(() => ({ status: 200, data: {} }))
    await syncServerClock()
    expect(serverOffsetMs()).toBe(0)
  })

  it('keeps the last offset when the server is unreachable', async () => {
    setServerOffsetForTests(42_000)
    stubAdapter(() => ({ network: true }))
    await syncServerClock()
    expect(serverOffsetMs()).toBe(42_000)
  })
})
