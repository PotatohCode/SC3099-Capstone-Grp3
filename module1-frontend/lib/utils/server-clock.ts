/** Server-aligned time: device clock plus an offset measured from the backend's Date header, so a wrong phone clock doesn't matter. */
import httpClient from '@/lib/utils/http-client'
import { API_ROOT_URL } from '@/lib/config'

let offsetMs = 0

/** Current time in milliseconds as the server sees it (device time if never synced). */
export function serverNow(): number {
  return Date.now() + offsetMs
}

/** Offset in milliseconds applied to the device clock. */
export function serverOffsetMs(): number {
  return offsetMs
}

/** Measures the offset from GET /health's Date header; keeps the previous offset when the header is missing or unreadable. */
export async function syncServerClock(): Promise<void> {
  try {
    const sent = Date.now()
    const response = await httpClient.get('/health', { baseURL: API_ROOT_URL, timeout: 5000 })
    const received = Date.now()
    const header = response.headers?.date
    const server = typeof header === 'string' ? Date.parse(header) : NaN
    if (Number.isNaN(server)) return
    // Date header drops milliseconds; +500 ms is the expected midpoint
    offsetMs = server + 500 - (sent + received) / 2
  } catch {
    // Unreachable server: keep the last known offset
  }
}

/** Test hook to reset or force the offset. */
export function setServerOffsetForTests(ms: number): void {
  offsetMs = ms
}
