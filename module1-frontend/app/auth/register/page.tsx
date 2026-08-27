'use client'

/**
 * Task 1.1: Authentication Interfaces - Registration page.
 * Fields: email + password + full_name + role selection (API-SPECIFICATION.md POST /auth/register)
 */

import { useState, type FormEvent } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { validateRegisterForm, type FieldError } from '@/lib/utils/validators'
import type { UserRole } from '@/lib/types'

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: 'student', label: 'Student' },
  { value: 'ta', label: 'Teaching Assistant' },
  { value: 'instructor', label: 'Instructor' },
]

export default function RegisterPage() {
  const { register } = useAuth()
  const router = useRouter()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<UserRole>('student')
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function errorFor(field: string): string | undefined {
    return fieldErrors.find((e) => e.field === field)?.message
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)
    setSuccessMessage(null)

    const errors = validateRegisterForm(email, password, fullName)
    setFieldErrors(errors)
    if (errors.length > 0) return

    setIsSubmitting(true)
    try {
      await register({ email: email.trim(), password, full_name: fullName.trim(), role })
      setSuccessMessage('Account created! Redirecting to login...')
      setTimeout(() => router.push('/auth/login'), 1200)
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Registration failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <h1 className="text-2xl font-bold text-gray-900">Create account</h1>
        <p className="mt-1 text-sm text-gray-500">Register to start checking in to sessions.</p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
          <div>
            <label htmlFor="full_name" className="block text-sm font-medium text-gray-700">
              Full name
            </label>
            <input
              id="full_name"
              name="full_name"
              type="text"
              autoComplete="name"
              autoFocus
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              aria-invalid={!!errorFor('full_name')}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
              placeholder="Jane Doe"
            />
            {errorFor('full_name') && (
              <p className="mt-1 text-sm text-red-600">{errorFor('full_name')}</p>
            )}
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
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
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!errorFor('password')}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
              placeholder="At least 8 characters"
            />
            {errorFor('password') && (
              <p className="mt-1 text-sm text-red-600">{errorFor('password')}</p>
            )}
          </div>

          <div>
            <label htmlFor="role" className="block text-sm font-medium text-gray-700">
              Role
            </label>
            <select
              id="role"
              name="role"
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
            >
              {ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {submitError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
              {submitError}
            </div>
          )}
          {successMessage && (
            <div className="rounded-md bg-green-50 p-3 text-sm text-green-700" role="status">
              {successMessage}
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60"
          >
            {isSubmitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-500">
          Already have an account?{' '}
          <Link href="/auth/login" className="font-medium text-blue-700 hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </main>
  )
}
