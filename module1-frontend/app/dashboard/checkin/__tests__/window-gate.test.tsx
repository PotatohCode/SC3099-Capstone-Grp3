import { act, fireEvent, render, screen } from '@testing-library/react'
import CheckInWizardPage from '@/app/dashboard/checkin/page'
import { CheckInProvider } from '@/lib/context/CheckInContext'
import { stubAdapter } from '@/test/axios-stub'
import { setServerOffsetForTests } from '@/lib/utils/server-clock'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'u1', role: 'student', camera_consent: true, geolocation_consent: true },
    saveConsent: async () => undefined,
  }),
}))

const NOW = Date.parse('2026-11-05T10:00:00Z')
const base = { course_id: 'c1', course_code: 'SC3099', status: 'active', scheduled_start: '', scheduled_end: '', venue_name: 'LT1' }
const open = { ...base, id: 's-open', name: 'Open Lecture', checkin_opens_at: '2026-11-05T09:45:00', checkin_closes_at: '2026-11-05T10:00:30' }
const later = { ...base, id: 's-later', name: 'Later Lecture', checkin_opens_at: '2026-11-05T10:01:00', checkin_closes_at: '2026-11-05T11:00:00' }
const over = { ...base, id: 's-over', name: 'Over Lecture', checkin_opens_at: '2026-11-05T08:00:00', checkin_closes_at: '2026-11-05T09:00:00' }
const noTimes = { ...base, id: 's-none', name: 'No Times Lecture' }
// Open only by server time (10:00): a slow phone says not yet, a fast one says closed
const skewed = { ...base, id: 's-skew', name: 'Skew Lecture', checkin_opens_at: '2026-11-05T09:55:00', checkin_closes_at: '2026-11-05T10:05:00' }

async function flush(ms = 0) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms)
  })
}

function renderWizard(sessions: object[]) {
  stubAdapter((req) => {
    if (req.url === '/sessions/my-sessions') return { status: 200, data: sessions }
    if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
    return { status: 404 }
  })
  render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
}

const card = (name: string) => screen.getByText(name).closest('button') as HTMLButtonElement
const reason = (name: string) => {
  const id = card(name).getAttribute('aria-describedby')
  return id ? document.getElementById(id)?.textContent : null
}

