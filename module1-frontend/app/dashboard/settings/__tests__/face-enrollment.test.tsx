import { act, fireEvent, render, screen } from '@testing-library/react'
import SettingsPage from '@/app/dashboard/settings/page'
import { installCamera } from '@/test/browser-mocks'
import { httpError, stubAdapter, type RecordedRequest, type StubReply } from '@/test/axios-stub'
import httpClient from '@/lib/utils/http-client'
import type { InternalAxiosRequestConfig } from 'axios'
import type { User } from '@/lib/types'

const reauthenticate = jest.fn(async (password: string) => {
  if (password !== 'right') throw new Error('Incorrect password.')
})
const saveConsent = jest.fn(async (_type: string, granted: boolean) => granted)
const refreshUser = jest.fn(async () => undefined)
let mockUser: User = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student', face_enrolled: false }

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: mockUser, reauthenticate, saveConsent, refreshUser }),
}))

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function enrollOk(req: RecordedRequest) {
  if (req.url === '/users/me/face/enroll') {
    return { status: 200, data: { success: true, message: 'ok', face_enrolled: true, quality_score: 0.9 } }
  }
  return { status: 404 }
}

async function openAndPassPassword(password = 'right') {
  fireEvent.click(screen.getByRole('button', { name: 'Register face identity' }))
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await flush()
}

describe('Settings face identity', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    reauthenticate.mockClear()
    saveConsent.mockClear()
    saveConsent.mockImplementation(async (_type: string, granted: boolean) => granted)
    refreshUser.mockClear()
    mockUser = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student', face_enrolled: false }
  })
  afterEach(() => jest.useRealTimers())

  it('shows the status and the right button label', () => {
    stubAdapter(enrollOk)
    const { unmount } = render(<SettingsPage />)
    expect(screen.getByText('Not registered')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Register face identity' })).toBeTruthy()
    unmount()
    mockUser = { ...mockUser, face_enrolled: true }
    render(<SettingsPage />)
    expect(screen.getByText('Registered')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Update face identity' })).toBeTruthy()
  })

  it('a wrong password shows an error and never opens the camera or saves consent', async () => {
    const camera = installCamera()
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword('wrong')
    expect(reauthenticate).toHaveBeenCalledWith('wrong')
    expect(screen.getByRole('alert').textContent).toBe('Incorrect password.')
    expect(screen.queryByRole('button', { name: 'Allow camera access' })).toBeNull()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
    expect(saveConsent).not.toHaveBeenCalled()
    expect(calls).toHaveLength(0)
  })

  it('password, camera grant, consent saved, 5 s countdown, one raw base64 frame enrolled, gate refreshed', async () => {
    const camera = installCamera()
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    expect(camera.getUserMedia).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1)
    expect(saveConsent).toHaveBeenCalledWith('camera', true)
    expect(camera.getUserMedia.mock.invocationCallOrder[0]).toBeLessThan(saveConsent.mock.invocationCallOrder[0])
    expect(screen.getByText('Look at the camera')).toBeTruthy()
    expect(screen.getByTestId('face-countdown').textContent).toBe('5')

    await flush(1000)
    expect(screen.getByTestId('face-countdown').textContent).toBe('4')
    await flush(3999)
    expect(calls).toHaveLength(0)
    expect(camera.track.stop).not.toHaveBeenCalled()
    await flush(1)

    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'post', url: '/users/me/face/enroll' })
    const image = (calls[0].data as { image: string }).image
    expect(image).toMatch(/^[A-Za-z0-9+/=]+$/)
    expect(image.startsWith('data:')).toBe(false)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(refreshUser).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Your face identity is registered. You can now check in.')).toBeTruthy()
  })

  it('a denied camera records consent false and does not enroll', async () => {
    const camera = installCamera({ deny: true })
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    expect(camera.getUserMedia).toHaveBeenCalled()
    expect(saveConsent).toHaveBeenCalledWith('camera', false)
    expect(saveConsent).not.toHaveBeenCalledWith('camera', true)
    expect(screen.getByRole('alert').textContent).toMatch(/Camera access was denied/)
    await flush(6000)
    expect(calls).toHaveLength(0)
  })

  it('stops the camera and does not enroll when consent was not saved on the server', async () => {
    const camera = installCamera()
    saveConsent.mockImplementation(async () => false)
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(6000)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert').textContent).toMatch(/Couldn't save your camera consent/)
  })

  it('shows the backend error and lets the student try again without re-entering the password', async () => {
    installCamera()
    let attempt = 0
    stubAdapter((req) => {
      if (req.url !== '/users/me/face/enroll') return { status: 404 }
      attempt += 1
      return attempt === 1 ? { status: 400, data: { code: 'NO_FACE_DETECTED', detail: 'No face detected in image' } } : enrollOk(req)
    })
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByRole('alert').textContent).toMatch(/No face was detected/)
    expect(refreshUser).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(reauthenticate).toHaveBeenCalledTimes(1)
    expect(attempt).toBe(2)
    expect(refreshUser).toHaveBeenCalledTimes(1)
  })

  it('cancel during the countdown stops the camera and sends nothing', async () => {
    const camera = installCamera()
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(2000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await flush(5000)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Register face identity' })).toBeTruthy()
  })

  it('never writes the captured frame to browser storage', async () => {
    installCamera()
    stubAdapter(enrollOk)
    const setItem = jest.spyOn(Storage.prototype, 'setItem')
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(setItem.mock.calls.some(([, value]) => String(value).includes('RlJBTUU'))).toBe(false)
    setItem.mockRestore()
  })

  it('asks for a reload instead of offering Check In when the user could not be refreshed', async () => {
    installCamera()
    stubAdapter(enrollOk)
    refreshUser.mockImplementationOnce(async () => {
      throw new Error('offline')
    })
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByText(/Reload the page to turn check-in back on/)).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Go to Check In' })).toBeNull()
  })

  it('does not enroll when the camera stops during the countdown', async () => {
    const camera = installCamera()
    const track = Object.assign(new EventTarget(), { stop: jest.fn() })
    camera.getUserMedia.mockImplementation(async () => ({ getTracks: () => [track] }) as unknown as MediaStream)
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(2000)
    await act(async () => {
      track.dispatchEvent(new Event('ended'))
    })
    await flush(4000)
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert').textContent).toMatch(/The camera stopped/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('does not enroll when the camera stops while consent is still saving', async () => {
    const camera = installCamera()
    const track = Object.assign(new EventTarget(), { stop: jest.fn() })
    camera.getUserMedia.mockImplementation(async () => ({ getTracks: () => [track] }) as unknown as MediaStream)
    let finishSave: (value: boolean) => void = () => undefined
    saveConsent.mockImplementation(() => new Promise<boolean>((resolve) => (finishSave = resolve)))
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    await act(async () => {
      track.dispatchEvent(new Event('ended'))
    })
    await act(async () => {
      finishSave(true)
    })
    await flush(6000)
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert').textContent).toMatch(/The camera stopped/)
  })

  it('does not enroll when the page is hidden while consent is still saving', async () => {
    installCamera()
    let finishSave: (value: boolean) => void = () => undefined
    saveConsent.mockImplementation(() => new Promise<boolean>((resolve) => (finishSave = resolve)))
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    await act(async () => {
      finishSave(true)
    })
    await flush(6000)
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert').textContent).toMatch(/The camera stopped/)

    saveConsent.mockImplementation(async (_type: string, granted: boolean) => granted)
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls).toHaveLength(1)
  })

  it('a hidden page before the camera step does not block a later attempt', async () => {
    installCamera()
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls).toHaveLength(1)
  })

  it('does not enroll when the page is hidden during the countdown', async () => {
    const camera = installCamera()
    const calls = stubAdapter(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(2000)
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    await flush(4000)
    expect(calls).toHaveLength(0)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/The camera stopped/)
  })

  it('maps a 503 to the face-service message', async () => {
    installCamera()
    stubAdapter(() => ({ status: 503, data: httpError(503).response?.data ?? { code: 'FACE_SERVICE_UNAVAILABLE' } }))
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByRole('alert').textContent).toMatch(/face service is unavailable/)
  })
})

