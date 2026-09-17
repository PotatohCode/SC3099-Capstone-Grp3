'use client'

/**
 * Task 1.9: Check-In History View.
 * - GET /checkins/my-checkins with filters (course_id, limit)
 * - Columns: Date (date/time on separate lines), Course, Status - kept to 3 so the list
 *   never needs horizontal scroll on mobile (that used to hide the Risk/Action columns
 *   off-screen with no visual hint the table could scroll).
 * - Each row links to /dashboard/history/[id] for the full detail view (risk score,
 *   location, verification signals, review notes, and the Appeal action all live there
 *   now instead of being crammed into the table).
 * - Filters: course, status, and check-in month range (all client-side, over the already
 *   fetched list - the documented endpoint has no server-side filter/sort params beyond
 *   course_id).
 * - Sorting: clicking a column header cycles asc -> desc -> none (back to the server's
 *   default checked_in_at DESC order). Single-column sort - clicking a different header
 *   abandons whatever was sorted before and starts that column at ascending.
 * - Pagination (10 items/page) - client-side, since the documented endpoint has no
 *   `offset` parameter (API-SPECIFICATION.md returns a flat array, not a paginated
 *   envelope, for GET /checkins/my-checkins).
 */

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { getMyCheckIns } from '@/lib/services/checkin.service'
import { getMyEnrollments, type MyEnrollment } from '@/lib/services/enrollment.service'
import { extractErrorMessage } from '@/lib/utils/http-client'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { StatusBadge } from '@/components/StatusBadge'
import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'
import type { CheckInHistoryItem, CheckInStatus } from '@/lib/types'

const PAGE_SIZE = 10

const STATUS_OPTIONS: CheckInStatus[] = ['pending', 'approved', 'flagged', 'rejected', 'appealed']

type SortColumn = 'date' | 'course' | 'status'
type SortDirection = 'asc' | 'desc'

/** dd/mm/yy and HH:MM (24h), returned separately so they can render on two lines. */
function formatShortDateParts(iso: string): { date: string; time: string } {
  const d = new Date(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yy = String(d.getFullYear()).slice(-2)
  const HH = String(d.getHours()).padStart(2, '0')
  const MM = String(d.getMinutes()).padStart(2, '0')
  return { date: `${dd}/${mm}/${yy}`, time: `${HH}:${MM}` }
}

/** `from`/`to` are 'YYYY-MM' (from <input type="month">) or '' when unset. Inclusive of both whole months. */
function isWithinMonthRange(iso: string, from: string, to: string): boolean {
  const checkedAt = new Date(iso)
  if (from) {
    const [fy, fm] = from.split('-').map(Number)
    if (checkedAt < new Date(fy, fm - 1, 1, 0, 0, 0, 0)) return false
  }
  if (to) {
    const [ty, tm] = to.split('-').map(Number)
    if (checkedAt > new Date(ty, tm, 0, 23, 59, 59, 999)) return false
  }
  return true
}

function SortIcon({ active, direction }: { active: boolean; direction: SortDirection }) {
  if (!active) {
    return (
      <span aria-hidden="true" className="text-gray-300">
        ↕
      </span>
    )
  }
  return <span aria-hidden="true">{direction === 'asc' ? '↑' : '↓'}</span>
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
  const [statusFilter, setStatusFilter] = useState<CheckInStatus | 'all'>('all')
  const [monthFrom, setMonthFrom] = useState<string>('')
  const [monthTo, setMonthTo] = useState<string>('')
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
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
    return checkins.filter((c) => {
      if (courseFilter !== 'all' && c.course_code !== courseFilter) return false
      if (statusFilter !== 'all' && c.status !== statusFilter) return false
      if (!isWithinMonthRange(c.checked_in_at, monthFrom, monthTo)) return false
      return true
    })
  }, [checkins, courseFilter, statusFilter, monthFrom, monthTo])

  const sorted = useMemo(() => {
    if (!sortColumn) return filtered
    const dir = sortDirection === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      let cmp = 0
      if (sortColumn === 'date') {
        cmp = new Date(a.checked_in_at).getTime() - new Date(b.checked_in_at).getTime()
      } else if (sortColumn === 'course') {
        cmp = (a.course_code ?? '').localeCompare(b.course_code ?? '')
      } else if (sortColumn === 'status') {
        cmp = a.status.localeCompare(b.status)
      }
      return cmp * dir
    })
  }, [filtered, sortColumn, sortDirection])

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const pageItems = sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  function handleSortClick(column: SortColumn) {
    if (sortColumn !== column) {
      setSortColumn(column)
      setSortDirection('asc')
    } else if (sortDirection === 'asc') {
      setSortDirection('desc')
    } else {
      setSortColumn(null)
    }
    setPage(0)
  }

  function sortAriaValue(column: SortColumn): 'ascending' | 'descending' | 'none' {
    if (sortColumn !== column) return 'none'
    return sortDirection === 'asc' ? 'ascending' : 'descending'
  }

  function SortableHeader({ column, label }: { column: SortColumn; label: string }) {
    return (
      <th scope="col" className="whitespace-nowrap px-4 py-3" aria-sort={sortAriaValue(column)}>
        <button
          type="button"
          onClick={() => handleSortClick(column)}
          className="flex items-center gap-1 rounded text-xs font-medium uppercase text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          {label}
          <SortIcon active={sortColumn === column} direction={sortDirection} />
        </button>
      </th>
    )
  }

  if (isLoading) return <LoadingSpinner label="Loading check-in history..." />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Check-in History</h1>
      </div>

      <div className="flex flex-wrap items-end gap-3">
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

        <div>
          <label htmlFor="status-filter" className="sr-only">
            Filter by status
          </label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as CheckInStatus | 'all')
              setPage(0)
            }}
            className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm capitalize"
          >
            <option value="all">All statuses</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status} className="capitalize">
                {status}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-end gap-2">
          <div>
            <label htmlFor="month-from" className="block text-xs uppercase text-gray-500">
              From
            </label>
            <input
              id="month-from"
              type="month"
              value={monthFrom}
              max={monthTo || undefined}
              onChange={(e) => {
                setMonthFrom(e.target.value)
                setPage(0)
              }}
              className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="month-to" className="block text-xs uppercase text-gray-500">
              To
            </label>
            <input
              id="month-to"
              type="month"
              value={monthTo}
              min={monthFrom || undefined}
              onChange={(e) => {
                setMonthTo(e.target.value)
                setPage(0)
              }}
              className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
            />
          </div>
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {sorted.length === 0 && !error ? (
        <p className="text-sm text-gray-600">No check-ins found.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <SortableHeader column="date" label="Date" />
                <SortableHeader column="course" label="Course" />
                <SortableHeader column="status" label="Status" />
              </tr>
            </thead>
            <tbody>
              {pageItems.map((item) => {
                const courseLabel = item.course_code ?? '-'
                const { date, time } = formatShortDateParts(item.checked_in_at)
                return (
                  <tr
                    key={item.id}
                    className="relative border-t border-gray-100 hover:bg-gray-50 focus-within:bg-gray-50"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                      <div className="flex flex-col leading-tight">
                        <span>{date}</span>
                        <span className="text-gray-500">{time}</span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                      <Link
                        href={`/dashboard/history/${item.id}`}
                        className="static after:absolute after:inset-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                        aria-label={`View check-in for ${courseLabel} on ${date} at ${time}`}
                      >
                        {courseLabel}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <StatusBadge status={item.status} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {sorted.length > PAGE_SIZE && (
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
