import { clearCachedApiResponses, purgeLegacyOfflineQueue } from '@/lib/services/offline.service'

describe('purgeLegacyOfflineQueue', () => {
  afterEach(() => {
    delete (globalThis as { indexedDB?: unknown }).indexedDB
  })

  it('deletes the old IndexedDB queue and its sessionStorage backup', async () => {
    const deleteDatabase = jest.fn(() => {
      const request: { onsuccess?: () => void } = {}
      setTimeout(() => request.onsuccess?.(), 0)
      return request
    })
    ;(globalThis as { indexedDB?: unknown }).indexedDB = { deleteDatabase }
    window.sessionStorage.setItem('saiv_offline_queue_backup', '[{"payload":{"liveness_challenge_response":"/9j/"}}]')
    await purgeLegacyOfflineQueue()
    expect(deleteDatabase).toHaveBeenCalledWith('saiv')
    expect(window.sessionStorage.getItem('saiv_offline_queue_backup')).toBeNull()
  })

  it('still finishes when the browser has no IndexedDB', async () => {
    await expect(purgeLegacyOfflineQueue()).resolves.toBeUndefined()
  })
})

describe('clearCachedApiResponses', () => {
  afterEach(() => {
    delete (globalThis as { caches?: unknown }).caches
  })

  it('deletes every API response cache and keeps static and page caches', async () => {
    const names = ['saiv-reads-v1', 'saiv-reads-v2', 'saiv-static-v2', 'saiv-pages-v2']
    const deleted: string[] = []
    ;(globalThis as { caches?: unknown }).caches = {
      keys: async () => names,
      delete: async (name: string) => {
        deleted.push(name)
        return true
      },
    }
    await clearCachedApiResponses()
    expect(deleted.sort()).toEqual(['saiv-reads-v1', 'saiv-reads-v2'])
  })

  it('does nothing when Cache Storage is unavailable', async () => {
    await expect(clearCachedApiResponses()).resolves.toBeUndefined()
  })
})
