import { act, fireEvent, render, screen } from '@testing-library/react'
import { CameraCapture } from '@/app/dashboard/checkin/camera-capture'
import type { CapturedMedia } from '@/lib/checkin/payload'
import { installCamera, installPermissions } from '@/test/browser-mocks'
import { stubAdapter } from '@/test/axios-stub'
import { attemptsUsed, resetVerifyCalls, startAttempt } from '@/lib/liveness/verify'
import { planCapture } from '@/lib/liveness/challenge'

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

const PLAN = planCapture(['blink', 'turn_left'], 30)!
const CAPTURE_MS = PLAN.durationMs

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
    resetVerifyCalls()
    jest.useFakeTimers()
    saveConsent.mockClear()
    cameraConsent = true
  })
  afterEach(() => jest.useRealTimers())

  it('fetches a challenge on Start, shows each step and delivers a 20-frame burst', async () => {
    const camera = installCamera()
    installPermissions('granted')
    const calls = stubAdapter((req) => {
      if (req.url === '/checkins/challenge') return { status: 201, data: challenge }
      if (req.url?.endsWith('/verify')) return { status: 200, data: { result: 'passed', attempts_left: 2 } }
      return { status: 404 }
    })
    const { onComplete } = renderCapture()
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1)
    expect(calls).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(calls[0]).toMatchObject({ method: 'post', url: '/checkins/challenge', data: { session_id: 's1' } })
    expect(screen.getByText('Step 1 of 2')).toBeTruthy()
    expect(screen.getByText('Close your eyes for 1 second and open them')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    await flush(1000)
    expect(screen.getByText('2')).toBeTruthy()
    await flush(1000)
    expect(screen.getByText('1')).toBeTruthy()
    await flush(1000)
    expect(screen.getByText('Go!')).toBeTruthy()
    await flush(1900)
    expect(screen.getByText('Step 1 of 2')).toBeTruthy()
    await flush(100)
    expect(screen.getByText('Step 2 of 2')).toBeTruthy()
    expect(screen.getByText('Turn your head to your left and look back in the camera within 2 seconds')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.queryByText('Go!')).toBeNull()
    await flush(3000)
    expect(screen.getByText('Go!')).toBeTruthy()
    expect(onComplete).not.toHaveBeenCalled()
    await flush(2000)

    expect(onComplete).toHaveBeenCalledTimes(1)
    const media = onComplete.mock.calls[0][0]
    expect(media.kind).toBe('burst')
    if (media.kind !== 'burst') return
    expect(media.challengeId).toBe('ch-123')
    expect(media.sequence).toEqual(['blink', 'turn_left'])
    expect(media.maxFrames).toBe(30)
    expect(media.frames).toHaveLength(20)
    expect(new Set(media.frames).size).toBe(20)
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
    expect(screen.getByText('Close your eyes for 1 second and open them').closest('[aria-live="assertive"]')).toBeTruthy()
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
    expect(screen.getByRole('alert').textContent).toMatch(/Unsuccessful capture, please retry\.\s*2 tries left\./)
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
    expect(screen.getByRole('alert').textContent).toMatch(/Unsuccessful capture, please retry\./)
    expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
  })

  describe('Skip face check', () => {
    const skipped = { kind: 'none', verification: 'review', skipped: true }

    function confirmSkip() {
      fireEvent.click(screen.getByRole('button', { name: 'Skip face check' }))
      expect(screen.getByText('Skip the face check?')).toBeTruthy()
      expect(screen.getByText(/Your check-in may be flagged\. Please approach your instructor in class to mark your attendance\./)).toBeTruthy()
      fireEvent.click(screen.getByRole('button', { name: 'Skip and continue' }))
    }

    it('is offered before camera permission is asked and never opens the camera', async () => {
      cameraConsent = false
      const camera = installCamera()
      installPermissions('prompt')
      const { onComplete } = renderCapture()
      await flush()
      confirmSkip()
      expect(camera.getUserMedia).not.toHaveBeenCalled()
      expect(onComplete).toHaveBeenCalledWith(skipped)
    })

    it('is offered when the camera is blocked', async () => {
      installCamera()
      installPermissions('denied')
      const { onComplete } = renderCapture()
      await flush()
      expect(screen.getByText(/Camera access is blocked for this site/)).toBeTruthy()
      confirmSkip()
      expect(onComplete).toHaveBeenCalledWith(skipped)
    })

    it('stops a running camera, sends no request and uses no liveness try', async () => {
      const camera = installCamera()
      installPermissions('granted')
      const calls = stubAdapter(() => ({ status: 404 }))
      const { onComplete } = renderCapture()
      await flush()
      expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
      confirmSkip()
      expect(onComplete).toHaveBeenCalledWith(skipped)
      expect(camera.track.stop).toHaveBeenCalled()
      expect(calls).toHaveLength(0)
      expect(attemptsUsed('u1', 's1')).toBe(0)
    })

    it("Don't skip returns to the check without completing", async () => {
      installCamera()
      installPermissions('granted')
      const { onComplete } = renderCapture()
      await flush()
      fireEvent.click(screen.getByRole('button', { name: 'Skip face check' }))
      await flush()
      expect(document.activeElement).toBe(screen.getByRole('button', { name: "Don't skip" }))
      fireEvent.click(screen.getByRole('button', { name: "Don't skip" }))
      expect(onComplete).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Skip face check' })).toBeTruthy()
      expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
    })

    it('is hidden while a capture is running', async () => {
      installCamera()
      installPermissions('granted')
      stubAdapter(() => ({ status: 201, data: challenge }))
      renderCapture()
      await flush()
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
      await flush(3000)
      expect(screen.queryByRole('button', { name: 'Skip face check' })).toBeNull()
    })
  })

  it('asks for consent first and records it on the backend', async () => {
    cameraConsent = false
    const camera = installCamera()
    installPermissions('prompt')
    renderCapture()
    await flush()
    expect(screen.getByText('Camera access for the face check')).toBeTruthy()
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

  it('goes straight to the first instruction without listing the upcoming actions', async () => {
    installCamera()
    installPermissions('granted')
    stubAdapter(() => ({ status: 201, data: challenge }))
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(screen.queryByText(/You'll be asked to/)).toBeNull()
    expect(screen.queryByText('Get ready')).toBeNull()
    expect(screen.queryByText('Turn your head to your left and look back in the camera within 2 seconds')).toBeNull()
    expect(screen.getByText('Close your eyes for 1 second and open them')).toBeTruthy()
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

describe('CameraCapture attempts (one per Start, 3 per session)', () => {
  beforeEach(() => {
    resetVerifyCalls()
    jest.useFakeTimers()
    saveConsent.mockClear()
    cameraConsent = true
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
  })
  afterEach(() => jest.useRealTimers())

  type Reply = { status: number; data?: unknown } | { network: true }

  function scripted(verifyReplies: Reply[], challengeReply?: Reply) {
    let n = 0
    return stubAdapter((req) => {
      if (req.url === '/checkins/challenge') {
        n++
        return challengeReply ?? { status: 201, data: { ...challenge, challenge_id: `ch-${n}`, attempts_left: 3 } }
      }
      if (req.url?.endsWith('/verify')) return verifyReplies.shift() ?? { status: 200, data: { result: 'unverified', attempts_left: 3 } }
      return { status: 404 }
    })
  }

  async function startAndCapture() {
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(CAPTURE_MS + 200)
  }

  function verifyBodies(calls: Array<{ url?: string; data: unknown }>) {
    return calls.filter((c) => c.url?.endsWith('/verify')).map((c) => (c.data as { frames: string[] }).frames)
  }

  it('submits the same challenge and frames when verify passes on the first Start', async () => {
    const camera = installCamera()
    installPermissions('granted')
    const calls = scripted([{ status: 200, data: { result: 'passed', attempts_left: 2 } }])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    const media = onComplete.mock.calls[0][0]
    expect(media).toMatchObject({ kind: 'burst', challengeId: 'ch-1', verification: 'passed' })
    expect(media.kind === 'burst' && media.frames).toEqual(verifyBodies(calls)[0])
    expect(camera.track.stop).toHaveBeenCalled()
  })

  it('asks for another Start after the first two unverified results, then goes to review with the third burst', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/Unsuccessful capture, please retry\.\s*2 tries left\./)
    await startAndCapture()
    expect(screen.getByRole('alert').textContent).toMatch(/1 try left\./)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(500)
    expect(screen.getByText('This is your last try.')).toBeTruthy()
    await flush(CAPTURE_MS - 300)
    expect(onComplete).toHaveBeenCalledTimes(1)
    const media = onComplete.mock.calls[0][0]
    expect(media).toMatchObject({ kind: 'burst', challengeId: 'ch-3', verification: 'review' })
    expect(media.kind === 'burst' && media.frames).toEqual(verifyBodies(calls)[2])
    expect(calls.filter((c) => c.url === '/checkins/challenge')).toHaveLength(3)
  })

  it('names the missed step when the face service reports one', async () => {
    installCamera()
    installPermissions('granted')
    scripted([{ status: 200, data: { result: 'failed', attempts_left: 2, failed_step: 'turn_left' } }])
    renderCapture()
    await flush()
    await startAndCapture()
    const alert = screen.getByRole('alert').textContent ?? ''
    expect(alert).toMatch(/Unsuccessful capture, please retry\./)
    expect(alert).toMatch(/turn your head to your left/)
    expect(alert).toMatch(/2 tries left\./)
  })

  it('counts a cancelled Start as a try and ends with no image on the third', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([])
    const { onComplete } = renderCapture()
    await flush()
    for (let i = 0; i < 3; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
      await flush(3600)
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
      await flush()
      if (i < 2) expect(screen.getByRole('alert').textContent).toMatch(/Unsuccessful capture, please retry\./)
    }
    expect(onComplete).toHaveBeenCalledTimes(1)
    expect(onComplete.mock.calls[0][0]).toEqual({ kind: 'none', verification: 'review' })
    expect(calls.some((c) => c.url?.endsWith('/verify'))).toBe(false)
  })

  it('mixes outcomes: a cancel, an unverified and a failed Start end in review with the last burst', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([
      { status: 200, data: { result: 'unverified', attempts_left: 3 } },
      { status: 200, data: { result: 'failed', attempts_left: 2 } },
    ])
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3600)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await flush()
    await startAndCapture()
    expect(onComplete).not.toHaveBeenCalled()
    await startAndCapture()
    expect(onComplete.mock.calls[0][0]).toMatchObject({ kind: 'burst', challengeId: 'ch-3', verification: 'review' })
    expect(verifyBodies(calls)).toHaveLength(2)
  })

  it('a pass on the third Start still submits as passed', async () => {
    installCamera()
    installPermissions('granted')
    scripted([
      { status: 200, data: { result: 'unverified', attempts_left: 3 } },
      { status: 400, data: { code: 'CHALLENGE_INVALID' } },
      { status: 200, data: { result: 'passed', attempts_left: 2 } },
    ])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    await startAndCapture()
    await startAndCapture()
    expect(onComplete.mock.calls[0][0]).toMatchObject({ challengeId: 'ch-3', verification: 'passed' })
  })

  it('goes straight to review when the server says no tries are left, whatever the count', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([{ status: 200, data: { result: 'failed', attempts_left: 0 } }])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    expect(onComplete.mock.calls[0][0]).toMatchObject({ kind: 'burst', challengeId: 'ch-1', verification: 'review' })
    const media = onComplete.mock.calls[0][0]
    expect(media.kind === 'burst' && media.frames).toEqual(verifyBodies(calls)[0])
  })

  it('verify 409 on the first Start ends with one frame of this burst', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([{ status: 409, data: { code: 'LIVENESS_ATTEMPTS_EXHAUSTED' } }])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    const frames = verifyBodies(calls)[0]
    expect(onComplete.mock.calls[0][0]).toEqual({ kind: 'photo', photo: frames[Math.floor(frames.length / 2)], verification: 'review' })
    expect(screen.queryByText('Look at the camera and hold still')).toBeNull()
  })

  it('challenge 409 ends with no image and no capture', async () => {
    const camera = installCamera()
    installPermissions('granted')
    const calls = scripted([], { status: 409, data: { code: 'LIVENESS_ATTEMPTS_EXHAUSTED' } })
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(onComplete.mock.calls[0][0]).toEqual({ kind: 'none', verification: 'review' })
    expect(calls.some((c) => c.url?.endsWith('/verify'))).toBe(false)
    expect(camera.track.stop).toHaveBeenCalled()
  })

  it('a third Start that ends in a verify error submits one frame when the challenge cannot be reused', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([
      { status: 429, data: {} },
      { status: 422, data: {} },
      { status: 400, data: { code: 'CHALLENGE_INVALID' } },
    ])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    await startAndCapture()
    await startAndCapture()
    const frames = verifyBodies(calls)[2]
    expect(onComplete.mock.calls[0][0]).toEqual({ kind: 'photo', photo: frames[Math.floor(frames.length / 2)], verification: 'review' })
  })

  it('a third Start that loses the network at verify submits the burst for review without restarting freshness', async () => {
    installCamera()
    installPermissions('granted')
    scripted([{ status: 200, data: { result: 'unverified', attempts_left: 3 } }, { status: 200, data: { result: 'unverified', attempts_left: 3 } }, { network: true }])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    await startAndCapture()
    const before = performance.now()
    await startAndCapture()
    const media = onComplete.mock.calls[0][0]
    expect(media).toMatchObject({ kind: 'burst', challengeId: 'ch-3', verification: 'review' })
    expect(media.kind === 'burst' && media.fetchedAtMs).toBeLessThanOrEqual(before + 50)
  })

  it('keeps a verify in flight when the tab is hidden and no Cancel is offered while verifying', async () => {
    installCamera()
    installPermissions('granted')
    let release: () => void = () => undefined
    stubAdapter((req) => (req.url === '/checkins/challenge' ? { status: 201, data: challenge } : { status: 404 }))
    const httpClient = (await import('@/lib/utils/http-client')).default
    const base = httpClient.defaults.adapter as NonNullable<typeof httpClient.defaults.adapter> & ((c: never) => Promise<never>)
    httpClient.defaults.adapter = ((config: { url?: string }) => {
      if (!config.url?.endsWith('/verify')) return base(config as never)
      return new Promise((resolve) => {
        release = () => resolve({ status: 200, statusText: '200', headers: {}, config: config as never, data: { result: 'passed', attempts_left: 2 } })
      })
    }) as typeof httpClient.defaults.adapter
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    expect(screen.getByText('Checking your movements...')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull()
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    await act(async () => release())
    await flush()
    expect(onComplete.mock.calls[0][0]).toMatchObject({ challengeId: 'ch-123', verification: 'passed' })
  })

  it('offers no further face check once all three Starts are used, without opening the camera', async () => {
    const camera = installCamera()
    installPermissions('granted')
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    startAttempt('u1', 's1')
    const calls = scripted([{ status: 200, data: { result: 'passed', attempts_left: 2 } }])
    const { onComplete } = renderCapture()
    await flush()
    expect(screen.getByText('No face-check tries left')).toBeTruthy()
    expect(screen.getByText(/You've used all 3 face-check tries for this session\. Your liveliness check was unsuccessful/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Skip face check' })).toBeNull()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onComplete.mock.calls[0][0]).toEqual({ kind: 'none', verification: 'review' })
    expect(calls).toHaveLength(0)
  })

  it('shows how many tries are left after an earlier Start', async () => {
    installCamera()
    installPermissions('granted')
    startAttempt('u1', 's1')
    renderCapture()
    await flush()
    expect(screen.getByText('You have 2 tries left.')).toBeTruthy()
  })

  it('restarts the camera after it stops so the student can tap Start again', async () => {
    const camera = installCamera()
    installPermissions('granted')
    const track = Object.assign(new EventTarget(), { stop: jest.fn() })
    camera.getUserMedia.mockImplementation(async () => ({ getTracks: () => [track] }) as unknown as MediaStream)
    scripted([])
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3600)
    await act(async () => {
      track.dispatchEvent(new Event('ended'))
    })
    await flush()
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/Unsuccessful capture, please retry\./)
    expect(camera.getUserMedia).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Start' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start camera' })).toBeNull()
    expect(screen.queryByText('The camera stopped. Please try again.')).toBeNull()
  })

  it('does not use a try when the session has closed or challenges fall back to a photo', async () => {
    installCamera()
    installPermissions('granted')
    scripted([], { status: 400, data: { code: 'SESSION_WINDOW_CLOSED' } })
    renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush()
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })

  it('does not use a try when challenges are unavailable and a photo is taken instead', async () => {
    installCamera()
    installPermissions('granted')
    scripted([], { status: 503, data: { code: 'CHALLENGE_UNAVAILABLE' } })
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await flush(3000)
    expect(onComplete.mock.calls[0][0].kind).toBe('photo')
    expect(attemptsUsed('u1', 's1')).toBe(0)
  })

  it('counts attempts per student', async () => {
    installCamera()
    installPermissions('granted')
    startAttempt('someone-else', 's1')
    startAttempt('someone-else', 's1')
    startAttempt('someone-else', 's1')
    scripted([])
    const { onComplete } = renderCapture()
    await flush()
    await startAndCapture()
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/2 tries left\./)
  })

  it('skips verify when the browser is offline', async () => {
    installCamera()
    installPermissions('granted')
    const calls = scripted([])
    const { onComplete } = renderCapture()
    await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    await flush(CAPTURE_MS + 200)
    expect(calls.some((c) => c.url?.endsWith('/verify'))).toBe(false)
    expect(onComplete.mock.calls[0][0].kind).toBe('burst')
    expect(onComplete.mock.calls[0][0].verification).toBeUndefined()
  })
})
