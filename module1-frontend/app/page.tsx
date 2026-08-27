'use client'

/**
 * Task 1.10: "Ensure root route responds 200 OK" - kept as a simple, always-renderable
 * landing page (no auth-gated data fetching) so health checks never fail.
 */

import Link from 'next/link'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace('/dashboard')
    }
  }, [isLoading, isAuthenticated, router])

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8 text-center">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 sm:text-4xl">
          SAIV - Secure Attendance System
        </h1>
        <p className="mt-3 text-gray-600">
          Student check-in with liveness detection, geolocation, and device binding.
        </p>
      </div>

      <div className="flex w-full max-w-xs flex-col gap-3 sm:flex-row sm:max-w-none sm:justify-center">
        <Link
          href="/auth/login"
          className="flex min-h-[44px] items-center justify-center rounded-md bg-blue-700 px-6 py-2 font-medium text-white hover:bg-blue-800"
        >
          Log in
        </Link>
        <Link
          href="/auth/register"
          className="flex min-h-[44px] items-center justify-center rounded-md border border-blue-700 px-6 py-2 font-medium text-blue-700 hover:bg-blue-50"
        >
          Create account
        </Link>
      </div>
    </main>
  )
}
