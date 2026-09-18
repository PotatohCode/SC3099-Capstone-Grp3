'use client'

/**
 * Phase 5 deliverable: "Dashboard home page"
 */

import Link from 'next/link'
import { useAuth } from '@/lib/hooks/useAuth'

export default function DashboardHomePage() {
  const { user } = useAuth()
  // Check In / History are student-only - only students check in to a course;
  // instructor/ta/admin manage attendance from Module 4's dashboard instead.
  const isStudent = user?.role === 'student'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Welcome, {user?.full_name ?? 'Student'}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {isStudent
            ? 'Check in to your active sessions and review your attendance history.'
            : 'This student check-in portal has no features for your role. Use the Module 4 instructor dashboard to manage sessions and review attendance.'}
        </p>
      </div>

      {isStudent && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Link
            href="/dashboard/checkin"
            className="block min-h-[44px] rounded-lg border border-blue-200 bg-blue-50 p-5 hover:bg-blue-100"
          >
            <h2 className="text-lg font-semibold text-blue-800">Check In</h2>
            <p className="mt-1 text-sm text-blue-700">
              Select a session, verify liveness, and confirm your location.
            </p>
          </Link>

          <Link
            href="/dashboard/history"
            className="block min-h-[44px] rounded-lg border border-gray-200 bg-white p-5 hover:bg-gray-50"
          >
            <h2 className="text-lg font-semibold text-gray-800">Check-in History</h2>
            <p className="mt-1 text-sm text-gray-600">
              View past check-ins, statuses, risk scores, and appeal outcomes.
            </p>
          </Link>
        </div>
      )}

      {user && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-gray-700">Account</h2>
          <dl className="mt-2 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-gray-500">Email</dt>
              <dd className="font-medium text-gray-800">{user.email}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Role</dt>
              <dd className="font-medium capitalize text-gray-800">{user.role}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  )
}
