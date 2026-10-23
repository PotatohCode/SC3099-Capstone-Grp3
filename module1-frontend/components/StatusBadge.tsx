/**
 * Task 1.9: "Color-coded status badges + risk score badges"
 */

import type { CheckInStatus, RiskLevel } from '@/lib/types'
import { RISK_LABEL, riskLevelFor } from '@/lib/utils/risk'

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

const RISK_STYLES: Record<RiskLevel, string> = {
  LOW: 'bg-green-100 text-green-700 border-green-300',
  MEDIUM: 'bg-amber-100 text-amber-700 border-amber-300',
  HIGH: 'bg-red-100 text-red-700 border-red-300',
  CRITICAL: 'bg-red-700 text-white border-red-800',
}

/** Shows the risk band (backend risk_level first, score bands as fallback) with the score when known. */
export function RiskBadge({
  riskLevel,
  riskScore,
}: {
  riskLevel?: string | null
  riskScore?: number | null
}) {
  const level = riskLevelFor(riskLevel, riskScore)
  if (!level) {
    return (
      <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
        N/A
      </span>
    )
  }
  const hasScore = typeof riskScore === 'number' && Number.isFinite(riskScore)
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${RISK_STYLES[level]}`}>
      {hasScore ? `${RISK_LABEL[level]} (${riskScore.toFixed(2)})` : RISK_LABEL[level]}
    </span>
  )
}
