import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CameraCapture } from '@/app/dashboard/checkin/camera-capture'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import { installCamera, installGeolocation, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type StubReply } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls } from '@/lib/liveness/verify'
import { planCapture } from '@/lib/liveness/challenge'
import { OPEN_WINDOW } from '@/test/fixtures/session'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', role: 'student', camera_consent: true, geolocation_consent: true },
    saveConsent: async () => undefined,
  }),
}))

const challenge = { challenge_id: 'ch-1', session_id: 's1', sequence: ['blink', 'turn_left'], expires_at: '', max_frames: 30 }
const CAPTURE_MS = planCapture(['blink', 'turn_left'], 30)!.durationMs
const UNREACHABLE: Array<[string, StubReply]> = [
  ['502', { status: 502 }],
  ['504', { status: 504 }],
  ['no response', { network: true }],
]

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

/** Renders the face-check step alone and returns its callbacks. */
function renderCapture() {
  const onComplete = jest.fn()
  const onServerUnreachable = jest.fn()
  render(
    <CameraCapture sessionId="s1" photoMode={false} onComplete={onComplete} onReselectSession={jest.fn()} onServerUnreachable={onServerUnreachable} />
  )
  return { onComplete, onServerUnreachable }
}

describe('face check when the server is unreachable', () => {
  beforeEach(() => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
  })
  afterEach(() => jest.useRealTimers())

  it.each(UNREACHABLE)('challenge %s: uses no try and sends the student back', async (_, reply) => {
    stubAdapter(() => reply)
    const { onComplete, onServerUnreachable } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3500)
    expect(attemptsUsed('u1', 's1')).toBe(0)
    expect(onComplete).not.toHaveBeenCalled()
    expect(onServerUnreachable).toHaveBeenCalledTimes(1)
  })

  it.each(UNREACHABLE)('verify %s after capture: uses no try and sends the student back', async (_, reply) => {
    stubAdapter((req) => (req.url === '/checkins/challenge' ? { status: 201, data: challenge } : reply))
    const { onComplete, onServerUnreachable } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(CAPTURE_MS + 200)
    expect(attemptsUsed('u1', 's1')).toBe(0)
    expect(onComplete).not.toHaveBeenCalled()
    expect(onServerUnreachable).toHaveBeenCalledTimes(1)
  })

  it('a real failed check still uses a try', async () => {
    stubAdapter((req) =>
      req.url === '/checkins/challenge' ? { status: 201, data: challenge } : { status: 200, data: { result: 'failed', attempts_left: 2 } }
    )
    const { onServerUnreachable } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(CAPTURE_MS + 200)
    expect(attemptsUsed('u1', 's1')).toBe(1)
    expect(onServerUnreachable).not.toHaveBeenCalled()
  })

  it('the wizard returns to the session list and says it cannot connect', async () => {
    installGeolocation({ latitude: 1.3483, longitude: 103.6831, accuracy: 10 })
    let down = false
    stubAdapter((req) => {
      if (down) return { status: 502 }
      if (req.url === '/sessions/my-sessions') {
        return { status: 200, data: [{ id: 's1', course_id: 'c1', name: 'Lecture 7', status: 'active', venue_name: 'LT1', ...OPEN_WINDOW }] }
      }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    fireEvent.click(await screen.findByRole('button', { name: /Lecture 7/ }))
    await flush()
    await flush()
    down = true
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
    await flush(100)
    expect(screen.getByText('Unable to connect to server.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Face check' })).toBeNull()
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })
})
