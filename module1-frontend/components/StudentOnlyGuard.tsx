'use client'

/**
 * Check In (Task 1.2) and check-in History (Task 1.9) are student-only features - only
 * students check in to a course; instructor/ta/admin manage attendance from Module 4's
 * dashboard instead. This guard redirects any non-student role away from those two routes
 * (dashboard/layout.tsx already hides their nav links, but a role check here also covers
 * anyone who types the URL directly).
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'

export function StudentOnlyGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()
  const isStudent = user?.role === 'student'

  useEffect(() => {
    if (!isLoading && user && !isStudent) {
      router.replace('/dashboard')
    }
  }, [isLoading, user, isStudent, router])

  if (isLoading || !user) {
    return <LoadingSpinner label="Checking your session..." />
  }

  if (!isStudent) {
    // Redirect effect above will fire; render nothing meanwhile.
    return null
  }

  return <>{children}</>
}
