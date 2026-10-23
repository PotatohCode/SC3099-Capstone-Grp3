/** Maps a backend risk_level (or a risk score fallback) to the LOW/MEDIUM/HIGH/CRITICAL bands of Module 2. */
import type { RiskLevel } from '@/lib/types'

const LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

export const RISK_LABEL: Record<RiskLevel, string> = {
  LOW: 'Low',
  MEDIUM: 'Medium',
  HIGH: 'High',
  CRITICAL: 'Critical',
}

/** Returns the backend level when valid, else the band for the score, else null. */
export function riskLevelFor(
  level: string | null | undefined,
  score: number | null | undefined
): RiskLevel | null {
  const normalized = typeof level === 'string' ? level.toUpperCase() : null
  if (normalized && (LEVELS as string[]).includes(normalized)) return normalized as RiskLevel
  if (typeof score !== 'number' || !Number.isFinite(score)) return null
  if (score < 0.3) return 'LOW'
  if (score < 0.5) return 'MEDIUM'
  if (score < 0.7) return 'HIGH'
  return 'CRITICAL'
}
