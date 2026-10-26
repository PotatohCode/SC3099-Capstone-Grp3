import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import type { CheckInRequest } from '@/lib/types'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type RecordedRequest, type StubReply } from '@/test/axios-stub'
import { resetVerifyCalls } from '@/lib/liveness/verify'
import { clearOfflineQueue, queueCheckIn } from '@/lib/services/offline.service'
import { FLAGGED_WARNING } from '@/components/FlaggedNotice'

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
  return {
    id,
    course_id: 'c1',
    course_code: 'SC3099',
    name,
    status: 'active',
    scheduled_start: '2026-10-26T01:00:00',
    scheduled_end: '2026-10-26T03:00:00',
    venue_name: 'LT1',
  }
}

const s1 = makeSession('s1', 'Lecture 7')
const s2 = makeSession('s2', 'Lecture 8')

function historyRow(sessionId: string) {
  return { id: `c-${sessionId}`, session_id: sessionId, session_name: 'x', course_code: 'SC3099', status: 'approved', checked_in_at: '2026-10-26T02:00:00' }
}

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

interface BackendOptions {
  history?: () => StubReply
  checkin?: StubReply
}

function backend({ history = () => ({ status: 200, data: [] }), checkin }: BackendOptions = {}) {
  return stubAdapter((req: RecordedRequest) => {
    if (req.url === '/sessions/my-sessions') return { status: 200, data: [s1, s2] }
    if (req.url === '/checkins/my-checkins') return history()
    if (req.url === '/checkins/') return checkin ?? { status: 500 }
    if (req.url === '/checkins/challenge') return { status: 503 }
    return { status: 404 }
  })
}

function renderWizard() {
  render(
    <CheckInProvider>
      <CheckInWizardPage />
    </CheckInProvider>
  )
}

