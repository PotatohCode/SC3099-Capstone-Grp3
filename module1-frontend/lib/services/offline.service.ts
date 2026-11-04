/** Removes data the PWA may hold on the device: the retired offline check-in queue and service-worker caches of API responses. */

const LEGACY_DB_NAME = 'saiv'
const LEGACY_QUEUE_BACKUP_KEY = 'saiv_offline_queue_backup'
const API_CACHE_PREFIX = 'saiv-reads-'

/** Deletes the old offline queue (IndexedDB `saiv` and its sessionStorage backup), which could hold face images. */
export async function purgeLegacyOfflineQueue(): Promise<void> {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.removeItem(LEGACY_QUEUE_BACKUP_KEY)
  } catch {}
  if (typeof indexedDB === 'undefined') return
  await new Promise<void>((resolve) => {
    const request = indexedDB.deleteDatabase(LEGACY_DB_NAME)
    request.onsuccess = request.onerror = request.onblocked = () => resolve()
  })
}

/** Deletes cached API responses so the next person on this device can't read the previous student's data. */
export async function clearCachedApiResponses(): Promise<void> {
  if (typeof caches === 'undefined') return
  const names = await caches.keys()
  await Promise.all(names.filter((name) => name.startsWith(API_CACHE_PREFIX)).map((name) => caches.delete(name)))
}
