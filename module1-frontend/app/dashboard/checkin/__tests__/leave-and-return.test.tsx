import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import type { CheckInRequest } from '@/lib/types'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type RecordedRequest, type StubReply } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls } from '@/lib/liveness/verify'
import { requestCheckInRestart } from '@/lib/checkin/restart'
import { clearOfflineQueue } from '@/lib/services/offline.service'
import httpClient from '@/lib/utils/http-client'
import type { InternalAxiosRequestConfig } from 'axios'

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

function delayRequests(match: (config: InternalAxiosRequestConfig) => boolean, ms: number) {
  const inner = httpClient.defaults.adapter as (config: InternalAxiosRequestConfig) => Promise<unknown>
  const delayed = async (config: InternalAxiosRequestConfig) => {
    if (match(config)) await new Promise((resolve) => setTimeout(resolve, ms))
    return inner(config)
  }
  httpClient.defaults.adapter = delayed as typeof httpClient.defaults.adapter
}

async function restart() {
  await act(async () => {
    requestCheckInRestart()
  })
  await flush()
  await flush()
}

async function reopen() {
  const view = openPage()
  await flush()
  await flush()
  await flush()
  return view
}

describe('leaving a check-in and coming back', () => {
  let geo: jest.Mock
  beforeEach(async () => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    geo = installGeolocation({ latitude: 1.3483, longitude: 103.6831, accuracy: 15 })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
    window.localStorage.clear()
    await clearOfflineQueue()
  })
  afterEach(() => jest.useRealTimers())

  it('starts again at the session list after leaving before Start', async () => {
    const calls = backend()
    const first = openPage()
    await flush()
    await chooseLecture7()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    first.unmount()

    await reopen()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(geo).toHaveBeenCalledTimes(1)
    expect(calls.some((c) => c.url === '/checkins/challenge')).toBe(false)
    expect(Object.keys(window.localStorage).some((k) => k.startsWith('saiv_checkin_progress'))).toBe(false)
  })

  it('keeps a try used by leaving after Start when the student picks the session again', async () => {
    const calls = backend()
    const first = openPage()
    await flush()
    await chooseLecture7()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(1000)
    first.unmount()
    expect(attemptsUsed('u1', 's1')).toBe(1)

    await reopen()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
    await chooseLecture7()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    expect(screen.getByText('You have 2 tries left.')).toBeTruthy()
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(1)
  })

  it('stops further face checks once three Starts were abandoned, and the student can still submit for review', async () => {
    const calls = backend({ checkin: { status: 201, data: { id: 'c1', status: 'flagged', risk_score: 0.67, risk_level: 'HIGH' } } })
    for (let i = 0; i < 3; i++) {
      const view = await reopen()
      await chooseLecture7()
      fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
      await flush(500)
      view.unmount()
    }
    expect(attemptsUsed('u1', 's1')).toBe(3)

    await reopen()
    await chooseLecture7()
    expect(screen.getByText('No face-check tries left')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
    expect(screen.getByText('Review & submit')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    const submit = calls.find((c) => c.url === '/checkins/')!.data as CheckInRequest
    expect(submit.liveness_challenge_response).toBeUndefined()
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(3)
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })

  it('a restart request (nav "Check In" on this page) goes back to the session list and stops the camera', async () => {
    const camera = installCamera()
    backend()
    await reopen()
    await chooseLecture7()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(500)
    expect(attemptsUsed('u1', 's1')).toBe(1)

    await act(async () => {
      requestCheckInRestart()
    })
    await flush()
    await flush()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
    expect(camera.track.stop).toHaveBeenCalled()
    expect(attemptsUsed('u1', 's1')).toBe(1)

    await chooseLecture7()
    expect(screen.getByText('You have 2 tries left.')).toBeTruthy()
  })

  it('ignores a restart while a check-in is being submitted, so the result still shows', async () => {
    const calls = backend({ checkin: { status: 201, data: { id: 'c1', status: 'flagged', risk_score: 0.67, risk_level: 'HIGH' } } })
    for (let i = 0; i < 3; i++) {
      const view = await reopen()
      await chooseLecture7()
      fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
      await flush(500)
      view.unmount()
    }
    delayRequests((config) => config.url === '/checkins/', 3000)
    await reopen()
    await chooseLecture7()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush(100)
    await restart()
    expect(screen.queryByText('Step 1 of 4: Session')).toBeNull()
    await flush(3000)
    expect(calls.filter((c) => c.url === '/checkins/')).toHaveLength(1)
    expect(screen.getByText('Check-in submitted')).toBeTruthy()

    await restart()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
  })

  it('a restart during the pre-check after picking a session keeps the student on the list', async () => {
    backend()
    delayRequests((config) => config.url === '/checkins/my-checkins' && !!(config.params as { course_id?: string } | undefined)?.course_id, 1500)
    await reopen()
    fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
    await flush(100)
    await restart()
    await flush(3000)
    await flush()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
  })

  it('removes saved-session keys left by older builds', async () => {
    backend()
    window.localStorage.setItem('saiv_checkin_progress:u1', JSON.stringify({ sessionId: 's1', savedAt: Date.now() }))
    await reopen()
    expect(window.localStorage.getItem('saiv_checkin_progress:u1')).toBeNull()
    expect(screen.getByText('Step 1 of 4: Session')).toBeTruthy()
  })
})
