/** Warning shown with every flagged check-in telling the student to see their instructor in class. */

export const FLAGGED_WARNING = 'Please approach your instructor in class to mark your attendance.'

export function FlaggedNotice({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p className="max-w-[9rem] whitespace-normal text-xs font-medium text-amber-800" role="note">
        {FLAGGED_WARNING}
      </p>
    )
  }
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm font-medium text-amber-800" role="alert">
      {FLAGGED_WARNING}
    </div>
  )
}
