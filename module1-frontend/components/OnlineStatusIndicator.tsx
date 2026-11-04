'use client'

/** Header badge showing whether the device is online; check-ins need a connection. */
import { useOnlineStatus } from '@/lib/hooks/useOnlineStatus'

export function OnlineStatusIndicator() {
  const isOnline = useOnlineStatus()
  return (
    <div className={`flex items-center gap-1.5 text-xs ${isOnline ? 'text-green-600' : 'text-red-600'}`} aria-live="polite">
      <span className={`h-2 w-2 rounded-full ${isOnline ? 'bg-green-500' : 'bg-red-500'}`} />
      {isOnline ? 'Online' : 'Offline'}
    </div>
  )
}
