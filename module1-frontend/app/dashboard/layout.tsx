'use client'

/**
 * Task 1.1 / Phase 1 deliverable: "Protected route wrapper" - guards every route under
 * /dashboard/*. Redirects unauthenticated users to /auth/login.
 */

import { useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { OnlineStatusIndicator } from '@/components/OnlineStatusIndicator'
import { ErrorBoundary } from '@/components/ErrorBoundary'

const NAV_LINKS = [
  { href: '/dashboard', label: 'Home' },
  // Check In / History are student-only (only students check in to a course - instructor/ta/
  // admin manage attendance from Module 4's dashboard instead), so these two are filtered out
  // below for any other role.
  { href: '/dashboard/checkin', label: 'Check In', studentOnly: true },
  { href: '/dashboard/history', label: 'History', studentOnly: true },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, user, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  const visibleNavLinks = NAV_LINKS.filter((link) => !link.studentOnly || user?.role === 'student')

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace('/auth/login')
    }
  }, [isLoading, isAuthenticated, router])

  if (isLoading) {
    return <LoadingSpinner label="Checking your session..." />
  }

  if (!isAuthenticated) {
    // Redirect effect above will fire; render nothing meanwhile.
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-6">
            <span className="text-lg font-bold text-blue-800">SAIV</span>
            <nav className="flex gap-1" aria-label="Primary">
              {visibleNavLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`flex min-h-[44px] items-center rounded-md px-3 text-sm font-medium ${
                    pathname === link.href
                      ? 'bg-blue-100 text-blue-800'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <OnlineStatusIndicator />
            <span className="hidden text-sm text-gray-500 sm:inline">{user?.full_name}</span>
            <button
              type="button"
              onClick={logout}
              className="min-h-[44px] rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  )
}
