'use client'

/** Change password form: current password, new password and confirmation, checked locally before POST /users/me/password. */

import { useRef, useState, type FormEvent } from 'react'
import { changePassword } from '@/lib/services/auth.service'
import {
  PASSWORD_MIN_LENGTH,
  changePasswordErrorMessage,
  validatePasswordChange,
} from '@/lib/utils/password-change'

const INPUT =
  'mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600'

export function ChangePasswordForm() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const busyRef = useRef(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busyRef.current) return
    setDone(false)
    const problem = validatePasswordChange({ current, next, confirm })
    if (problem) {
      setError(problem)
      return
    }
    busyRef.current = true
    setBusy(true)
    setError(null)
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      setError(changePasswordErrorMessage(err))
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-3" noValidate>
      <div>
        <label htmlFor="current-password" className="block text-sm font-medium text-gray-700">
          Current password
        </label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          disabled={busy}
          className={INPUT}
        />
      </div>
      <div>
        <label htmlFor="new-password" className="block text-sm font-medium text-gray-700">
          New password
        </label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          aria-describedby="new-password-hint"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          disabled={busy}
          className={INPUT}
        />
        <p id="new-password-hint" className="mt-1 text-xs text-gray-500">
          At least {PASSWORD_MIN_LENGTH} characters.
        </p>
      </div>
      <div>
        <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-700">
          Confirm new password
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={busy}
          className={INPUT}
        />
      </div>
      {error && (
        <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {done && (
        <div role="status" className="rounded-md bg-green-50 p-3 text-sm text-green-800">
          Password changed. Use your new password next time you log in.
        </div>
      )}
      <button
        type="submit"
        disabled={busy}
        className="min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60"
      >
        {busy ? 'Changing...' : 'Change password'}
      </button>
    </form>
  )
}
