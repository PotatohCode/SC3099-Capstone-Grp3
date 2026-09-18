'use client'

/**
 * Task 1.8: "Listen to online/offline events, show sync status UI"
 * Component tree Section 2.1: "useOfflineSync() [Queue management + SW communication]"
 */

import { useCallback, useEffect, useState } from 'react'
import {
  getQueueLength,
  queueCheckIn as queueCheckInService,
  syncQueuedCheckIns,
  type SyncResult,
} from '@/lib/services/offline.service'
import type { CheckInRequest } from '@/lib/types'

export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(true)
  const [queueLength, setQueueLength] = useState(0)
  const [isSyncing, setIsSyncing] = useState(false)
  const [lastSyncResult, setLastSyncResult] = useState<SyncResult | null>(null)

  const refreshQueueLength = useCallback(async () => {
    setQueueLength(await getQueueLength())
  }, [])

  const syncNow = useCallback(async () => {
    if (isSyncing) return
    setIsSyncing(true)
    try {
      const result = await syncQueuedCheckIns()
      setLastSyncResult(result)
      await refreshQueueLength()
      return result
    } finally {
      setIsSyncing(false)
    }
  }, [isSyncing, refreshQueueLength])

  const queueCheckIn = useCallback(
    async (payload: CheckInRequest) => {
      const item = await queueCheckInService(payload)
      await refreshQueueLength()
      return item
    },
    [refreshQueueLength]
  )

  useEffect(() => {
    setIsOnline(typeof navigator !== 'undefined' ? navigator.onLine : true)
    refreshQueueLength()

    function handleOnline() {
      setIsOnline(true)
      // Task 1.8: "Implement offline check-in queue + sync on reconnect"
      syncNow()
    }
    function handleOffline() {
      setIsOnline(false)
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return {
    isOnline,
    queueLength,
    isSyncing,
    lastSyncResult,
    syncNow,
    queueCheckIn,
    refreshQueueLength,
  }
}
