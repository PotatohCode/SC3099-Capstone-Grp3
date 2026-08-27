'use client'

/**
 * Task 1.8: "online/offline status indicator"
 */

import { useOfflineSync } from '@/lib/hooks/useOfflineSync'

export function OnlineStatusIndicator() {
  const { isOnline, queueLength, isSyncing, syncNow } = useOfflineSync()

  if (isOnline && queueLength === 0) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-green-600" aria-live="polite">
        <span className="h-2 w-2 rounded-full bg-green-500" />
        Online
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" aria-live="polite">
      <span className={`flex items-center gap-1.5 ${isOnline ? 'text-green-600' : 'text-red-600'}`}>
        <span className={`h-2 w-2 rounded-full ${isOnline ? 'bg-green-500' : 'bg-red-500'}`} />
        {isOnline ? 'Online' : 'Offline'}
      </span>
      {queueLength > 0 && (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-700">
          {queueLength} check-in{queueLength === 1 ? '' : 's'} pending sync
        </span>
      )}
      {isOnline && queueLength > 0 && (
        <button
          type="button"
          onClick={() => syncNow()}
          disabled={isSyncing}
          className="min-h-[28px] rounded-md bg-blue-600 px-2 py-1 font-medium text-white disabled:opacity-50"
        >
          {isSyncing ? 'Syncing...' : 'Sync now'}
        </button>
      )}
    </div>
  )
}