describe('step 1 check-in window gate', () => {
  beforeEach(() => {
    setServerOffsetForTests(0)
    jest.useFakeTimers({ now: NOW })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
  })
  afterEach(() => jest.useRealTimers())

  it('disables sessions not open yet and says why in SGT; closed ones leave the list', async () => {
    renderWizard([over, later, open, noTimes])
    await flush()
    expect(card('Open Lecture').disabled).toBe(false)
    expect(card('Later Lecture').disabled).toBe(true)
    expect(reason('Later Lecture')).toBe('Check-in opens at 05/11/2026, 18:01 SGT.')
    expect(screen.queryByText('Over Lecture')).toBeNull()
    expect(card('No Times Lecture').disabled).toBe(true)
    expect(reason('No Times Lecture')).toBe('Check-in times are unavailable for this session.')
  })

  it('points to History when every session has closed', async () => {
    renderWizard([over])
    await flush()
    expect(screen.getByText(/Sessions whose check-in has closed are in/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'History' }).getAttribute('href')).toBe('/dashboard/history')
  })

  it('lists open sessions first', async () => {
    renderWizard([later, open])
    await flush()
    const names = screen.getAllByRole('button').map((b) => b.querySelector('p')?.textContent)
    expect(names[0]).toBe('Open Lecture')
  })

  it('lets the student continue to the location step from an open session', async () => {
    renderWizard([open])
    await flush()
    fireEvent.click(card('Open Lecture'))
    await flush()
    expect(screen.getByText(/Step 2 of 4/)).toBeTruthy()
  })

  it('a disabled session does nothing when clicked', async () => {
    renderWizard([later])
    await flush()
    fireEvent.click(card('Later Lecture'))
    await flush()
    expect(screen.getByText(/Step 1 of 4/)).toBeTruthy()
  })

  it('enables a session once its window opens, without a reload', async () => {
    renderWizard([later])
    await flush()
    expect(card('Later Lecture').disabled).toBe(true)
    await flush(61_000)
    expect(card('Later Lecture').disabled).toBe(false)
  })

  it('blocks the click if the window closed after the list was drawn', async () => {
    renderWizard([open])
    await flush()
    expect(card('Open Lecture').disabled).toBe(false)
    jest.setSystemTime(NOW + 31_000)
    fireEvent.click(card('Open Lecture'))
    await flush()
    expect(screen.getByRole('alert').textContent).toBe('Check-in closed at 05/11/2026, 18:00 SGT.')
    expect(screen.getByText(/Step 1 of 4/)).toBeTruthy()
  })

  it('shows a session the backend activates later without a reload', async () => {
    let list: object[] = []
    stubAdapter((req) => {
      if (req.url === '/sessions/my-sessions') return { status: 200, data: list }
      if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    expect(screen.getByText(/No sessions are open for check-in right now/)).toBeTruthy()
    list = [{ ...open, checkin_closes_at: '2026-11-05T11:00:00' }]
    await flush(60_000)
    expect(card('Open Lecture').disabled).toBe(false)
  })

  it('picks up a later closing time after the instructor extends check-in', async () => {
    let list: object[] = [over]
    stubAdapter((req) => {
      if (req.url === '/sessions/my-sessions') return { status: 200, data: list }
      if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    expect(screen.queryByText('Over Lecture')).toBeNull()
    list = [{ ...over, checkin_closes_at: '2026-11-05T11:00:00' }]
    await flush(60_000)
    expect(card('Over Lecture').disabled).toBe(false)
  })

  it('keeps the list when a background refresh fails', async () => {
    let down = false
    stubAdapter((req) => {
      if (down) return { status: 502 }
      if (req.url === '/sessions/my-sessions') return { status: 200, data: [{ ...open, checkin_closes_at: '2026-11-05T11:00:00' }] }
      if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    down = true
    await flush(60_000)
    expect(screen.getByText('Open Lecture')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('clears the closed-window alert once that session opens again', async () => {
    let list: object[] = [open]
    stubAdapter((req) => {
      if (req.url === '/sessions/my-sessions') return { status: 200, data: list }
      if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    jest.setSystemTime(NOW + 31_000)
    fireEvent.click(card('Open Lecture'))
    await flush()
    expect(screen.getByRole('alert').textContent).toBe('Check-in closed at 05/11/2026, 18:00 SGT.')
    list = [{ ...open, checkin_closes_at: '2026-11-05T11:00:00' }]
    await flush(60_000)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(card('Open Lecture').disabled).toBe(false)
  })

  it.each([
    ['10 minutes slow', -600_000, 'Thu, 05 Nov 2026 10:00:00 GMT'],
    ['10 minutes fast', 600_000, 'Thu, 05 Nov 2026 10:00:00 GMT'],
  ])('uses the server time when the phone clock is %s', async (_label, skew, serverDate) => {
    jest.setSystemTime(NOW + skew)
    stubAdapter((req) => {
      if (req.url === '/health') return { status: 200, data: {}, headers: { date: serverDate } }
      if (req.url === '/sessions/my-sessions') return { status: 200, data: [skewed, later] }
      if (req.url === '/checkins/my-checkins') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<CheckInProvider><CheckInWizardPage /></CheckInProvider>)
    await flush()
    expect(card('Skew Lecture').disabled).toBe(false)
    expect(card('Later Lecture').disabled).toBe(true)
  })

  it('shows inactive sessions as not open even inside the window', async () => {
    renderWizard([{ ...open, status: 'scheduled' }])
    await flush()
    expect(card('Open Lecture').disabled).toBe(true)
    expect(reason('Open Lecture')).toBe('This session is not open for check-in.')
  })
})
