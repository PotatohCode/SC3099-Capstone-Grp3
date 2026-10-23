'use client'

/**
 * Task 1.1 / Phase 1 deliverable: "Protected route wrapper" - guards every route under
 * /dashboard/*. Redirects unauthenticated users to /auth/login.
 */

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { OnlineStatusIndicator } from '@/components/OnlineStatusIndicator'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { FaceEnrollmentPrompt } from '@/components/FaceEnrollmentPrompt'
import { needsFaceEnrollment } from '@/lib/face/enrollment'

const NAV_LINKS = [
  { href: '/dashboard', label: 'Home' },
  // Check In / History are student-only (only students check in to a course - instructor/ta/
  // admin manage attendance from Module 4's dashboard instead), so these two are filtered out
  // below for any other role.
  { href: '/dashboard/checkin', label: 'Check In', studentOnly: true },
  { href: '/dashboard/history', label: 'History', studentOnly: true },
  { href: '/dashboard/settings', label: 'Settings', studentOnly: true },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const visibleNavLinks = NAV_LINKS.filter((link) => !link.studentOnly || user?.role === 'student')
  const checkInBlocked = needsFaceEnrollment(user)
  const [menuOpen, setMenuOpen] = useState(false)
  const headerRef = useRef<HTMLElement | null>(null)
  const menuButtonRef = useRef<HTMLButtonElement | null>(null)
  const useMenu = visibleNavLinks.length > 1

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace('/auth/login')
    }
  }, [isLoading, isAuthenticated, router])

  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!menuOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      setMenuOpen(false)
      menuButtonRef.current?.focus()
    }
    function onPointer(event: MouseEvent) {
      if (headerRef.current && !headerRef.current.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointer)
    }
  }, [menuOpen])

  function renderNavItem(link: (typeof NAV_LINKS)[number], variant: 'inline' | 'menu') {
    const base = `flex min-h-[44px] items-center rounded-md px-3 text-sm font-medium${variant === 'menu' ? ' w-full' : ''}`
    if (link.href === '/dashboard/checkin' && checkInBlocked) {
      return (
        <span
          key={link.href}
          aria-disabled="true"
          title="Register your face identity in Settings to check in"
          className={`${base} cursor-not-allowed text-gray-400`}
        >
          {variant === 'menu' ? `${link.label} (register your face first)` : link.label}
        </span>
      )
    }
    return (
      <Link
        key={link.href}
        href={link.href}
        onClick={() => setMenuOpen(false)}
        aria-current={pathname === link.href ? 'page' : undefined}
        className={`${base} ${pathname === link.href ? 'bg-blue-100 text-blue-800' : 'text-gray-600 hover:bg-gray-100'}`}
      >
        {link.label}
      </Link>
    )
  }

  if (isLoading) {
    return <LoadingSpinner label="Checking your session..." />
  }

  if (!isAuthenticated) {
    // Redirect effect above will fire; render nothing meanwhile.
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header ref={headerRef} className="relative border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3 sm:gap-6">
            <span className="text-lg font-bold text-blue-800">SAIV</span>
            {useMenu && (
              <button
                ref={menuButtonRef}
                type="button"
                aria-expanded={menuOpen}
                aria-controls={menuOpen ? 'mobile-nav' : undefined}
                onClick={() => setMenuOpen((open) => !open)}
                className="flex min-h-[44px] items-center gap-1 rounded-md border border-gray-300 px-3 text-sm font-medium text-gray-700 hover:bg-gray-100 sm:hidden"
              >
                Menu
                <span aria-hidden="true">{menuOpen ? '▴' : '▾'}</span>
              </button>
            )}
            {useMenu && menuOpen && (
              <nav
                id="mobile-nav"
                aria-label="Mobile"
                className="absolute inset-x-0 top-full z-40 flex flex-col gap-1 border-b border-gray-200 bg-white px-4 py-2 shadow-md sm:hidden"
              >
                {visibleNavLinks.map((link) => renderNavItem(link, 'menu'))}
              </nav>
            )}
            <nav className={`${useMenu ? 'hidden sm:flex' : 'flex'} gap-1`} aria-label="Primary">
              {visibleNavLinks.map((link) => renderNavItem(link, 'inline'))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <OnlineStatusIndicator />
            <span className="hidden text-sm text-gray-500 sm:inline">{user?.full_name}</span>
            <button
              type="button"
              onClick={async () => {
                setIsLoggingOut(true)
                await logout()
              }}
              disabled={isLoggingOut}
              className="min-h-[44px] rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-60"
            >
              {isLoggingOut ? 'Logging out...' : 'Log out'}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <FaceEnrollmentPrompt />
    </div>
  )
}
