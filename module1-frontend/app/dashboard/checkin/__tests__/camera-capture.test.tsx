import { act, fireEvent, render, screen } from '@testing-library/react'
import { CameraCapture } from '@/app/dashboard/checkin/camera-capture'
import type { CapturedMedia } from '@/lib/checkin/payload'
import { installCamera, installPermissions } from '@/test/browser-mocks'
import { stubAdapter } from '@/test/axios-stub'

const saveConsent = jest.fn(async () => undefined)
let cameraConsent: boolean | undefined = true

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'student', camera_consent: cameraConsent }, saveConsent }),
}))

const challenge = {
  challenge_id: 'ch-123',
  session_id: 's1',
  sequence: ['blink', 'turn_left'],
  expires_at: '2026-10-22T10:00:00',
  max_frames: 30,
}

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function renderCapture(photoMode = false) {
  const onComplete = jest.fn<void, [CapturedMedia]>()
  const onReselectSession = jest.fn()
  render(<CameraCapture sessionId="s1" photoMode={photoMode} onComplete={onComplete} onReselectSession={onReselectSession} />)
  return { onComplete, onReselectSession }
}

describe('CameraCapture', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    saveConsent.mockClear()
    cameraConsent = true
  })
  afterEach(() => jest.useRealTimers())

  it('fetches a challenge on Start, shows each step and delivers a 16-frame burst', async () => {
    const camera = installCamera()
    installPermissions('granted')
    const calls = stubAdapter((req) => (req.url === '/checkins/challenge' ? { status: 201, data: challenge } : { status: 404 }))
    const { onComplete } = renderCapture()
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1)
    expect(calls).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(calls[0]).toMatchObject({ method: 'post', url: '/checkins/challenge', data: { session_id: 's1' } })
    expect(screen.getByText('Get ready')).toBeTruthy()

    await flush(3000)
    expect(screen.getByText('Step 1 of 2')).toBeTruthy()
    expect(screen.getByText('Blink a few times')).toBeTruthy()
    await flush(2400)
    expect(screen.getByText('Step 2 of 2')).toBeTruthy()
    expect(screen.getByText('Slowly turn your head to your left')).toBeTruthy()
    await flush(2000)

    expect(onComplete).toHaveBeenCalledTimes(1)
    const media = onComplete.mock.calls[0][0]
    expect(media.kind).toBe('burst')
    if (media.kind !== 'burst') return
    expect(media.challengeId).toBe('ch-123')
    expect(media.sequence).toEqual(['blink', 'turn_left'])
    expect(media.maxFrames).toBe(30)
    expect(media.frames).toHaveLength(16)
    expect(new Set(media.frames).size).toBe(16)
    expect(media.frames.every((f) => !f.startsWith('data:'))).toBe(true)
    expect(camera.track.stop).toHaveBeenCalled()
  })

  it('announces step prompts to screen readers', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 201, data: challenge }))
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3000)
    expect(screen.getByText('Blink a few times').closest('[aria-live="assertive"]')).toBeTruthy()
  })

  it('falls back to a single photo when challenges are unavailable (503)', async () => {
    const camera = installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 503, data: { code: 'CHALLENGE_UNAVAILABLE' } }))
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(screen.getByText('Look at the camera and hold still')).toBeTruthy()
    await flush(3000)
    expect(onComplete).toHaveBeenCalledTimes(1)
    const media = onComplete.mock.calls[0][0]
    expect(media.kind).toBe('photo')
    expect(media.kind === 'photo' && media.photo.startsWith('data:')).toBe(false)
    expect(camera.track.stop).toHaveBeenCalled()
  })

  it('falls back to a single photo when the challenge request gets no response', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ network: true }))
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3000)
    expect(onComplete.mock.calls[0][0].kind).toBe('photo')
  })

  it('skips the challenge in photo mode', async () => {
    installCamera()
    installPermissions('granted')
    const calls = stubAdapter(() => ({ status: 201, data: challenge }))
    const { onComplete } = renderCapture(true)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Take photo' }))
    await flush(3000)
    expect(calls).toHaveLength(0)
    expect(onComplete.mock.calls[0][0].kind).toBe('photo')
  })

  it('offers another session when the session window has closed', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 400, data: { code: 'SESSION_WINDOW_CLOSED' } }))
    const { onComplete, onReselectSession } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(screen.getByText('Check-in for this session is closed.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Choose another session' }))
    expect(onReselectSession).toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('discards frames and asks to retry when the tab is hidden mid-capture', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 201, data: challenge }))
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3600)
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await flush(6000)
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByText("The face check was interrupted. Let's try again.")).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
  })

  it('Cancel aborts the capture', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 201, data: challenge }))
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3600)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await flush(6000)
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('asks for consent first and records it on the backend', async () => {
    cameraConsent = false
    const camera = installCamera()
    installPermissions('prompt')
    renderCapture()
    await flush()
    expect(screen.getByText('Camera access required')).toBeTruthy()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1)
    expect(saveConsent).toHaveBeenCalledWith('camera', true)
    expect(camera.getUserMedia.mock.invocationCallOrder[0]).toBeLessThan(saveConsent.mock.invocationCallOrder[0])
  })

  it('records a browser denial as consent false and shows how to unblock', async () => {
    cameraConsent = false
    installCamera({ deny: true })
    installPermissions('prompt')
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    expect(saveConsent).not.toHaveBeenCalledWith('camera', true)
    expect(saveConsent).toHaveBeenCalledWith('camera', false)
    expect(screen.getByText(/Camera access is blocked for this site/)).toBeTruthy()
  })

  it('shows the blocked message without prompting when the browser already denies the camera', async () => {
    const camera = installCamera()
    installPermissions('denied')
    renderCapture()
    await flush()
    expect(screen.getByText(/Camera access is blocked for this site/)).toBeTruthy()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
  })

  it('retrying from blocked asks the browser first and saves consent only after it grants', async () => {
    cameraConsent = false
    const camera = installCamera({ deny: true })
    installPermissions('prompt')
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    saveConsent.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalledTimes(2)
    expect(saveConsent).not.toHaveBeenCalledWith('camera', true)
  })

  it('lists the actions during the countdown', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 201, data: challenge }))
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(screen.getByText("You'll be asked to: blink, then turn left")).toBeTruthy()
  })

  it('a successful retry from blocked opens one stream and releases it on unmount', async () => {
    cameraConsent = false
    const tracks: Array<{ stop: jest.Mock; stopped: boolean }> = []
    let deny = true
    const getUserMedia = jest.fn(async () => {
      if (deny) throw new DOMException('', 'NotAllowedError')
      const track: { stop: jest.Mock; stopped: boolean } = { stopped: false, stop: jest.fn() }
      track.stop.mockImplementation(() => {
        track.stopped = true
      })
      tracks.push(track)
      return { getTracks: () => [track] } as unknown as MediaStream
    })
    installCamera()
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    installPermissions('prompt')
    const { unmount } = render(<CameraCapture sessionId="s1" photoMode={false} onComplete={jest.fn()} onReselectSession={jest.fn()} />)
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    deny = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await flush()
    await flush()
    expect(tracks).toHaveLength(1)
    unmount()
    expect(tracks.every((t) => t.stopped)).toBe(true)
  })
})
