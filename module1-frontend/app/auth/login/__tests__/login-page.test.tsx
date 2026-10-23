import { act, fireEvent, render, screen } from '@testing-library/react'
import LoginPage from '@/app/auth/login/page'
import { AuthProvider } from '@/lib/context/AuthContext'
import { stubAdapter } from '@/test/axios-stub'

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }))

async function submit(email: string, password: string) {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
  })
}

describe('login page', () => {
  it('shows the locked-account message instead of a wrong-password message', async () => {
    stubAdapter(() => ({
      status: 429,
      data: { detail: 'Account locked due to too many failed login attempts', code: 'ACCOUNT_LOCKED' },
      headers: { 'retry-after': '827' },
    }))
    render(<AuthProvider><LoginPage /></AuthProvider>)
    await submit('s@e.edu', 'Correct-password-1')
    expect(screen.getByText('Too many failed sign-in attempts. This account is locked for 14 minutes.')).toBeTruthy()
    expect(screen.queryByText(/incorrect email or password/i)).toBeNull()
  })

  it('shows the wrong-credentials message on 401', async () => {
    stubAdapter(() => ({ status: 401, data: { detail: 'Incorrect email or password', code: 'INVALID_CREDENTIALS' } }))
    render(<AuthProvider><LoginPage /></AuthProvider>)
    await submit('s@e.edu', 'nope')
    expect(screen.getByText('Incorrect email or password.')).toBeTruthy()
  })

  it('has no sign-up link', () => {
    render(<AuthProvider><LoginPage /></AuthProvider>)
    expect(document.querySelector('a[href="/auth/register"]')).toBeNull()
  })
})
