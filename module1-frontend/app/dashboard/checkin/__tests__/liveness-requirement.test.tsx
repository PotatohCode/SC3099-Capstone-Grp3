import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import type { CheckInRequest } from '@/lib/types'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type RecordedRequest } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls } from '@/lib/liveness/verify'
import { clearOfflineQueue } from '@/lib/services/offline.service'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', role: 'student', camera_consent: true, geolocation_consent: true },
    saveConsent: jest.fn(async () => undefined),
  }),
}))

jest.mock('localforage', () => {
  const store = new Map<string, unknown>()
  const instance = {
    setItem: async (k: string, v: unknown) => store.set(k, v),
    getItem: async (k: string) => store.get(k) ?? null,
    removeItem: async (k: string) => store.delete(k),
    clear: async () => store.clear(),
    iterate: async (fn: (v: unknown) => void) => store.forEach((v) => fn(v)),
  }
  return { createInstance: () => instance }
})

const base = { course_id: 'c1', course_code: 'SC3099', status: 'active', scheduled_start: '', scheduled_end: '', venue_name: 'LT1' }
const photoOnly = { ...base, id: 's1', name: 'Tutorial A', require_liveness_check: false, require_face_match: true }
const nothing = { ...base, id: 's2', name: 'Tutorial B', require_liveness_check: false, require_face_match: false }
const liveOnly = { ...base, id: 's3', name: 'Lecture C', require_liveness_check: true, require_face_match: false }
const legacy = { ...base, id: 's4', name: 'Lecture D' }

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function backend() {
  return stubAdapter((req: RecordedRequest) => {
    if (req.url === '/sessions/my-sessions') return { status: 200, data: [photoOnly, nothing, liveOnly, legacy] }
    if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
    if (req.url === '/checkins/challenge') {
      return { status: 201, data: { challenge_id: 'ch-1', session_id: 's3', sequence: ['blink'], expires_at: '', max_frames: 30 } }
    }
    if (req.url === '/checkins/') return { status: 201, data: { id: 'c1', status: 'approved', risk_score: 0.13, risk_level: 'LOW' } }
    return { status: 404 }
  })
}

async function pick(name: string) {
  render(
    <CheckInProvider>
      <CheckInWizardPage />
    </CheckInProvider>
  )
  await flush()
  await flush()
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }))
  await flush()
  await flush()
}

describe('face step follows the session liveness requirement', () => {
  beforeEach(async () => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    installGeolocation({ latitude: 1.3483, longitude: 103.6831, accuracy: 15 })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
    window.localStorage.clear()
    await clearOfflineQueue()
  })
  afterEach(() => jest.useRealTimers())

  it.each([
    ['Tutorial A', 'face match only'],
    ['Tutorial B', 'neither check'],
  ])('%s (%s): one photo, no challenge, one image submitted', async (name) => {
    const calls = backend()
    await pick(name)
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Take photo' }))
    await flush(3000)
    expect(screen.getByText('Review & submit')).toBeTruthy()
    expect(screen.getByText('Photo taken')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(calls.some((c) => c.url === '/checkins/challenge' || c.url?.endsWith('/verify'))).toBe(false)
    const submit = calls.find((c) => c.url === '/checkins/')!.data as CheckInRequest
    expect(typeof submit.liveness_challenge_response).toBe('string')
    expect(submit.liveness_challenge_frames).toBeUndefined()
    expect(submit.challenge_id).toBeUndefined()
    expect(attemptsUsed('u1', name === 'Tutorial A' ? 's1' : 's2')).toBe(0)
    expect(screen.getByText('Check-in submitted')).toBeTruthy()
  })

  it.each([
    ['Lecture C', 'liveness required'],
    ['Lecture D', 'flag missing'],
  ])('%s (%s): the liveness challenge flow runs', async (name) => {
    const calls = backend()
    await pick(name)
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Take photo' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(500)
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(1)
  })
})
