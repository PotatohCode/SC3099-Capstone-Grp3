'use client'

/**
 * Check-in detail page. Reached by tapping a row in /dashboard/history (Task 1.9
 * redesign: the list view only shows Date/Session/Status - everything else, including
 * the Appeal action, lives here instead of being crammed into a horizontally-scrolling
 * table that wasn't obvious to scroll on mobile).
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { appealCheckIn, getCheckIn } from '@/lib/services/checkin.service'
import { getSession } from '@/lib/services/session.service'
import { extractErrorMessage } from '@/lib/utils/http-client'
import { sanitizeText } from '@/lib/utils/validators'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { StatusBadge, RiskBadge } from '@/components/StatusBadge'
import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'
import type { CheckInResponse, SessionSummary } from '@/lib/types'

const APPEALABLE_STATUSES = new Set(['flagged', 'rejected'])

function DetailCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex items-center justify-between gap-4 py-1 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">{value}</span>
    </div>
  )
}

function BooleanBadge({ value }: { value: boolean | null | undefined }) {
  if (value === null || value === undefined) {
    return (
      <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
        N/A
      </span>
    )
  }
  return value ? (
    <span className="inline-flex items-center rounded-full border border-green-300 bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
      Passed
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full border border-red-300 bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
      Failed
    </span>
  )
}

function AppealForm({
  checkinId,
  onAppealed,
}: {
  checkinId: string
  onAppealed: (updated: Pick<CheckInResponse, 'status' | 'appeal_reason' | 'appealed_at'>) => void
}) {
  const [reason, setReason] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="min-h-[44px] rounded-md border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50"
      >
        Appeal this check-in
      </button>
    )
  }

  async function handleSubmit() {
    const cleaned = sanitizeText(reason)
    if (cleaned.length < 5) {
      setError('Please provide a brief explanation (at least 5 characters).')
      return
    }
    setIsSubmitting(true)
    setError(null)
    try {
      const response = await appealCheckIn(checkinId, { appeal_reason: cleaned })
      onAppealed({
        status: response.status,
        appeal_reason: response.appeal_reason,
        appealed_at: response.appealed_at,
      })
      setIsOpen(false)
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to submit appeal.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-gray-200 bg-gray-50 p-3">
      <label htmlFor="appeal-reason" className="block text-xs font-medium text-gray-700">
        Why should this check-in be reconsidered?
      </label>
      <textarea
        id="appeal-reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={3}
        className="w-full rounded-md border border-gray-300 p-2 text-sm focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600"
        placeholder="e.g. I was in the venue but GPS accuracy was poor indoors."
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting}
          className="min-h-[44px] rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-60"
        >
          {isSubmitting ? 'Submitting...' : 'Submit appeal'}
        </button>
        <button
          type="button"
          onClick={() => setIsOpen(false)}
          className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

export default function CheckInDetailPage() {
  return (
    <StudentOnlyGuard>
      <CheckInDetailContent />
    </StudentOnlyGuard>
  )
}

function CheckInDetailContent() {
  const params = useParams<{ id: string }>()
  const checkinId = params.id

  const [checkin, setCheckin] = useState<CheckInResponse | null>(null)
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setIsLoading(true)
      setError(null)
      try {
        const checkinData = await getCheckIn(checkinId)
        if (cancelled) return
        setCheckin(checkinData)
        const sessionData = await getSession(checkinData.session_id).catch(() => null)
        if (!cancelled) setSession(sessionData)
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err, 'Failed to load check-in details.'))
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [checkinId])

  function handleAppealed(updated: Pick<CheckInResponse, 'status' | 'appeal_reason' | 'appealed_at'>) {
    setCheckin((prev) => (prev ? { ...prev, ...updated } : prev))
  }

  if (isLoading) return <LoadingSpinner label="Loading check-in details..." />

  if (error || !checkin) {
    return (
      <div className="space-y-4">
        <Link
          href="/dashboard/history"
          className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
        >
          Back to history
        </Link>
        <p className="text-sm text-red-600" role="alert">
          {error ?? 'Check-in not found.'}
        </p>
      </div>
    )
  }

  const sessionLabel = session ? `${session.course_code ?? ''} ${session.name}`.trim() : checkin.session_id
  const hasReview = Boolean(checkin.reviewed_by_id || checkin.reviewed_at || checkin.review_notes)
  const hasAppeal = Boolean(checkin.appeal_reason || checkin.appealed_at)

  return (
    <div className="space-y-4">
      <Link
        href="/dashboard/history"
        className="inline-flex min-h-[44px] items-center rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
      >
        Back to history
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{sessionLabel}</h1>
          {session?.venue_name && <p className="text-sm text-gray-500">{session.venue_name}</p>}
        </div>
        <StatusBadge status={checkin.status} />
      </div>

      <DetailCard title="Check-in">
        <Field label="Checked in at" value={new Date(checkin.checked_in_at).toLocaleString()} />
        {checkin.verified_at && (
          <Field label="Verified at" value={new Date(checkin.verified_at).toLocaleString()} />
        )}
      </DetailCard>

      <DetailCard title="Location">
        {checkin.latitude !== undefined && checkin.longitude !== undefined && (
          <Field label="Coordinates" value={`${checkin.latitude.toFixed(5)}, ${checkin.longitude.toFixed(5)}`} />
        )}
        {checkin.location_accuracy_meters !== undefined && (
          <Field label="GPS accuracy" value={`±${checkin.location_accuracy_meters.toFixed(0)} m`} />
        )}
        {checkin.distance_from_venue_meters !== undefined && (
          <Field label="Distance from venue" value={`${checkin.distance_from_venue_meters.toFixed(0)} m`} />
        )}
      </DetailCard>

      <DetailCard title="Verification">
        <div className="flex items-center justify-between py-1 text-sm">
          <span className="text-gray-500">Liveness check</span>
          <BooleanBadge value={checkin.liveness_passed} />
        </div>
        {checkin.liveness_score !== undefined && checkin.liveness_score !== null && (
          <Field label="Liveness score" value={checkin.liveness_score.toFixed(2)} />
        )}
        <div className="flex items-center justify-between py-1 text-sm">
          <span className="text-gray-500">Face match</span>
          <BooleanBadge value={checkin.face_match_passed} />
        </div>
        {checkin.face_match_score !== undefined && checkin.face_match_score !== null && (
          <Field label="Face match score" value={checkin.face_match_score.toFixed(2)} />
        )}
      </DetailCard>

      <DetailCard title="Risk assessment">
        <div className="flex items-center justify-between py-1 text-sm">
          <span className="text-gray-500">Risk score</span>
          <RiskBadge riskScore={checkin.risk_score} />
        </div>
        {checkin.risk_factors && checkin.risk_factors.length > 0 && (
          <ul className="mt-2 space-y-1">
            {checkin.risk_factors.map((factor, idx) => (
              <li key={`${factor.type}-${idx}`} className="flex items-center justify-between text-sm">
                <span className="text-gray-700 capitalize">{factor.type.replace(/_/g, ' ')}</span>
                <span className="text-gray-500">+{factor.weight.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
      </DetailCard>

      {hasReview && (
        <DetailCard title="Instructor review">
          {checkin.reviewed_at && <Field label="Reviewed at" value={new Date(checkin.reviewed_at).toLocaleString()} />}
          {checkin.review_notes && (
            <p className="pt-1 text-sm text-gray-700">{checkin.review_notes}</p>
          )}
        </DetailCard>
      )}

      <DetailCard title="Appeal">
        {hasAppeal ? (
          <>
            {checkin.appealed_at && <Field label="Appealed at" value={new Date(checkin.appealed_at).toLocaleString()} />}
            {checkin.appeal_reason && <p className="pt-1 text-sm text-gray-700">{checkin.appeal_reason}</p>}
          </>
        ) : APPEALABLE_STATUSES.has(checkin.status) ? (
          <AppealForm checkinId={checkin.id} onAppealed={handleAppealed} />
        ) : (
          <p className="text-sm text-gray-500">This check-in is not eligible for appeal.</p>
        )}
      </DetailCard>
    </div>
  )
}
