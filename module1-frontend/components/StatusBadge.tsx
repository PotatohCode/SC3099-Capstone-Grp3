/**
 * Task 1.9: "Color-coded status badges + risk score badges"
 */

import type { CheckInStatus } from '@/lib/types'

const STATUS_STYLES: Record<CheckInStatus, string> = {
  pending: 'bg-gray-100 text-gray-700 border-gray-300',
  approved: 'bg-green-100 text-green-700 border-green-300',
  flagged: 'bg-amber-100 text-amber-700 border-amber-300',
  rejected: 'bg-red-100 text-red-700 border-red-300',
  appealed: 'bg-blue-100 text-blue-700 border-blue-300',
}

export function StatusBadge({ status }: { status: CheckInStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status] ?? STATUS_STYLES.pending}`}
    >
      {status}
    </span>
  )
}

/** docs/API-SPECIFICATION.md risk_distribution: low < 0.3, medium 0.3-0.5, high >= 0.5 */
export function RiskBadge({ riskScore }: { riskScore: number | null | undefined }) {
  if (riskScore === null || riskScore === undefined) {
    return (
      <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
        N/A
      </span>
    )
  }

  let styles = 'bg-green-100 text-green-700 border-green-300'
  let label = 'Low'
  if (riskScore >= 0.5) {
    styles = 'bg-red-100 text-red-700 border-red-300'
    label = 'High'
  } else if (riskScore >= 0.3) {
    styles = 'bg-amber-100 text-amber-700 border-amber-300'
    label = 'Medium'
  }

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles}`}>
      {label} ({riskScore.toFixed(2)})
    </span>
  )
}
