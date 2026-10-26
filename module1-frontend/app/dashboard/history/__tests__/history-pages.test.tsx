import { act, render, screen } from '@testing-library/react'
import HistoryPage from '@/app/dashboard/history/page'
import CheckInDetailPage from '@/app/dashboard/history/[id]/page'
import { stubAdapter } from '@/test/axios-stub'
import { FLAGGED_WARNING } from '@/components/FlaggedNotice'

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
})