describe('check-in feedback changes', () => {
  beforeEach(async () => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    installGeolocation({ latitude: 1.3483, longitude: 103.6831, accuracy: 15 })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
    await clearOfflineQueue()
  })
  afterEach(() => jest.useRealTimers())

  it('leaves out sessions the student has already checked in to', async () => {
    backend({ history: () => ({ status: 200, data: [historyRow('s1')] }) })
    renderWizard()
    await flush()
    expect(screen.queryByRole('button', { name: /Lecture 7/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
  })

  it('points to History when every open session is already checked in', async () => {
    backend({ history: () => ({ status: 200, data: [historyRow('s1'), historyRow('s2')] }) })
    renderWizard()
    await flush()
    expect(screen.queryByRole('button', { name: /Lecture/ })).toBeNull()
    expect(screen.getByText(/already checked in to every open session/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'History' }).getAttribute('href')).toBe('/dashboard/history')
  })

  it("leaves out a session with this student's queued offline check-in, but not another student's", async () => {
    await queueCheckIn({ session_id: 's1', latitude: 1.3, longitude: 103.8, device_fingerprint: 'web-x' }, 'u1')
    await queueCheckIn({ session_id: 's2', latitude: 1.3, longitude: 103.8, device_fingerprint: 'web-y' }, 'someone-else')
    backend()
    renderWizard()
    await flush()
    expect(screen.queryByRole('button', { name: /Lecture 7/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
  })

  it('says a hidden session is waiting to sync when only the offline queue has it', async () => {
    await queueCheckIn({ session_id: 's1', latitude: 1.3, longitude: 103.8, device_fingerprint: 'web-x' }, 'u1')
    backend()
    renderWizard()
    await flush()
    expect(screen.getByText(/A check-in you made offline is saved on this device/)).toBeTruthy()
  })

  it('jumps to a waiting-to-sync message when a stale list offers a session queued offline', async () => {
    backend()
    renderWizard()
    await flush()
    await queueCheckIn({ session_id: 's1', latitude: 1.3, longitude: 103.8, device_fingerprint: 'web-x' }, 'u1')
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush()
    expect(screen.getByText('Check-in waiting to sync')).toBeTruthy()
    expect(screen.getByText('Step 4 of 4: Confirm')).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Go to history' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Choose another session' })).toBeTruthy()
  })

  it('carries on with the check-in if the already-checked-in lookup takes over 5 seconds', async () => {
    let tap = false
    const { default: httpClient } = await import('@/lib/utils/http-client')
    backend()
    const stubbed = httpClient.defaults.adapter as (c: unknown) => Promise<unknown>
    httpClient.defaults.adapter = (async (config: { url?: string }) => {
      if (tap && config.url === '/checkins/my-checkins') await new Promise(() => undefined)
      return stubbed(config)
    }) as never
    renderWizard()
    await flush()
    tap = true
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush(4900)
    expect(screen.getByText('Checking...')).toBeTruthy()
    await flush(200)
    await flush()
    expect(screen.queryByText('Checking...')).toBeNull()
    expect(screen.getByText(/Step [23] of 4: (Location|Face check)/)).toBeTruthy()
    expect(screen.queryByText('Already checked in')).toBeNull()
  })

  it('still lists sessions when the check-in history cannot be loaded', async () => {
    backend({ history: () => ({ status: 500 }) })
    renderWizard()
    await flush()
    expect(screen.getByRole('button', { name: /Lecture 7/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
  })

  it('jumps to the last step with the already-checked-in error when the list was stale', async () => {
    let checkedIn = false
    const calls = backend({ history: () => ({ status: 200, data: checkedIn ? [historyRow('s1')] : [] }) })
    renderWizard()
    await flush()
    checkedIn = true
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush()
    expect(screen.getByText('Already checked in')).toBeTruthy()
    expect(screen.getByText(/already checked in to this session/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Go to history' }).getAttribute('href')).toBe('/dashboard/history')
    expect(screen.getByText('Step 4 of 4: Confirm')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Submit check-in' })).toBeNull()
    expect(calls.some((c) => c.url === '/checkins/challenge' || c.url === '/checkins/')).toBe(false)
    expect(calls.filter((c) => c.url === '/checkins/my-checkins')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Choose another session' }))
    await flush()
    expect(screen.queryByRole('button', { name: /Lecture 7/ })).toBeNull()
    expect(screen.getByRole('button', { name: /Lecture 8/ })).toBeTruthy()
  })

  it('skips the face check, submits location with no image and shows the flagged warning', async () => {
    const calls = backend({
      checkin: { status: 201, data: { id: 'c9', status: 'flagged', risk_score: 0.69, risk_level: 'HIGH', distance_from_venue_meters: 5 } },
    })
    renderWizard()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: 'Skip face check' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skip and continue' }))
    await flush()
    expect(screen.getByText('Review & submit')).toBeTruthy()
    expect(screen.getByText('Skipped')).toBeTruthy()
    expect(screen.getByText(/You skipped the face check, so this check-in may be flagged/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    const submit = calls.find((c) => c.url === '/checkins/')!.data as CheckInRequest
    expect(submit).toMatchObject({ session_id: 's1', latitude: 1.3483, longitude: 103.6831, location_accuracy_meters: 15 })
    expect(submit.liveness_challenge_response).toBeUndefined()
    expect(submit.liveness_challenge_frames).toBeUndefined()
    expect(submit.challenge_id).toBeUndefined()
    expect(calls.some((c) => c.url === '/checkins/challenge')).toBe(false)
    expect(screen.getByText('Check-in submitted')).toBeTruthy()
    expect(screen.getByText(FLAGGED_WARNING)).toBeTruthy()
  })

  it('does not show the flagged warning for an approved check-in', async () => {
    backend({ checkin: { status: 201, data: { id: 'c9', status: 'approved', risk_score: 0.1, risk_level: 'LOW' } } })
    renderWizard()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: 'Skip face check' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skip and continue' }))
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText('Check-in submitted')).toBeTruthy()
    expect(screen.queryByText(FLAGGED_WARNING)).toBeNull()
  })

  it('ends at the already-checked-in error with both recovery options when submit finds a duplicate', async () => {
    backend({ checkin: { status: 400, data: { detail: 'Already checked in for this session', code: 'ALREADY_CHECKED_IN' } } })
    renderWizard()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: 'Skip face check' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skip and continue' }))
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Submit check-in' }))
    await flush()
    expect(screen.getByText('Already checked in')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Go to history' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Choose another session' })).toBeTruthy()
  })
})
