import { RISK_LABEL, riskLevelFor } from '@/lib/utils/risk'

describe('riskLevelFor', () => {
  it('prefers a valid backend level over the score', () => {
    expect(riskLevelFor('CRITICAL', 0.1)).toBe('CRITICAL')
    expect(riskLevelFor('low', 0.95)).toBe('LOW')
  })

  it.each([
    [0, 'LOW'],
    [0.29, 'LOW'],
    [0.3, 'MEDIUM'],
    [0.49, 'MEDIUM'],
    [0.5, 'HIGH'],
    [0.69, 'HIGH'],
    [0.7, 'CRITICAL'],
    [1, 'CRITICAL'],
  ])('bands score %p as %p', (score, level) => {
    expect(riskLevelFor(undefined, score)).toBe(level)
  })

  it('falls back to the score for an unknown level', () => {
    expect(riskLevelFor('SEVERE', 0.75)).toBe('CRITICAL')
  })

  it('returns null without a usable level or score', () => {
    expect(riskLevelFor(null, null)).toBeNull()
    expect(riskLevelFor(undefined, Number.NaN)).toBeNull()
  })

  it('labels every level', () => {
    expect(RISK_LABEL).toEqual({ LOW: 'Low', MEDIUM: 'Medium', HIGH: 'High', CRITICAL: 'Critical' })
  })
})
