import { act, fireEvent, render, screen } from '@testing-library/react'
import HistoryPage from '@/app/dashboard/history/page'
import CheckInDetailPage from '@/app/dashboard/history/[id]/page'
import { stubAdapter } from '@/test/axios-stub'
import { FLAGGED_WARNING } from '@/components/FlaggedNotice'
import { REJECTED_AFTER_APPEAL, REJECTED_SHORT, REJECTED_WARNING } from '@/components/RejectedNotice'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u1', role: 'student' }, isLoading: false }),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useParams: () => ({ id: 'c-flag' }),
}))

const rows = [
  { id: 'c-flag', session_id: 's1', session_name: 'Lecture 7', course_code: 'SC3099', status: 'flagged', checked_in_at: '2026-10-26T02:05:00', risk_score: 0.69, risk_level: 'HIGH' },
  { id: 'c-ok', session_id: 's2', session_name: 'Lecture 8', course_code: 'SC3099', status: 'approved', checked_in_at: '2026-10-31T16:30:00', risk_score: 0.1, risk_level: 'LOW' },
]

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

describe('history pages', () => {
  it('lists times in Singapore time and warns once per flagged row', async () => {
    stubAdapter((req) => {
      if (req.url === '/checkins/my-checkins') return { status: 200, data: rows }
      if (req.url === '/enrollments/my-enrollments') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<HistoryPage />)
    await settle()
    expect(screen.getByText('Date (SGT)')).toBeTruthy()
    expect(screen.getByText('26/10/26')).toBeTruthy()
    expect(screen.getByText('10:05')).toBeTruthy()
    expect(screen.getByText('01/11/26')).toBeTruthy()
    expect(screen.getByText('00:30')).toBeTruthy()
    expect(screen.getAllByText(FLAGGED_WARNING)).toHaveLength(1)
  })

  it('adds a Missed row for a closed session with no check-in, without a detail link or risk', async () => {
    const sessions = [
      { id: 's1', course_id: 'c1', course_code: 'SC3099', name: 'Lecture 7', status: 'closed', scheduled_start: '2026-10-26T02:00:00', scheduled_end: '2026-10-26T04:00:00', checkin_opens_at: '2026-10-26T01:45:00', checkin_closes_at: '2026-10-26T02:30:00' },
      { id: 's9', course_id: 'c1', course_code: 'SC3099', name: 'Tutorial 3', status: 'closed', scheduled_start: '2026-10-28T06:00:00', scheduled_end: '2026-10-28T07:00:00', checkin_opens_at: '2026-10-28T05:45:00', checkin_closes_at: '2026-10-28T06:30:00' },
      { id: 's10', course_id: 'c1', course_code: 'SC3099', name: 'Cancelled Lab', status: 'cancelled', scheduled_start: '2026-10-29T06:00:00', scheduled_end: '2026-10-29T07:00:00', checkin_opens_at: '2026-10-29T05:45:00', checkin_closes_at: '2026-10-29T06:30:00' },
      { id: 's11', course_id: 'c1', course_code: 'SC3099', name: 'Future Lecture', status: 'scheduled', scheduled_start: '2099-01-01T06:00:00', scheduled_end: '2099-01-01T07:00:00', checkin_opens_at: '2099-01-01T05:45:00', checkin_closes_at: '2099-01-01T06:30:00' },
    ]
    stubAdapter((req) => {
      if (req.url === '/checkins/my-checkins') return { status: 200, data: rows }
      if (req.url === '/enrollments/my-enrollments') return { status: 200, data: [{ id: 'e1', course_id: 'c1', course_code: 'SC3099', course_name: 'Capstone' }] }
      if (req.url === '/sessions/my-sessions') return { status: 200, data: sessions.filter((x) => x.status === req.params?.status) }
      return { status: 404 }
    })
    render(<HistoryPage />)
    await settle()
    expect(screen.getAllByText('missed', { selector: 'span' })).toHaveLength(1)
    const row = screen.getByText('Tutorial 3').closest('tr') as HTMLElement
    expect(row.textContent).toContain('28/10/26')
    expect(row.textContent).toContain('14:00')
    expect(row.querySelector('a')).toBeNull()
    expect(row.textContent).not.toContain('N/A')
    expect(screen.queryByText('Cancelled Lab')).toBeNull()
    expect(screen.queryByText('Future Lecture')).toBeNull()
    const body = screen.getAllByRole('row').slice(1).map((r) => r.textContent ?? '')
    expect(body.map((t) => t.slice(0, 8))).toEqual(['01/11/26', '28/10/26', '26/10/26'])
  })

  it('filters History to Missed rows', async () => {
    const sessions = [
      { id: 's9', course_id: 'c1', course_code: 'SC3099', name: 'Tutorial 3', status: 'closed', scheduled_start: '2026-10-28T06:00:00', scheduled_end: '2026-10-28T07:00:00', checkin_opens_at: '2026-10-28T05:45:00', checkin_closes_at: '2026-10-28T06:30:00' },
    ]
    stubAdapter((req) => {
      if (req.url === '/checkins/my-checkins') return { status: 200, data: rows }
      if (req.url === '/enrollments/my-enrollments') return { status: 200, data: [{ id: 'e1', course_id: 'c1', course_code: 'SC3099', course_name: 'Capstone' }] }
      if (req.url === '/sessions/my-sessions') return { status: 200, data: sessions.filter((x) => x.status === req.params?.status) }
      return { status: 404 }
    })
    render(<HistoryPage />)
    await settle()
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'missed' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Tutorial 3')).toBeTruthy()
  })

  it('still lists check-ins when the session list fails to load', async () => {
    stubAdapter((req) => {
      if (req.url === '/checkins/my-checkins') return { status: 200, data: rows }
      if (req.url === '/enrollments/my-enrollments') return { status: 200, data: [] }
      if (req.url === '/sessions/my-sessions') return { status: 500 }
      return { status: 404 }
    })
    render(<HistoryPage />)
    await settle()
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.queryByText('missed', { selector: 'span' })).toBeNull()
  })

  it('shows detail times in Singapore time and the flagged warning', async () => {
    stubAdapter((req) => {
      if (req.url === '/checkins/c-flag') {
        return {
          status: 200,
          data: { ...rows[0], session_id: 's1', verified_at: '2026-10-26T02:06:00', risk_factors: [] },
        }
      }
      if (req.url === '/sessions/s1') return { status: 200, data: { id: 's1', course_id: 'c1', name: 'Lecture 7', status: 'active', scheduled_start: '', scheduled_end: '' } }
      return { status: 404 }
    })
    render(<CheckInDetailPage />)
    await settle()
    expect(screen.getByText('Checked in at').nextSibling?.textContent).toBe('26/10/2026, 10:05 SGT')
    expect(screen.getByText('Verified at').nextSibling?.textContent).toBe('26/10/2026, 10:06 SGT')
    expect(screen.getByText(FLAGGED_WARNING)).toBeTruthy()
  })
  it('tells the student on a rejected History row to open it to appeal or see the instructor', async () => {
    const rejected = [{ ...rows[1], id: 'c-rej', status: 'rejected' }, rows[0]]
    stubAdapter((req) => {
      if (req.url === '/checkins/my-checkins') return { status: 200, data: rejected }
      if (req.url === '/enrollments/my-enrollments') return { status: 200, data: [] }
      return { status: 404 }
    })
    render(<HistoryPage />)
    await settle()
    expect(screen.getAllByText(REJECTED_SHORT)).toHaveLength(1)
    const row = screen.getByText(REJECTED_SHORT).closest('tr') as HTMLElement
    expect(row.querySelector('a')?.getAttribute('href')).toBe('/dashboard/history/c-rej')
  })

  it('shows a rejected check-in why it matters and links to the appeal form', async () => {
    stubAdapter((req) => {
      if (req.url === '/checkins/c-flag') {
        return { status: 200, data: { ...rows[0], status: 'rejected', session_id: 's1', risk_factors: [] } }
      }
      if (req.url === '/sessions/s1') return { status: 200, data: { id: 's1', course_id: 'c1', name: 'Lecture 7', status: 'closed', scheduled_start: '', scheduled_end: '' } }
      return { status: 404 }
    })
    render(<CheckInDetailPage />)
    await settle()
    expect(screen.getByText(REJECTED_WARNING)).toBeTruthy()
    expect(document.getElementById('appeal')?.querySelector('textarea')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Write an appeal' }))
    expect(document.getElementById('appeal')?.querySelector('textarea')).toBeTruthy()
    expect(screen.queryByText(FLAGGED_WARNING)).toBeNull()
  })

  it('opens the appeal form straight away when arriving from check-in with #appeal', async () => {
    window.location.hash = '#appeal'
    stubAdapter((req) => {
      if (req.url === '/checkins/c-flag') return { status: 200, data: { ...rows[0], status: 'rejected', session_id: 's1', risk_factors: [] } }
      if (req.url === '/sessions/s1') return { status: 200, data: { id: 's1', course_id: 'c1', name: 'Lecture 7', status: 'closed', scheduled_start: '', scheduled_end: '' } }
      return { status: 404 }
    })
    render(<CheckInDetailPage />)
    await settle()
    expect(document.getElementById('appeal')?.querySelector('textarea')).toBeTruthy()
    window.location.hash = ''
  })

  it('after a reviewed appeal, points the student to the instructor without another appeal link', async () => {
    stubAdapter((req) => {
      if (req.url === '/checkins/c-flag') {
        return {
          status: 200,
          data: { ...rows[0], status: 'rejected', session_id: 's1', risk_factors: [], appeal_reason: 'I was in LT1', appealed_at: '2026-10-26T03:00:00' },
        }
      }
      if (req.url === '/sessions/s1') return { status: 200, data: { id: 's1', course_id: 'c1', name: 'Lecture 7', status: 'closed', scheduled_start: '', scheduled_end: '' } }
      return { status: 404 }
    })
    render(<CheckInDetailPage />)
    await settle()
    expect(screen.getByText(REJECTED_AFTER_APPEAL)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Write an appeal' })).toBeNull()
  })
})
