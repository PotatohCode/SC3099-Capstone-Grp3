/** Current time in milliseconds, refreshed on an interval so time-based UI updates without a reload. */
import { useEffect, useState } from 'react'

/** Re-renders every intervalMs with the latest time from clock (device time by default). */
export function useNow(intervalMs = 15000, clock: () => number = Date.now): number {
  const [now, setNow] = useState(() => clock())
  useEffect(() => {
    const id = setInterval(() => setNow(clock()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs, clock])
  return now
}
