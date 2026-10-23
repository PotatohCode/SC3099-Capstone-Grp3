import { act, fireEvent, render, screen } from '@testing-library/react'
import SettingsPage from '@/app/dashboard/settings/page'
import { installCamera } from '@/test/browser-mocks'
import { httpError, stubAdapter, type RecordedRequest } from '@/test/axios-stub'
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
