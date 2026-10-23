import { act, fireEvent, render, screen } from '@testing-library/react'
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import type { CheckInRequest } from '@/lib/types'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type RecordedRequest, type StubReply } from '@/test/axios-stub'

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

const session = {
  id: 's1',
  course_id: 'c1',
  course_code: 'SC3099',
  name: 'Lecture 7',
  status: 'active',
  scheduled_start: '2026-10-22T08:00:00',
  scheduled_end: '2026-10-22T10:00:00',
  venue_name: 'LT1',
}

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function backend(checkinReplies: StubReply[]) {
  let challengeCount = 0
  return stubAdapter((req: RecordedRequest) => {
    if (req.url === '/sessions/my-sessions') return { status: 200, data: [session] }
    if (req.url === '/checkins/challenge') {
      challengeCount++
      return {
        status: 201,
        data: { challenge_id: `ch-${challengeCount}`, session_id: 's1', sequence: ['blink', 'turn_right'], expires_at: '', max_frames: 30 },
      }
    }
    if (req.url === '/checkins/') return checkinReplies.shift() ?? { status: 500 }
    return { status: 404 }
  })
}

async function runToConfirm() {
  fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
  await flush()
  await flush()
  fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
  await flush(7400)
  await flush(100)
  expect(screen.getByText('Review & submit')).toBeTruthy()
}

describe('check-in wizard', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    installGeolocation({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 11.75 })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
  })
  afterEach(() => jest.useRealTimers())

  it('runs session, location, face check, confirm and submits the burst payload', async () => {
    const calls = backend([
      { status: 201, data: { id: 'c1', status: 'flagged', risk_score: 0.42, risk_level: 'MEDIUM', distance_from_venue_meters: 12 } },
    ])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    expect(screen.getByText('Completed (2 actions)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    const submit = calls.find((c) => c.url === '/checkins/')!.data as CheckInRequest
    expect(submit).toMatchObject({
      session_id: 's1',
      latitude: 1.3483123,
      longitude: 103.6831456,
      location_accuracy_meters: 11.75,
      challenge_id: 'ch-1',
      challenge_type: 'sequence',
    })
    expect(submit.liveness_challenge_frames).toHaveLength(16)
    expect(submit.device_fingerprint).toMatch(/^web-[0-9a-f-]{36}$/)
    expect(screen.getByText('Check-in submitted')).toBeTruthy()
    expect(screen.getByText('Medium (0.42)')).toBeTruthy()
  })

  it('explains OUTSIDE_SINGAPORE and retries with a new challenge and fresh frames', async () => {
    const calls = backend([
      { status: 403, data: { detail: 'Check-in only allowed from within Singapore', code: 'OUTSIDE_SINGAPORE' } },
      { status: 201, data: { id: 'c1', status: 'rejected', risk_score: 0.81, risk_level: 'CRITICAL' } },
    ])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText('Check-in not available here')).toBeTruthy()
    expect(screen.getByText("Check-in is only available within Singapore. If you're using a VPN, turn it off and try again.")).toBeTruthy()
    expect(screen.getByText('Nothing was saved, so you can try again.')).toBeTruthy()
    const buttons = screen.getAllByRole('button').map((b) => b.textContent)
    expect(buttons.indexOf('Update my location')).toBeLessThan(buttons.indexOf('Redo face check'))

    fireEvent.click(screen.getByRole('button', { name: 'Redo face check' }))
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
    await flush(7400)
    await flush(100)
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()

    const submits = calls.filter((c) => c.url === '/checkins/').map((c) => c.data as CheckInRequest)
    expect(submits).toHaveLength(2)
    expect(submits[0].challenge_id).toBe('ch-1')
    expect(submits[1].challenge_id).toBe('ch-2')
    const reused = submits[1].liveness_challenge_frames!.filter((f) => submits[0].liveness_challenge_frames!.includes(f))
    expect(reused).toEqual([])
    expect(submits[1].latitude).toBe(1.3483123)
    expect(screen.getByText('Critical (0.81)')).toBeTruthy()
  })

  it('Update my location after OUTSIDE_SINGAPORE takes a new reading, then a new face check', async () => {
    const get = installGeolocation({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 11.75 })
    backend([{ status: 403, data: { code: 'OUTSIDE_SINGAPORE' } }])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Update my location' }))
    await flush()
    await flush()
    expect(get).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
  })

  it('disables submit after a failure until a new face check is done', async () => {
    backend([{ status: 500 }])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText('The server had a problem. Please try again.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Submit check-in' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Redo face check' }))
    await flush()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
  })

  it('refuses to submit a challenge older than 80 s', async () => {
    const calls = backend([{ status: 201, data: { id: 'c1', status: 'approved' } }])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    await flush(80_000)
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText("That check took too long. Let's try again.")).toBeTruthy()
    expect(calls.filter((c) => c.url === '/checkins/')).toHaveLength(0)
  })

  it('queues the check-in with one image when offline', async () => {
    const calls = backend([])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    await runToConfirm()
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText('Saved for sync')).toBeTruthy()
    expect(calls.filter((c) => c.url === '/checkins/')).toHaveLength(0)
    const { getQueuedCheckIns } = await import('@/lib/services/offline.service')
    const [queued] = await getQueuedCheckIns()
    expect(queued.payload).not.toHaveProperty('challenge_id')
    expect(queued.payload).not.toHaveProperty('liveness_challenge_frames')
    expect(typeof queued.payload.liveness_challenge_response).toBe('string')
  })

  it('Back from the face check stays on location and lets the student change session', async () => {
    const get = installGeolocation({ latitude: 1.3483123, longitude: 103.6831456, accuracy: 11.75 })
    backend([])
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    expect(screen.getByRole('heading', { name: 'Face check' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await flush()
    await flush()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(get).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await flush()
    expect(await screen.findByRole('button', { name: /Lecture 7/ })).toBeTruthy()
  })

  it('disables Back while a submit is in flight', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((r) => (release = r))
    let challengeCount = 0
    stubAdapter((req: RecordedRequest) => {
      if (req.url === '/sessions/my-sessions') return { status: 200, data: [session] }
      if (req.url === '/checkins/challenge') {
        challengeCount++
        return { status: 201, data: { challenge_id: `ch-${challengeCount}`, session_id: 's1', sequence: ['blink'], expires_at: '', max_frames: 30 } }
      }
      return { status: 201, data: { id: 'c1', status: 'approved' } }
    })
    const { default: httpClient } = await import('@/lib/utils/http-client')
    const original = httpClient.defaults.adapter as (c: InternalAxiosRequestConfig) => Promise<AxiosResponse>
    httpClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      if (config.url === '/checkins/') await gate
      return original(config)
    }
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
    await flush(6000)
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect((screen.getByRole('button', { name: 'Back' }) as HTMLButtonElement).disabled).toBe(true)
    release()
    await flush()
  })
})
