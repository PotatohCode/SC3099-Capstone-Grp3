/** Guidance shown with a rejected check-in: the attendance didn't count, so see the instructor or appeal. */

import Link from 'next/link'

export const REJECTED_SHORT = 'Not counted. Open to appeal, or see your instructor.'
export const REJECTED_TITLE = "Your attendance wasn't recorded"
export const REJECTED_WARNING =
  "This check-in was rejected, so you're marked absent for this session. If you were there, speak to your instructor in class or send an appeal explaining what happened."
export const REJECTED_AFTER_APPEAL =
  'This check-in was rejected after your appeal was reviewed. If you think this is a mistake, speak to your instructor.'

/** Compact note for the History list, or a full panel with an appeal link for the detail page. */
export function RejectedNotice({
  compact = false,
  appealed = false,
  onAppeal,
  appealHref,
}: {
  compact?: boolean
  appealed?: boolean
  onAppeal?: () => void
  appealHref?: string
}) {
  if (compact) {
    return (
      <p className="max-w-[9rem] whitespace-normal text-xs font-medium text-red-800" role="note">
        {REJECTED_SHORT}
      </p>
    )
  }
  return (
    <div className="space-y-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800" role="alert">
      <p className="font-semibold">{REJECTED_TITLE}</p>
      <p>{appealed ? REJECTED_AFTER_APPEAL : REJECTED_WARNING}</p>
      {!appealed && appealHref && (
        <Link
          href={appealHref}
          className="inline-flex min-h-[44px] items-center rounded-md bg-red-700 px-4 py-2 font-medium text-white hover:bg-red-800"
        >
          Write an appeal
        </Link>
      )}
      {!appealed && !appealHref && onAppeal && (
        <button
          type="button"
          onClick={onAppeal}
          className="inline-flex min-h-[44px] items-center rounded-md bg-red-700 px-4 py-2 font-medium text-white hover:bg-red-800"
        >
          Write an appeal
        </button>
      )}
    </div>
  )
}
