'use client'

/**
 * Task 1.9: Check-In History View.
 * - GET /checkins/my-checkins with filters (course_id, limit)
 * - Date, Course, Session, Status, Risk Score columns
 * - Color-coded status + risk badges
 * - Filter dropdown by course
 * - Pagination (10 items/page) - client-side, since the documented endpoint has no
 *   `offset` parameter (API-SPECIFICATION.md returns a flat array, not a paginated
 *   envelope, for GET /checkins/my-checkins).
 * - "Appeal" action on flagged/rejected items
 */

import { useEffect, useMemo, useState } from 'react'
import { getMyCheckIns, appealCheckIn } from '@/lib/services/checkin.service'
import { getMyEnrollments, type MyEnrollment } from '@/lib/services/enrollment.service'
import { extractErrorMessage } from '@/lib/utils/http-client'
import { sanitizeText } from '@/lib/utils/validators'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { StatusBadge, RiskBadge } from '@/components/StatusBadge'
import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'
import type { CheckInHistoryItem } from '@/lib/types'

const PAGE_SIZE = 10
const APPEALABLE_STATUSES = new Set(['flagged', 'rejected'])

function AppealForm({
  checkinId,
  onAppealed,
}: {
  checkinId: string
  onAppealed: (updated: CheckInHistoryItem) => void
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
        className="min-h-[36px] rounded-md border border-blue-300 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50"
      >
        Appeal
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
        id: checkinId,
        status: response.status,
        appeal_reason: response.appeal_reason,
        appealed_at: response.appealed_at,
      } as CheckInHistoryItem)
      setIsOpen(false)
    } catch (err) {
      setError(extractErrorMessage(err, 'Failed to submit appeal.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="mt-2 space-y-2 rounded-md border border-gray-200 bg-gray-50 p-3">
      <label htmlFor={`appeal-${checkinId}`} className="block text-xs font-medium text-gray-700">
        Why should this check-in be reconsidered?
      </label>
      <textarea
        id={`appeal-${checkinId}`}
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
          className="min-h-[36px] rounded-md bg-blue-700 px-3 py-1 text-xs font-medium text-white hover:bg-blue-800 disabled:opacity-60"
        >
          {isSubmitting ? 'Submitting...' : 'Submit appeal'}
        </button>
        <button
          type="button"
          onClick={() => setIsOpen(false)}
          className="min-h-[36px] rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

export default function HistoryPage() {
  return (
    <StudentOnlyGuard>
      <HistoryPageContent />
    </StudentOnlyGuard>
  )
}

function HistoryPageContent() {
  const [checkins, setCheckins] = useState<CheckInHistoryItem[]>([])
  const [enrollments, setEnrollments] = useState<MyEnrollment[]>([])
  const [courseFilter, setCourseFilter] = useState<string>('all')
  const [page, setPage] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setIsLoading(true)
      setError(null)
      try {
        const [checkinData, enrollmentData] = await Promise.all([
          getMyCheckIns({ limit: 100 }),
          getMyEnrollments().catch(() => []),
        ])
        if (!cancelled) {
          setCheckins(checkinData)
          setEnrollments(enrollmentData)
        }
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err, 'Failed to load check-in history.'))
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    if (courseFilter === 'all') return checkins
    return checkins.filter((c) => c.course_code === courseFilter)
  }, [checkins, courseFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageItems = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  function handleAppealed(updated: CheckInHistoryItem) {
    setCheckins((prev) =>
      prev.map((c) => (c.id === updated.id ? { ...c, ...updated } : c))
    )
  }

  if (isLoading) return <LoadingSpinner label="Loading check-in history..." />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Check-in History</h1>
        <div>
          <label htmlFor="course-filter" className="sr-only">
            Filter by course
          </label>
          <select
            id="course-filter"
            value={courseFilter}
            onChange={(e) => {
              setCourseFilter(e.target.value)
              setPage(0)
            }}
            className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
          >
            <option value="all">All courses</option>
            {enrollments.map((enrollment) => (
              <option key={enrollment.id} value={enrollment.course_code}>
                {enrollment.course_code}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {filtered.length === 0 && !error ? (
        <p className="text-sm text-gray-600">No check-ins found.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Course</th>
                <th className="px-4 py-3">Session</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((item) => (
                <tr key={item.id} className="border-t border-gray-100">
                  <td className="px-4 py-3 text-gray-700">
                    {new Date(item.checked_in_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-gray-700">{item.course_code ?? '-'}</td>
                  <td className="px-4 py-3 text-gray-700">{item.session_name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3">
                    <RiskBadge riskScore={item.risk_score} />
                  </td>
                  <td className="px-4 py-3">
                    {APPEALABLE_STATUSES.has(item.status) ? (
                      <AppealForm checkinId={item.id} onAppealed={handleAppealed} />
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="min-h-[44px] rounded-md border border-gray-300 px-3 py-1.5 font-medium text-gray-700 disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-gray-500">
            Page {page + 1} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="min-h-[44px] rounded-md border border-gray-300 px-3 py-1.5 font-medium text-gray-700 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
