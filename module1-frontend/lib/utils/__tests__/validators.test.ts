import { isValidCoordinate, isValidEmail, sanitizeText, validateLoginForm } from '@/lib/utils/validators'

describe('validators', () => {
  it('validates emails', () => {
    expect(isValidEmail('a@b.co')).toBe(true)
    expect(isValidEmail('not-an-email')).toBe(false)
  })

  it('validates coordinate ranges', () => {
    expect(isValidCoordinate(1.3483, 103.6831)).toBe(true)
    expect(isValidCoordinate(91, 0)).toBe(false)
    expect(isValidCoordinate(0, -181)).toBe(false)
    expect(isValidCoordinate(Number.NaN, 0)).toBe(false)
  })

  it('strips angle brackets', () => {
    expect(sanitizeText(' <b>hi</b> ')).toBe('bhi/b')
  })

  it('reports login form errors', () => {
    expect(validateLoginForm('bad', '')).toEqual([
      { field: 'email', message: 'Enter a valid email address.' },
      { field: 'password', message: 'Password is required.' },
    ])
    expect(validateLoginForm('a@b.co', 'x')).toEqual([])
  })
})
