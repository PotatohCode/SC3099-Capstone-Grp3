import { render, screen } from '@testing-library/react'
import { RiskBadge, StatusBadge } from '@/components/StatusBadge'

describe('RiskBadge', () => {
  it('shows CRITICAL from risk_level as Critical with the score', () => {
    render(<RiskBadge riskLevel="CRITICAL" riskScore={0.77} />)
    expect(screen.getByText('Critical (0.77)')).toBeTruthy()
  })

  it('shows Critical for a score of 0.75 without a level', () => {
    render(<RiskBadge riskScore={0.75} />)
    expect(screen.getByText('Critical (0.75)')).toBeTruthy()
  })

  it('shows the level alone when there is no score', () => {
    render(<RiskBadge riskLevel="HIGH" />)
    expect(screen.getByText('High')).toBeTruthy()
  })

  it('shows N/A when nothing is known', () => {
    render(<RiskBadge riskLevel={null} riskScore={null} />)
    expect(screen.getByText('N/A')).toBeTruthy()
  })

  it('uses a distinct style for Critical', () => {
    render(<RiskBadge riskLevel="CRITICAL" riskScore={0.9} />)
    expect(screen.getByText('Critical (0.90)').className).toContain('bg-red-700')
  })
})

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="flagged" />)
    expect(screen.getByText('flagged')).toBeTruthy()
  })
})
