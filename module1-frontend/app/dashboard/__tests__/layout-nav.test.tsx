import { fireEvent, render, screen, within } from '@testing-library/react'
import type { User } from '@/lib/types'

let mockUser: User | null = null
let mockPath = '/dashboard'

jest.mock('@/lib/hooks/useAuth', () => ({
  useAuth: () => ({ user: mockUser, isAuthenticated: !!mockUser, isLoading: false, logout: jest.fn() }),
}))
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => mockPath,
}))
jest.mock('@/lib/hooks/useOfflineSync', () => ({
  useOfflineSync: () => ({ isOnline: true, queueLength: 0, isSyncing: false, syncBlocked: false, syncNow: jest.fn() }),
}))

import DashboardLayout from '@/app/dashboard/layout'

const student: User = { id: 'u1', email: 's@e.edu', full_name: 'Sam', role: 'student', face_enrolled: true }

function renderLayout() {
  return render(
    <DashboardLayout>
      <p>page</p>
    </DashboardLayout>
  )
}

describe('dashboard nav on small screens', () => {
  beforeEach(() => {
    mockUser = { ...student }
    mockPath = '/dashboard'
  })

  it('hides the inline nav below sm and shows a closed Menu button only below sm', () => {
    renderLayout()
    const inline = screen.getByRole('navigation', { name: 'Primary' })
    expect(inline.className.split(' ')).toEqual(expect.arrayContaining(['hidden', 'sm:flex']))
    const menu = screen.getByRole('button', { name: /Menu/ })
    expect(menu.className.split(' ')).toContain('sm:hidden')
    expect(menu.getAttribute('aria-expanded')).toBe('false')
    expect(menu.getAttribute('aria-controls')).toBeNull()
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
  })

  it('keeps the same inline links as before for sm and up', () => {
    renderLayout()
    const links = within(screen.getByRole('navigation', { name: 'Primary' })).getAllByRole('link')
    expect(links.map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      ['Home', '/dashboard'],
      ['Check In', '/dashboard/checkin'],
      ['History', '/dashboard/history'],
      ['Settings', '/dashboard/settings'],
    ])
  })

  it('Menu opens a dropdown with every link, and a link tap closes it', () => {
    renderLayout()
    const menu = screen.getByRole('button', { name: /Menu/ })
    fireEvent.click(menu)
    expect(menu.getAttribute('aria-expanded')).toBe('true')
    expect(menu.getAttribute('aria-controls')).toBe('mobile-nav')
    const dropdown = screen.getByRole('navigation', { name: 'Mobile' })
    expect(dropdown.id).toBe('mobile-nav')
    expect(dropdown.className.split(' ')).toContain('sm:hidden')
    const links = within(dropdown).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Home', 'Check In', 'History', 'Settings'])
    expect(links[0].getAttribute('aria-current')).toBe('page')
    fireEvent.click(links[3])
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
  })

  it('closes on Escape and on a tap outside the header', () => {
    renderLayout()
    const menu = screen.getByRole('button', { name: /Menu/ })
    fireEvent.click(menu)
    within(screen.getByRole('navigation', { name: 'Mobile' })).getAllByRole('link')[1].focus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
    expect(document.activeElement).toBe(menu)
    fireEvent.click(menu)
    fireEvent.mouseDown(screen.getByText('page'))
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
    fireEvent.click(menu)
    fireEvent.click(menu)
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
  })

  it('closes when the route changes', () => {
    const { rerender } = renderLayout()
    fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
    expect(screen.getByRole('navigation', { name: 'Mobile' })).toBeTruthy()
    mockPath = '/dashboard/history'
    rerender(
      <DashboardLayout>
        <p>page</p>
      </DashboardLayout>
    )
    expect(screen.queryByRole('navigation', { name: 'Mobile' })).toBeNull()
  })

  it('shows Check In as disabled with a reason in the dropdown while the face gate is on', () => {
    mockUser = { ...student, face_enrolled: false }
    window.sessionStorage.setItem('saiv_face_prompt_dismissed', 'true')
    renderLayout()
    fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
    const dropdown = screen.getByRole('navigation', { name: 'Mobile' })
    expect(within(dropdown).queryByRole('link', { name: /Check In/ })).toBeNull()
    expect(dropdown.querySelector('[aria-disabled="true"]')?.textContent).toBe('Check In (register your face first)')
    expect(within(dropdown).getByRole('link', { name: 'Settings' })).toBeTruthy()
  })

  it('puts the dropdown right after the Menu button in tab order', () => {
    renderLayout()
    const menu = screen.getByRole('button', { name: /Menu/ })
    fireEvent.click(menu)
    const dropdown = screen.getByRole('navigation', { name: 'Mobile' })
    expect(menu.nextElementSibling).toBe(dropdown)
  })

  it('keeps the header able to wrap on wider screens, as before', () => {
    const { container } = renderLayout()
    expect(container.querySelector('header > div')?.className.split(' ')).toContain('flex-wrap')
  })

  it('gives non-students their single Home link inline with no Menu button', () => {
    mockUser = { ...student, role: 'instructor' }
    renderLayout()
    expect(screen.queryByRole('button', { name: /Menu/ })).toBeNull()
    const inline = screen.getByRole('navigation', { name: 'Primary' })
    expect(inline.className.split(' ')).not.toContain('hidden')
    expect(within(inline).getAllByRole('link').map((l) => l.textContent)).toEqual(['Home'])
  })

  it('Check In (menu and inline) asks the wizard to restart only when already on the check-in page', () => {
    const restarts = jest.fn()
    window.addEventListener('saiv:checkin-restart', restarts)
    mockPath = '/dashboard/checkin'
    renderLayout()
    fireEvent.click(screen.getByRole('button', { name: /Menu/ }))
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Mobile' })).getByRole('link', { name: 'Check In' }))
    expect(restarts).toHaveBeenCalledTimes(1)
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Check In' }))
    expect(restarts).toHaveBeenCalledTimes(2)
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'History' }))
    expect(restarts).toHaveBeenCalledTimes(2)
    window.removeEventListener('saiv:checkin-restart', restarts)
  })

  it('Check In from another page does not send a restart request', () => {
    const restarts = jest.fn()
    window.addEventListener('saiv:checkin-restart', restarts)
    mockPath = '/dashboard/history'
    renderLayout()
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Check In' }))
    expect(restarts).not.toHaveBeenCalled()
    window.removeEventListener('saiv:checkin-restart', restarts)
  })

  it('a Ctrl/Cmd/Shift-click on Check In (new tab or window) does not restart the current wizard', () => {
    const restarts = jest.fn()
    window.addEventListener('saiv:checkin-restart', restarts)
    mockPath = '/dashboard/checkin'
    renderLayout()
    const link = within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Check In' })
    fireEvent.click(link, { ctrlKey: true })
    fireEvent.click(link, { metaKey: true })
    fireEvent.click(link, { shiftKey: true })
    expect(restarts).not.toHaveBeenCalled()
    fireEvent.click(link)
    expect(restarts).toHaveBeenCalledTimes(1)
    window.removeEventListener('saiv:checkin-restart', restarts)
  })
})
