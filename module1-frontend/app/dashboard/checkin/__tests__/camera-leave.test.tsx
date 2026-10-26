import { act, fireEvent, render, screen } from '@testing-library/react'
import { CameraCapture } from '@/app/dashboard/checkin/camera-capture'
import type { CapturedMedia } from '@/lib/checkin/payload'
import { installCamera, installPermissions } from '@/test/browser-mocks'
import { stubAdapter, type StubReply } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls, startAttempt } from '@/lib/liveness/verify'
import { planCapture } from '@/lib/liveness/challenge'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'student', camera_consent: true }, saveConsent: jest.fn(async () => undefined) }),
}))

const CAPTURE_MS = planCapture(['blink', 'turn_left'], 30)!.durationMs
const challenge = { challenge_id: 'ch-1', session_id: 's1', sequence: ['blink', 'turn_left'], expires_at: '', max_frames: 30 }

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

async function delayedBackend(replies: { challenge: StubReply; verify?: StubReply }) {
  let releaseChallenge: () => void = () => undefined
  let releaseVerify: () => void = () => undefined
  const challengeGate = new Promise<void>((r) => (releaseChallenge = r))
  const verifyGate = new Promise<void>((r) => (releaseVerify = r))
  stubAdapter((req) => {
    if (req.url === '/checkins/challenge') return replies.challenge
    if (req.url?.endsWith('/verify')) return replies.verify ?? { status: 200, data: { result: 'passed', attempts_left: 2 } }
    return { status: 404 }
  })
  const { default: httpClient } = await import('@/lib/utils/http-client')
  const stubbed = httpClient.defaults.adapter as (c: unknown) => Promise<unknown>
  httpClient.defaults.adapter = (async (config: { url?: string }) => {
    if (config.url === '/checkins/challenge') await challengeGate
    if (config.url?.endsWith('/verify')) await verifyGate
    return stubbed(config)
  }) as never
  return { releaseChallenge, releaseVerify }
}

function renderCapture(photoMode = false) {
  const onComplete = jest.fn<void, [CapturedMedia]>()
  const view = render(<CameraCapture sessionId="s1" photoMode={photoMode} onComplete={onComplete} onReselectSession={jest.fn()} />)
  return { onComplete, unmount: view.unmount }
}

describe('leaving the face check part-way', () => {
  beforeEach(() => {
    resetVerifyCalls()
    jest.useFakeTimers()
    installCamera()
    installPermissions('granted')
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
  })
  afterEach(() => jest.useRealTimers())

  it('keeps the try used when the student leaves while the challenge loads and the request then fails', async () => {
    const { releaseChallenge } = await delayedBackend({ challenge: { status: 503, data: { code: 'CHALLENGE_UNAVAILABLE' } } })
    const { onComplete, unmount } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(attemptsUsed('u1', 's1')).toBe(1)
    unmount()
    releaseChallenge()
    await flush(5000)
    expect(attemptsUsed('u1', 's1')).toBe(1)
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('drops a verify result that arrives after the student has left', async () => {
    const { releaseChallenge, releaseVerify } = await delayedBackend({ challenge: { status: 201, data: challenge } })
    releaseChallenge()
    const { onComplete, unmount } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(CAPTURE_MS + 200)
    expect(screen.getByText('Checking your movements...')).toBeTruthy()
    unmount()
    releaseVerify()
    await flush()
    expect(onComplete).not.toHaveBeenCalled()
    expect(attemptsUsed('u1', 's1')).toBe(1)
  })

  it('applies the 3-try limit in photo mode too', async () => {
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    stubAdapter(() => ({ status: 404 }))
    renderCapture(true)
    await flush()
    expect(screen.getByText('No face-check tries left')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Take photo' })).toBeNull()
  })
})
