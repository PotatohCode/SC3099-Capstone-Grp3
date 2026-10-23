import { act, renderHook } from '@testing-library/react'
import type { User } from '@/lib/types'

const syncQueuedCheckIns = jest.fn(async () => ({ synced: 1, failed: 0, dropped: 0 }))
jest.mock('@/lib/services/offline.service', () => ({
  getQueueLength: async () => 1,
  queueCheckIn: jest.fn(),
  syncQueuedCheckIns: (...args: unknown[]) => syncQueuedCheckIns(...(args as [])),
}))

let mockUser: User | null = null
jest.mock('@/lib/hooks/useAuth', () => ({ useAuth: () => ({ user: mockUser }) }))

import { useOfflineSync } from '@/lib/hooks/useOfflineSync'

const student: User = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student' }

describe('useOfflineSync face gate', () => {
  beforeEach(() => syncQueuedCheckIns.mockClear())

  it('does not replay queued check-ins while the student has no registered face', async () => {
    mockUser = { ...student, face_enrolled: false }
    const { result } = renderHook(() => useOfflineSync())
    expect(result.current.syncBlocked).toBe(true)
    await act(async () => {
      await result.current.syncNow()
      window.dispatchEvent(new Event('online'))
    })
    expect(syncQueuedCheckIns).not.toHaveBeenCalled()
  })

  it('replays queued check-ins once a face is registered', async () => {
    mockUser = { ...student, face_enrolled: true }
    const { result } = renderHook(() => useOfflineSync())
    expect(result.current.syncBlocked).toBe(false)
    await act(async () => {
      await result.current.syncNow()
    })
    expect(syncQueuedCheckIns).toHaveBeenCalledWith('u1')
  })
})
