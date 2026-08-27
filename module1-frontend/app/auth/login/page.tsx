'use client'

/**
 * Task 1.1: Authentication Interfaces - Login page.
 */

import { useState, type FormEvent } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { validateLoginForm, type FieldError } from '@/lib/utils/validators'

export default function LoginPage() {
  const { login } = useAuth()
  const router = useRouter()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function errorFor(field: string): string | undefined {
    return fieldErrors.find((e) => e.field === field)?.message
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)

    const errors = validateLoginForm(email, password)
    setFieldErrors(errors)
    if (errors.length > 0) return

    setIsSubmitting(true)
    try {
      await login({ email: email.trim(), password })
      router.push('/dashboard')
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Login failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <h1 className="text-2xl font-bold text-gray-900">Log in</h1>
        <p className="mt-1 text-sm text-gray-500">Sign in to check in to your sessions.</p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={!!errorFor('email')}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
              placeholder="you@example.com"
            />
            {errorFor('email') && (
              <p className="mt-1 text-sm text-red-600">{errorFor('email')}</p>
            )}
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!errorFor('password')}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
              placeholder="********"
            />
            {errorFor('password') && (
              <p className="mt-1 text-sm text-red-600">{errorFor('password')}</p>
            )}
          </div>

          {submitError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
              {submitError}
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60"
          >
            {isSubmitting ? 'Logging in...' : 'Log in'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          Don&apos;t have an account?{' '}
          <Link href="/auth/register" className="font-medium text-blue-700 hover:underline">
            Register
          </Link>
        </p>
      </div>
    </main>
  )
}
