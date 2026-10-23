'use client'

/** Student settings: shows face identity status and runs the Update Face Identity flow. */

import { useState } from 'react'
import { useAuth } from '@/lib/hooks/useAuth'
import { FaceEnrollmentFlow } from '@/app/dashboard/settings/face-enrollment'

export default function SettingsPage() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const enrolled = user?.face_enrolled === true

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

      <section aria-labelledby="face-identity-heading" className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 id="face-identity-heading" className="text-lg font-semibold text-gray-900">
          Face identity
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Status:{' '}
          <span className={`font-medium ${enrolled ? 'text-green-700' : 'text-red-700'}`}>
            {enrolled ? 'Registered' : 'Not registered'}
          </span>
        </p>
        <p className="mt-1 text-sm text-gray-600">
          {enrolled
            ? 'Your face is used to confirm it is you when you check in. Update it if your appearance has changed.'
            : 'Register your face before you can check in. It is used to confirm it is you at each check-in.'}
        </p>
        {open ? (
          <FaceEnrollmentFlow onClose={() => setOpen(false)} />
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="mt-4 min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
          >
            {enrolled ? 'Update face identity' : 'Register face identity'}
          </button>
        )}
      </section>
    </div>
  )
}
