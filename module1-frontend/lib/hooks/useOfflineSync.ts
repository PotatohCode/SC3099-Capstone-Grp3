'use client'

/**
 * Task 1.8: "Listen to online/offline events, show sync status UI"
 * Component tree Section 2.1: "useOfflineSync() [Queue management + SW communication]"
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/lib/hooks/useAuth'
import {
  getQueueLength,
  queueCheckIn as queueCheckInService,
  syncQueuedCheckIns,
  type SyncResult,
} from '@/lib/services/offline.service'
import { needsFaceEnrollment } from '@/lib/face/enrollment'
import type { CheckInRequest } from '@/lib/types'

export function useOfflineSync() {
  const { user } = useAuth()
  const userIdRef = useRef<string | null>(user?.id ?? null)
  userIdRef.current = user?.id ?? null
  const blocked = needsFaceEnrollment(user)
  const blockedRef = useRef(blocked)
  blockedRef.current = blocked
  const [isOnline, setIsOnline] = useState(true)
  const [queueLength, setQueueLength] = useState(0)
  const [isSyncing, setIsSyncing] = useState(false)
  const [lastSyncResult, setLastSyncResult] = useState<SyncResult | null>(null)

  const refreshQueueLength = useCallback(async () => {
    setQueueLength(await getQueueLength())
  }, [])

  const syncNow = useCallback(async () => {
    const userId = userIdRef.current
    if (isSyncing || !userId || blockedRef.current) return
    setIsSyncing(true)
    try {
      const result = await syncQueuedCheckIns(userId)
      setLastSyncResult(result)
      await refreshQueueLength()
      return result
    } finally {
      setIsSyncing(false)
    }
  }, [isSyncing, refreshQueueLength])

  const queueCheckIn = useCallback(
    async (payload: CheckInRequest) => {
      const userId = userIdRef.current
      if (!userId) throw new Error('Not signed in')
      const item = await queueCheckInService(payload, userId)
      await refreshQueueLength()
      return item
    },
    [refreshQueueLength]
  )

  const syncNowRef = useRef(syncNow)
  syncNowRef.current = syncNow

  useEffect(() => {
    setIsOnline(typeof navigator !== 'undefined' ? navigator.onLine : true)
    refreshQueueLength()

    function handleOnline() {
      setIsOnline(true)
      // Task 1.8: "Implement offline check-in queue + sync on reconnect"
      syncNowRef.current()
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
    syncBlocked: blocked,
    lastSyncResult,
    syncNow,
    queueCheckIn,
    refreshQueueLength,
  }
}
