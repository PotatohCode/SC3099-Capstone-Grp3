import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import type { CheckInRequest } from '@/lib/types'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type RecordedRequest, type StubReply } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls } from '@/lib/liveness/verify'
import { readProgress } from '@/lib/checkin/progress'
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

function makeSession(id: string, name: string) {
  return { id, course_id: 'c1', course_code: 'SC3099', name, status: 'active', scheduled_start: '', scheduled_end: '', venue_name: 'LT1' }
}

const s1 = makeSession('s1', 'Lecture 7')
const s2 = makeSession('s2', 'Lecture 8')

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function backend(options: { history?: () => unknown[]; historyFails?: () => boolean; checkin?: StubReply } = {}) {
  let challengeCount = 0
  return stubAdapter((req: RecordedRequest) => {
    if (req.url === '/sessions/my-sessions') return { status: 200, data: [s1, s2] }
    if (req.url === '/checkins/my-checkins') {
      if (options.historyFails?.()) return { status: 500 }
      return { status: 200, data: options.history ? options.history() : [] }
    }
    if (req.url === '/checkins/challenge') {
      challengeCount++
      return { status: 201, data: { challenge_id: `ch-${challengeCount}`, session_id: 's1', sequence: ['blink', 'turn_left'], expires_at: '', max_frames: 30 } }
    }
    if (req.url?.endsWith('/verify')) return { status: 200, data: { result: 'unverified', attempts_left: 3 } }
    if (req.url === '/checkins/') return options.checkin ?? { status: 500 }
    return { status: 404 }
  })
}

function openPage() {
  return render(
    <CheckInProvider>
      <CheckInWizardPage />
    </CheckInProvider>
  )
}

async function chooseLecture7() {
  fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
  await flush()
  await flush()
}

describe('resuming a check-in after leaving the page', () => {
  let geo: jest.Mock
  beforeEach(async () => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    geo = installGeolocation({ latitude: 1.3483, longitude: 103.6831, accuracy: 15 })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
    await clearOfflineQueue()
  })
  afterEach(() => jest.useRealTimers())

  it('returns to the chosen session before Start, asking for location again', async () => {
    const calls = backend()
    const first = openPage()
    await flush()
    await chooseLecture7()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(geo).toHaveBeenCalledTimes(1)
    first.unmount()

    openPage()
    await flush()
    await flush()
    await flush()
    expect(screen.queryByRole('button', { name: /Lecture 8/ })).toBeNull()
    expect(screen.getByText('Lecture 7')).toBeTruthy()
    expect(screen.getByText(/Checking in to:/)).toBeTruthy()
    expect(geo).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
    expect(screen.queryByText(/tries left|try left/)).toBeNull()
    expect(calls.some((c) => c.url === '/checkins/challenge')).toBe(false)
  })

  it('uses up a try when the student leaves after Start, and lets them carry on', async () => {
    const calls = backend()
    const first = openPage()
    await flush()
    await chooseLecture7()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(1000)
    first.unmount()
    expect(attemptsUsed('u1', 's1')).toBe(1)

    openPage()
    await flush()
    await flush()
    await flush()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(screen.getByText('You have 2 tries left.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(1)
  })

  it('stops further face checks once three Starts were abandoned, and the student can still submit for review', async () => {
    const calls = backend({ checkin: { status: 201, data: { id: 'c1', status: 'flagged', risk_score: 0.67, risk_level: 'HIGH' } } })
    for (let i = 0; i < 3; i++) {
      const view = openPage()
      await flush()
      if (i === 0) await chooseLecture7()
      else {
        await flush()
        await flush()
      }
      fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
      await flush(500)
      view.unmount()
    }
    expect(attemptsUsed('u1', 's1')).toBe(3)

    openPage()
    await flush()
    await flush()
    await flush()
    expect(screen.getByText('No face-check tries left')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
    expect(screen.getByText('Review & submit')).toBeTruthy()
    expect(screen.getByText(/Your liveliness check was unsuccessful/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    const submit = calls.find((c) => c.url === '/checkins/')!.data as CheckInRequest
    expect(submit.liveness_challenge_response).toBeUndefined()
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(3)
    expect(readProgress('u1')).toBeNull()
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })

  it('forgets the saved session when the student goes Back to the session list', async () => {
    backend()
    const first = openPage()
    await flush()
    await chooseLecture7()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await flush()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await flush()
    expect(readProgress('u1')).toBeNull()
    first.unmount()
    openPage()
    await flush()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
  })

  it('does not auto-resume while check-in history is unavailable, but keeps the saved session', async () => {
    let failing = false
    backend({ historyFails: () => failing })
    const first = openPage()
    await flush()
    await chooseLecture7()
    first.unmount()
    failing = true
    openPage()
    await flush()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
    expect(readProgress('u1')).toBe('s1')
  })

  it('does not resume a session that was checked in elsewhere, and forgets it', async () => {
    let done: unknown[] = []
    backend({ history: () => done })
    const first = openPage()
    await flush()
    await chooseLecture7()
    first.unmount()
    done = [{ id: 'c1', session_id: 's1', session_name: 'Lecture 7', status: 'approved', checked_in_at: '2026-10-26T02:00:00' }]
    openPage()
    await flush()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
    expect(readProgress('u1')).toBeNull()
  })
})