const CHECK_URL = '/users/me/face/reset-code/check'
const CHECK_OK = { status: 200, data: { required: true, valid: true } }

function stubEnroll(enroll: (req: RecordedRequest) => StubReply, check: (req: RecordedRequest) => StubReply = () => CHECK_OK) {
  const enrolls: RecordedRequest[] = []
  const checks: RecordedRequest[] = []
  stubAdapter((req) => {
    if (req.url === CHECK_URL) {
      checks.push(req)
      return check(req)
    }
    enrolls.push(req)
    return enroll(req)
  })
  return Object.assign(enrolls, { checks })
}

describe('Settings face identity update with an instructor reset code', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    reauthenticate.mockClear()
    saveConsent.mockClear()
    saveConsent.mockImplementation(async (_type: string, granted: boolean) => granted)
    refreshUser.mockClear()
    mockUser = { id: 'u1', email: 's@e.edu', full_name: 'S', role: 'student', face_enrolled: true }
  })
  afterEach(() => jest.useRealTimers())

  async function openUpdate() {
    fireEvent.click(screen.getByRole('button', { name: 'Update face identity' }))
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'right' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
  }

  async function enterCode(value: string) {
    fireEvent.change(screen.getByLabelText('Reset code from your instructor'), { target: { value } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
  }

  it('asks for the code after the password and before the camera, and sends it normalized', async () => {
    const camera = installCamera()
    const calls = stubEnroll(enrollOk)
    render(<SettingsPage />)
    expect(screen.getByText(/you need a one-time reset code from your instructor/)).toBeTruthy()
    await openUpdate()
    expect(screen.getByLabelText('Reset code from your instructor')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Allow camera access' })).toBeNull()
    expect((screen.getByRole('button', { name: 'Continue' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Reset code from your instructor'), { target: { value: ' - ' } })
    expect((screen.getByRole('button', { name: 'Continue' }) as HTMLButtonElement).disabled).toBe(true)
    expect(camera.getUserMedia).not.toHaveBeenCalled()

    expect(document.activeElement).toBe(screen.getByLabelText('Reset code from your instructor'))
    await enterCode('k7qm-4xpa')
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 5:00')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls).toHaveLength(1)
    expect(calls[0].data).toEqual({ image: expect.any(String), reset_code: 'K7QM4XPA' })
    expect(screen.getByText('Your face identity is registered. You can now check in.')).toBeTruthy()
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
  })

  it('first registration never shows the code step or sends reset_code', async () => {
    mockUser = { ...mockUser, face_enrolled: false }
    installCamera()
    const calls = stubEnroll(enrollOk)
    render(<SettingsPage />)
    await openAndPassPassword()
    expect(screen.queryByLabelText('Reset code from your instructor')).toBeNull()
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls[0].data).toEqual({ image: expect.any(String) })
    expect(calls.checks).toHaveLength(0)
  })

  it('counts down and, at 0:00 before the photo is sent, stops the camera and asks for the code again', async () => {
    const camera = installCamera()
    const calls = stubEnroll(enrollOk)
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    await flush(61000)
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 3:59')
    await flush(240000 - 3000)
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(1000)
    expect(screen.getByTestId('face-countdown')).toBeTruthy()
    await flush(1000)
    expect(calls).toHaveLength(0)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/Time's up/)
    expect((screen.getByLabelText('Reset code from your instructor') as HTMLInputElement).value).toBe('')
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
    await flush(10000)
    expect(calls).toHaveLength(0)

    await enterCode('K7QM4XPA')
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 5:00')
  })

  it('does not upload a photo captured just as the window closes, before the timer ticks', async () => {
    const camera = installCamera()
    const calls = stubEnroll(enrollOk)
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    await flush(295000)
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush()
    expect(screen.getByTestId('face-countdown')).toBeTruthy()
    await flush(5000)
    expect(calls).toHaveLength(0)
    expect(camera.track.stop).toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/Time's up/)
  })

  it('a wrong code is caught by the check before the camera, keeps the typed code, and a right one goes on', async () => {
    const camera = installCamera()
    const calls = stubEnroll(enrollOk, (req) =>
      (req.data as { reset_code: string }).reset_code === 'WRONG123'
        ? { status: 403, data: { code: 'FACE_RESET_CODE_INVALID', detail: 'Reset code is invalid or expired' } }
        : CHECK_OK
    )
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('wrong-123')
    expect(calls.checks).toHaveLength(1)
    expect(calls.checks[0].data).toEqual({ reset_code: 'WRONG123' })
    expect(screen.getByRole('alert').textContent).toMatch(/reset code is wrong, expired or already used/)
    const field = screen.getByLabelText('Reset code from your instructor') as HTMLInputElement
    expect(field.value).toBe('wrong-123')
    expect(document.activeElement).toBe(field)
    expect(screen.queryByRole('button', { name: 'Allow camera access' })).toBeNull()
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
    expect(calls).toHaveLength(0)

    await enterCode('K7QM4XPA')
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 5:00')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls).toHaveLength(1)
    expect(calls[0].data).toMatchObject({ reset_code: 'K7QM4XPA' })
    expect(reauthenticate).toHaveBeenCalledTimes(1)
  })

  it('shows Checking... while the code is checked, then opens the camera step', async () => {
    installCamera()
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => (release = resolve))
    const calls = stubEnroll(enrollOk)
    const inner = httpClient.defaults.adapter as (config: InternalAxiosRequestConfig) => Promise<unknown>
    const held = async (config: InternalAxiosRequestConfig) => {
      if (config.url === CHECK_URL) await gate
      return inner(config)
    }
    httpClient.defaults.adapter = held as typeof httpClient.defaults.adapter
    render(<SettingsPage />)
    await openUpdate()
    fireEvent.change(screen.getByLabelText('Reset code from your instructor'), { target: { value: 'K7QM4XPA' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await flush()
    const button = screen.getByRole('button', { name: 'Checking...' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    await act(async () => {
      release()
    })
    await flush()
    expect(calls.checks).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Allow camera access' })).toBeTruthy()
  })

  it.each([
    [{ status: 429, data: { code: 'RATE_LIMITED' }, headers: { 'retry-after': '45' } }, /Too many code checks. Please wait 1 minute/],
    [{ status: 503, data: { code: 'FACE_RESET_CODE_UNAVAILABLE' } }, /Reset codes can't be checked right now/],
    [{ network: true }, /Can't reach the server/],
  ])('a failed check (%#) stays on the code step with its message', async (reply, expected) => {
    const camera = installCamera()
    const calls = stubEnroll(enrollOk, () => reply as StubReply)
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    expect(screen.getByRole('alert').textContent).toMatch(expected)
    expect((screen.getByLabelText('Reset code from your instructor') as HTMLInputElement).value).toBe('K7QM4XPA')
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
    expect(camera.getUserMedia).not.toHaveBeenCalled()
    expect(calls).toHaveLength(0)
  })

  it('falls back to checking at upload when the backend has no check endpoint (404)', async () => {
    installCamera()
    const calls = stubEnroll(enrollOk, () => ({ status: 404, data: { detail: 'Not Found' } }))
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    expect(screen.queryByText('Not Found')).toBeNull()
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 5:00')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls[0].data).toMatchObject({ reset_code: 'K7QM4XPA' })
  })

  it('two submits in the same moment send one check', async () => {
    installCamera()
    const calls = stubEnroll(enrollOk)
    render(<SettingsPage />)
    await openUpdate()
    fireEvent.change(screen.getByLabelText('Reset code from your instructor'), { target: { value: 'K7QM4XPA' } })
    const form = screen.getByLabelText('Reset code from your instructor').closest('form')!
    fireEvent.submit(form)
    fireEvent.submit(form)
    await flush()
    expect(calls.checks).toHaveLength(1)
  })

  it('a check that says no code is needed goes on without a timer or reset_code', async () => {
    installCamera()
    const calls = stubEnroll(enrollOk, () => ({ status: 200, data: { required: false, valid: true } }))
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls[0].data).toEqual({ image: expect.any(String) })
  })

  it('a code that expires between the check and the photo returns to the code step, keeping it', async () => {
    installCamera()
    const calls = stubEnroll(() => ({ status: 403, data: { code: 'FACE_RESET_CODE_INVALID', detail: 'x' } }))
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls).toHaveLength(1)
    expect(screen.getByRole('alert').textContent).toMatch(/reset code is wrong, expired or already used/)
    expect((screen.getByLabelText('Reset code from your instructor') as HTMLInputElement).value).toBe('K7QM4XPA')
    expect(screen.queryByTestId('face-reset-timer')).toBeNull()
  })

  it('a stale "not registered" state switches to the code step on FACE_RESET_CODE_REQUIRED', async () => {
    mockUser = { ...mockUser, face_enrolled: false }
    installCamera()
    let attempt = 0
    const calls = stubEnroll((req) => {
      attempt += 1
      return attempt === 1 ? { status: 403, data: { code: 'FACE_RESET_CODE_REQUIRED', detail: 'x' } } : enrollOk(req)
    })
    render(<SettingsPage />)
    await openAndPassPassword()
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByRole('alert').textContent).toMatch(/need a reset code from your instructor/)
    await enterCode('K7QM4XPA')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls[1].data).toMatchObject({ reset_code: 'K7QM4XPA' })
  })

  it('a no-face photo keeps the code and the running timer for the retry', async () => {
    installCamera()
    let attempt = 0
    const calls = stubEnroll((req) => {
      attempt += 1
      return attempt === 1 ? { status: 400, data: { code: 'NO_FACE_DETECTED', detail: 'x' } } : enrollOk(req)
    })
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByRole('alert').textContent).toMatch(/No face was detected/)
    await flush(1000)
    expect(screen.getByTestId('face-reset-timer').textContent).toBe('Time left to finish: 4:54')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(calls[1].data).toMatchObject({ reset_code: 'K7QM4XPA' })
    expect(screen.getByText('Your face identity is registered. You can now check in.')).toBeTruthy()
  })

  it('the window can also expire on the error screen', async () => {
    installCamera()
    const calls = stubEnroll(() => ({ status: 400, data: { code: 'NO_FACE_DETECTED', detail: 'x' } }))
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    await flush(300000)
    expect(screen.getByRole('alert').textContent).toMatch(/Time's up/)
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(calls).toHaveLength(1)
  })

  it('maps FACE_RESET_CODE_UNAVAILABLE to its own message, not the face-service one', async () => {
    installCamera()
    stubEnroll(() => ({ status: 503, data: { code: 'FACE_RESET_CODE_UNAVAILABLE', detail: 'x' } }))
    render(<SettingsPage />)
    await openUpdate()
    await enterCode('K7QM4XPA')
    fireEvent.click(screen.getByRole('button', { name: 'Allow camera access' }))
    await flush(5000)
    expect(screen.getByRole('alert').textContent).toMatch(/Reset codes can't be checked right now/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})
