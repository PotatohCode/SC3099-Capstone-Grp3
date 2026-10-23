'use client'

/** Blocks check-in for a student with no registered face and links them to Settings instead. */

import Link from 'next/link'
import { useAuth } from '@/lib/hooks/useAuth'
import { needsFaceEnrollment } from '@/lib/face/enrollment'

export function FaceEnrolledGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (!needsFaceEnrollment(user)) return <>{children}</>
  return (
    <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-5" role="alert">
      <h1 className="text-lg font-semibold text-amber-900">Check-in is turned off</h1>
      <p className="text-sm text-amber-800">Register your face identity in Settings before you can check in.</p>
      <Link
        href="/dashboard/settings"
        className="inline-flex min-h-[44px] items-center rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
      >
        Go to Settings
      </Link>
    </div>
  )
}
