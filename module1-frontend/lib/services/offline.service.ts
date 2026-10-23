/**
 * Task 1.8 - Offline-First PWA Capabilities
 * Component tree Section 2.1: "offline.service.ts [IndexedDB storage + sync - Task 1.8]"
 * Decision 3 (Section 9): "Offline Queue: IndexedDB + sessionStorage backup"
 *
 * Stores check-ins submitted while offline in IndexedDB (via localforage) so they can
 * be replayed once connectivity returns. A lightweight mirror is also kept in
 * sessionStorage as a backup in case IndexedDB is unavailable/cleared mid-session
 * (Section 7 Risk Analysis: "Offline Queue Data Loss").
 */

import localforage from 'localforage'
import type { CheckInRequest, CheckInResponse } from '@/lib/types'
import { submitCheckIn } from '@/lib/services/checkin.service'
import { classifyCheckInError } from '@/lib/checkin/errors'
import { toOfflinePayload } from '@/lib/checkin/payload'
import { parseApiError } from '@/lib/utils/api-error'

export type QueuedCheckInStatus = 'pending' | 'syncing' | 'failed'

export interface QueuedCheckIn {
  localId: string
  userId?: string
  payload: CheckInRequest
  queuedAt: string
  status: QueuedCheckInStatus
  attempts: number
  lastError?: string
}

const SESSION_BACKUP_KEY = 'saiv_offline_queue_backup'

const checkinStore = localforage.createInstance({
  name: 'saiv',
  storeName: 'offline_checkins',
})

function generateLocalId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function backupToSessionStorage(items: QueuedCheckIn[]): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(SESSION_BACKUP_KEY, JSON.stringify(items))
  } catch {
    // sessionStorage quota exceeded or unavailable - IndexedDB remains source of truth.
  }
}

async function readAllFromStore(): Promise<QueuedCheckIn[]> {
  const items: QueuedCheckIn[] = []
  await checkinStore.iterate<QueuedCheckIn, void>((value) => {
    items.push(value)
  })
  return items.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt))
}

/** Restores the sessionStorage backup into IndexedDB (used if IndexedDB was empty/cleared). */
async function hydrateFromSessionBackupIfEmpty(): Promise<void> {
  const existing = await readAllFromStore()
  if (existing.length > 0) return
  if (typeof window === 'undefined') return
  const raw = window.sessionStorage.getItem(SESSION_BACKUP_KEY)
  if (!raw) return
  try {
    const backedUp = JSON.parse(raw) as QueuedCheckIn[]
    for (const item of backedUp) {
      await checkinStore.setItem(item.localId, item)
    }
  } catch {
    // Corrupt backup - ignore.
  }
}

export async function queueCheckIn(payload: CheckInRequest, userId: string): Promise<QueuedCheckIn> {
  await hydrateFromSessionBackupIfEmpty()
  const item: QueuedCheckIn = {
    localId: generateLocalId(),
    userId,
    payload: toOfflinePayload(payload),
    queuedAt: new Date().toISOString(),
    status: 'pending',
    attempts: 0,
  }
  await checkinStore.setItem(item.localId, item)
  backupToSessionStorage(await readAllFromStore())
  return item
}

export async function getQueuedCheckIns(): Promise<QueuedCheckIn[]> {
  await hydrateFromSessionBackupIfEmpty()
  return readAllFromStore()
}

export async function getQueueLength(): Promise<number> {
  return (await getQueuedCheckIns()).length
}

async function removeQueuedCheckIn(localId: string): Promise<void> {
  await checkinStore.removeItem(localId)
  backupToSessionStorage(await readAllFromStore())
}

async function updateQueuedCheckIn(item: QueuedCheckIn): Promise<void> {
  await checkinStore.setItem(item.localId, item)
  backupToSessionStorage(await readAllFromStore())
}

export interface SyncResult {
  succeeded: number
  failed: number
  responses: CheckInResponse[]
}

/** True when a failed sync may be retried later (no response, 401, 429 or 5xx); any other server answer is final. */
export function isRetryableSyncError(error: unknown): boolean {
  const parsed = parseApiError(error)
  if (parsed.isNetwork || parsed.status === null) return true
  return parsed.status === 401 || parsed.status === 429 || parsed.status >= 500
}

let syncInFlight: Promise<SyncResult> | null = null

/** Sends this user's queued check-ins once (concurrent calls share one run); final server answers remove items, retryable failures stay queued. */
export function syncQueuedCheckIns(userId: string): Promise<SyncResult> {
  if (!syncInFlight) {
    syncInFlight = runSync(userId).finally(() => {
      syncInFlight = null
    })
  }
  return syncInFlight
}

async function runSync(userId: string): Promise<SyncResult> {
  const items = await getQueuedCheckIns()
  const result: SyncResult = { succeeded: 0, failed: 0, responses: [] }

  for (const item of items) {
    if (!item.userId) {
      await removeQueuedCheckIn(item.localId)
      continue
    }
    if (item.userId !== userId) continue
    item.status = 'syncing'
    await updateQueuedCheckIn(item)
    try {
      const response = await submitCheckIn(item.payload)
      result.succeeded += 1
      result.responses.push(response)
      await removeQueuedCheckIn(item.localId)
    } catch (error) {
      result.failed += 1
      if (!isRetryableSyncError(error)) {
        await removeQueuedCheckIn(item.localId)
        continue
      }
      item.status = 'failed'
      item.attempts += 1
      item.lastError = classifyCheckInError(error, true).message
      await updateQueuedCheckIn(item)
    }
  }

  return result
}

export async function clearOfflineQueue(): Promise<void> {
  await checkinStore.clear()
  if (typeof window !== 'undefined') {
    window.sessionStorage.removeItem(SESSION_BACKUP_KEY)
  }
}

// --- Generic cached-reads helpers (used to support Stale-While-Revalidate UX) ------
const cacheStore = localforage.createInstance({
  name: 'saiv',
  storeName: 'cached_reads',
})

export async function getCachedRead<T>(key: string): Promise<T | null> {
  return cacheStore.getItem<T>(key)
}

export async function setCachedRead<T>(key: string, value: T): Promise<void> {
  await cacheStore.setItem(key, value)
}
