import { fireEvent, render, screen } from '@testing-library/react'
import type { User } from '@/lib/types'

let mockUser: User | null = null
let mockPath = '/dashboard'
const push = jest.fn()
const replace = jest.fn()

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: mockUser, isAuthenticated: !!mockUser, isLoading: false, logout: jest.fn() }),
}))
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => mockPath,
}))
jest.mock('@/lib/hooks/useOfflineSync', () => ({
  useOfflineSync: () => ({ isOnline: true, queueLength: 2, isSyncing: false, syncBlocked: mockUser?.face_enrolled !== true, syncNow: jest.fn() }),
}))
jest.mock('@/lib/context/CheckInContext', () => ({
  CheckInProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import DashboardLayout from '@/app/dashboard/layout'
import DashboardHomePage from '@/app/dashboard/page'
import CheckInLayout from '@/app/dashboard/checkin/layout'
import { FaceEnrollmentPrompt } from '@/components/FaceEnrollmentPrompt'
import { OnlineStatusIndicator } from '@/components/OnlineStatusIndicator'

const student: User = { id: 'u1', email: 's@e.edu', full_name: 'Sam', role: 'student' }

describe('face identity gate', () => {
  beforeEach(() => {
    push.mockClear()
    mockPath = '/dashboard'
  })

  describe('student without a registered face', () => {
    beforeEach(() => {
      mockUser = { ...student, face_enrolled: false }
    })

    it('layout shows the prompt, a disabled Check In nav item and a Settings link', () => {
      render(<DashboardLayout><p>child</p></DashboardLayout>)
      expect(screen.getByRole('dialog', { name: 'Register your face identity' })).toBeTruthy()
      const nav = screen.getByRole('navigation', { name: 'Primary' })
      expect(nav.querySelector('a[href="/dashboard/checkin"]')).toBeNull()
      expect(nav.querySelector('[aria-disabled="true"]')?.textContent).toBe('Check In')
      expect(nav.querySelector('a[href="/dashboard/settings"]')?.textContent).toBe('Settings')
    })

    it('Register now goes to Settings; Later hides the prompt for this session', () => {
      const { unmount } = render(<FaceEnrollmentPrompt />)
      fireEvent.click(screen.getByRole('button', { name: 'Register now' }))
      expect(push).toHaveBeenCalledWith('/dashboard/settings')
      fireEvent.click(screen.getByRole('button', { name: 'Later' }))
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(window.sessionStorage.getItem('saiv_face_prompt_dismissed')).toBe('true')
      unmount()
      render(<FaceEnrollmentPrompt />)
      expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('Escape dismisses the prompt and it focuses Register now', () => {
      render(<FaceEnrollmentPrompt />)
      expect(document.activeElement?.textContent).toBe('Register now')
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('Tab keeps focus inside the prompt', () => {
      render(
        <>
          <button type="button">outside</button>
          <FaceEnrollmentPrompt />
        </>
      )
      const later = screen.getByRole('button', { name: 'Later' })
      const register = screen.getByRole('button', { name: 'Register now' })
      expect(document.activeElement).toBe(register)
      fireEvent.keyDown(window, { key: 'Tab' })
      expect(document.activeElement).toBe(later)
      fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
      expect(document.activeElement).toBe(register)
      screen.getByRole('button', { name: 'outside' }).focus()
      fireEvent.keyDown(window, { key: 'Tab' })
      expect(document.activeElement).toBe(later)
    })

    it('the prompt is not shown on the settings page', () => {
      mockPath = '/dashboard/settings'
      render(<FaceEnrollmentPrompt />)
      expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('home page replaces the check-in card with a link to Settings', () => {
      const { container } = render(<DashboardHomePage />)
      expect(container.querySelector('a[href="/dashboard/checkin"]')).toBeNull()
      expect(screen.getByText('Check In (turned off)')).toBeTruthy()
      expect(container.querySelector('a[href="/dashboard/settings"]')).toBeTruthy()
    })

    it('typing the check-in URL shows the blocked panel instead of the wizard', () => {
      render(<CheckInLayout><p>wizard</p></CheckInLayout>)
      expect(screen.queryByText('wizard')).toBeNull()
      expect(screen.getByText('Check-in is turned off')).toBeTruthy()
    })

    it('hides Sync now while blocked', () => {
      render(<OnlineStatusIndicator />)
      expect(screen.queryByRole('button', { name: 'Sync now' })).toBeNull()
      expect(screen.getByText('Sync paused until your face is registered')).toBeTruthy()
    })
  })

  describe('student with a registered face', () => {
    beforeEach(() => {
      mockUser = { ...student, face_enrolled: true }
    })

    it('keeps every check-in entry point as before and shows no prompt', () => {
      const { container } = render(<DashboardLayout><DashboardHomePage /></DashboardLayout>)
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(container.querySelectorAll('a[href="/dashboard/checkin"]')).toHaveLength(2)
      expect(screen.getByRole('button', { name: 'Sync now' })).toBeTruthy()
      render(<CheckInLayout><p>wizard</p></CheckInLayout>)
      expect(screen.getByText('wizard')).toBeTruthy()
    })
  })

  it('does not prompt or block non-students', () => {
    mockUser = { ...student, role: 'instructor', face_enrolled: false }
    render(<DashboardLayout><p>child</p></DashboardLayout>)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText('Settings')).toBeNull()
  })
})
