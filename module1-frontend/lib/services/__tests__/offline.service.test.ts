import type { CheckInRequest } from '@/lib/types'
import { httpError, networkError, stubAdapter } from '@/test/axios-stub'

jest.mock('localforage', () => {
  const stores = new Map<string, Map<string, unknown>>()
  return {
    createInstance: ({ storeName }: { storeName: string }) => {
      const store = stores.get(storeName) ?? new Map<string, unknown>()
      stores.set(storeName, store)
      return {
        setItem: async (k: string, v: unknown) => {
          store.set(k, JSON.parse(JSON.stringify(v)))
          return v
        },
        getItem: async (k: string) => store.get(k) ?? null,
        removeItem: async (k: string) => {
          store.delete(k)
        },
        clear: async () => store.clear(),
        iterate: async (fn: (v: unknown) => void) => {
          store.forEach((v) => fn(v))
        },
      }
    },
  }
})

import { clearOfflineQueue, getQueuedCheckIns, isRetryableSyncError, queueCheckIn, syncQueuedCheckIns } from '@/lib/services/offline.service'

const burstPayload: CheckInRequest = {
  session_id: 's1',
  latitude: 1.35,
  longitude: 103.8,
  location_accuracy_meters: 6.5,
  device_fingerprint: 'web-x',
  liveness_challenge_frames: ['f0', 'f1', 'f2'],
  liveness_challenge_response: 'f1',
  challenge_id: 'ch',
  challenge_type: 'sequence',
}

describe('offline queue', () => {
  beforeEach(async () => {
    await clearOfflineQueue()
  })

  it('stores one image and no challenge fields', async () => {
    await queueCheckIn(burstPayload, 'u1')
    const [item] = await getQueuedCheckIns()
    expect(item.payload).toEqual({
      session_id: 's1',
      latitude: 1.35,
      longitude: 103.8,
      location_accuracy_meters: 6.5,
      device_fingerprint: 'web-x',
      liveness_challenge_response: 'f1',
    })
  })

  it('removes an item after a successful sync', async () => {
    await queueCheckIn(burstPayload, 'u1')
    const calls = stubAdapter(() => ({ status: 201, data: { id: 'c1', status: 'flagged' } }))
    const result = await syncQueuedCheckIns('u1')
    expect(result.succeeded).toBe(1)
    expect(calls[0].url).toBe('/checkins/')
    expect(await getQueuedCheckIns()).toEqual([])
  })

  it('removes an item after a final server error so the image is never resent', async () => {
    await queueCheckIn(burstPayload, 'u1')
    stubAdapter(() => ({ status: 400, data: { code: 'ALREADY_CHECKED_IN' } }))
    const result = await syncQueuedCheckIns('u1')
    expect(result.failed).toBe(1)
    expect(await getQueuedCheckIns()).toEqual([])
  })

  it.each([
    ['a network error', { network: true } as const],
    ['a rate limit', { status: 429, data: { code: 'RATE_LIMITED' }, headers: { 'retry-after': '30' } }],
    ['a server error', { status: 503, data: {} }],
  ])('keeps the item after %s', async (_label, reply) => {
    await queueCheckIn(burstPayload, 'u1')
    stubAdapter(() => reply)
    await syncQueuedCheckIns('u1')
    const [item] = await getQueuedCheckIns()
    expect(item).toMatchObject({ status: 'failed', attempts: 1 })
    expect(typeof item.lastError).toBe('string')
  })
})

describe('concurrent sync', () => {
  beforeEach(async () => {
    await clearOfflineQueue()
  })

  it('sends a queued image once even when two syncs start together', async () => {
    await queueCheckIn(burstPayload, 'u1')
    const calls = stubAdapter(() => ({ status: 201, data: { id: 'c1', status: 'flagged' } }))
    await Promise.all([syncQueuedCheckIns('u1'), syncQueuedCheckIns('u1')])
    expect(calls.filter((c) => c.url === '/checkins/')).toHaveLength(1)
    expect(await getQueuedCheckIns()).toEqual([])
  })

  it('allows a later sync after the first finishes', async () => {
    await queueCheckIn(burstPayload, 'u1')
    stubAdapter(() => ({ network: true }))
    await syncQueuedCheckIns('u1')
    const calls = stubAdapter(() => ({ status: 201, data: {} }))
    await syncQueuedCheckIns('u1')
    expect(calls).toHaveLength(1)
  })
})

describe('queue ownership', () => {
  beforeEach(async () => {
    await clearOfflineQueue()
  })

  it('only syncs the logged-in student\'s items', async () => {
    await queueCheckIn(burstPayload, 'student-a')
    const calls = stubAdapter(() => ({ status: 201, data: {} }))
    await syncQueuedCheckIns('student-b')
    expect(calls).toHaveLength(0)
    expect(await getQueuedCheckIns()).toHaveLength(1)
    await syncQueuedCheckIns('student-a')
    expect(calls).toHaveLength(1)
  })

  it('keeps an item on 401 so it can be sent after signing in again', async () => {
    await queueCheckIn(burstPayload, 'u1')
    stubAdapter(() => ({ status: 401, data: { code: 'INVALID_TOKEN' } }))
    await syncQueuedCheckIns('u1')
    expect(await getQueuedCheckIns()).toHaveLength(1)
  })
})

describe('isRetryableSyncError', () => {
  it.each([
    [networkError(), true],
    [httpError(500), true],
    [httpError(503), true],
    [httpError(429), true],
    [httpError(400), false],
    [httpError(403), false],
    [httpError(413), false],
  ])('%#', (error, expected) => {
    expect(isRetryableSyncError(error)).toBe(expected)
  })
})
