'use client'

/** Pop-up shown to a student with no registered face, pointing them to Settings; dismissible until the next login. */

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/useAuth'
import { FACE_PROMPT_DISMISSED_KEY, needsFaceEnrollment } from '@/lib/face/enrollment'

function readDismissed(): boolean {
  try {
    return window.sessionStorage.getItem(FACE_PROMPT_DISMISSED_KEY) === 'true'
  } catch {
    return false
  }
}

function rememberDismissed(): void {
  try {
    window.sessionStorage.setItem(FACE_PROMPT_DISMISSED_KEY, 'true')
  } catch {
    return
  }
}

export function FaceEnrollmentPrompt() {
  const { user } = useAuth()
  const pathname = usePathname()
  const router = useRouter()
  const [dismissed, setDismissed] = useState(readDismissed)
  const primaryRef = useRef<HTMLButtonElement | null>(null)
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const visible = needsFaceEnrollment(user) && !dismissed && !pathname?.startsWith('/dashboard/settings')

  function dismiss() {
    rememberDismissed()
    setDismissed(true)
  }

  useEffect(() => {
    if (!visible) return
    primaryRef.current?.focus()
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Tab') {
        const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button')
        if (!buttons || buttons.length === 0) return
        const first = buttons[0]
        const last = buttons[buttons.length - 1]
        const active = document.activeElement
        const inside = !!active && !!dialogRef.current?.contains(active)
        if (event.shiftKey && (active === first || !inside)) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && (active === last || !inside)) {
          event.preventDefault()
          first.focus()
        }
        return
      }
      if (event.key !== 'Escape') return
      rememberDismissed()
      setDismissed(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [visible])

  if (!visible) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="face-prompt-title"
        aria-describedby="face-prompt-body"
        className="w-full max-w-md space-y-4 rounded-lg bg-white p-6 shadow-xl"
      >
        <h2 id="face-prompt-title" className="text-lg font-semibold text-gray-900">
          Register your face identity
        </h2>
        <p id="face-prompt-body" className="text-sm text-gray-600">
          You haven&apos;t registered your face yet. Check-in is turned off until you do. It takes about 10
          seconds in Settings.
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={dismiss}
            className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Later
          </button>
          <button
            ref={primaryRef}
            type="button"
            onClick={() => router.push('/dashboard/settings')}
            className="min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
          >
            Register now
          </button>
        </div>
      </div>
    </div>
  )
}
