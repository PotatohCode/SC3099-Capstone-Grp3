import { act, fireEvent, render, screen } from '@testing-library/react'
import { ChangePasswordForm } from '@/app/dashboard/settings/change-password'
import { changePasswordErrorMessage, validatePasswordChange } from '@/lib/utils/password-change'
import { httpError, networkError, stubAdapter, type StubReply } from '@/test/axios-stub'
import { getAccessToken, setTokens } from '@/lib/utils/token-storage'

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: confirm } })
}

async function submit() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  })
}

describe('validatePasswordChange', () => {
  it.each([
    [{ current: '', next: 'newpass123', confirm: 'newpass123' }, 'Enter your current password.'],
    [{ current: 'old', next: 'short', confirm: 'short' }, 'New password must be at least 8 characters.'],
    [{ current: 'old', next: 'x'.repeat(129), confirm: 'x'.repeat(129) }, 'New password must be at most 128 characters.'],
    [{ current: 'old', next: 'newpass123', confirm: 'newpass124' }, "The new passwords don't match."],
    [{ current: 'samepass1', next: 'samepass1', confirm: 'samepass1' }, 'New password must be different from your current one.'],
    [{ current: 'old', next: 'x'.repeat(128), confirm: 'x'.repeat(128) }, null],
    [{ current: 'old', next: 'newpass1', confirm: 'newpass1' }, null],
    [{ current: 'old', next: '😀😀😀😀', confirm: '😀😀😀😀' }, 'New password must be at least 8 characters.'],
    [{ current: 'old', next: '😀'.repeat(128), confirm: '😀'.repeat(128) }, null],
    [{ current: 'old', next: '😀'.repeat(129), confirm: '😀'.repeat(129) }, 'New password must be at most 128 characters.'],
  ])('%# %o', (form, expected) => {
    expect(validatePasswordChange(form)).toBe(expected)
  })
})

describe('changePasswordErrorMessage', () => {
  it.each([
    [httpError(403, { code: 'PASSWORD_INCORRECT' }), /Current password is incorrect/],
    [httpError(400, { code: 'PASSWORD_UNCHANGED' }), /must be different/],
    [httpError(422, { detail: [{ msg: 'too short' }] }), /Passwords must be 8 to 128 characters/],
    [httpError(429, { code: 'ACCOUNT_LOCKED' }, { 'retry-after': '900' }), /^Too many failed sign-in attempts\. This account is locked for 15 minutes\.$/],
    [httpError(429, { code: 'ACCOUNT_LOCKED' }), /This account is locked\. Please try again later/],
    [httpError(429, { code: 'RATE_LIMITED' }), /Too many requests/],
    [networkError(), /Can't reach the server/],
    [httpError(500, {}), /Couldn't change your password/],
  ])('maps %#', (error, expected) => {
    expect(changePasswordErrorMessage(error)).toMatch(expected)
  })
})

describe('ChangePasswordForm', () => {
  beforeEach(() => setTokens('a1', 'r1'))

  it('labels the fields for password managers', () => {
    stubAdapter(() => ({ status: 404 }))
    render(<ChangePasswordForm />)
    expect(screen.getByLabelText('Current password').getAttribute('autocomplete')).toBe('current-password')
    expect(screen.getByLabelText('New password').getAttribute('autocomplete')).toBe('new-password')
    expect(screen.getByLabelText('Confirm new password').getAttribute('autocomplete')).toBe('new-password')
  })

  it.each([
    ['', 'newpass123', 'newpass123'],
    ['oldpass1', 'short', 'short'],
    ['oldpass1', 'newpass123', 'different1'],
    ['samepass1', 'samepass1', 'samepass1'],
  ])('sends nothing when the form is invalid (%s, %s, %s)', async (current, next, confirm) => {
    const calls = stubAdapter(() => ({ status: 204 }))
    render(<ChangePasswordForm />)
    fill(current, next, confirm)
    await submit()
    expect(calls).toHaveLength(0)
    expect(screen.getByRole('alert')).toBeTruthy()
  })

  it('sends one request when several submits land together', async () => {
    let release: () => void = () => undefined
    const calls = stubAdapter(() => ({ status: 204 }))
    const httpClient = (await import('@/lib/utils/http-client')).default
    const adapter = httpClient.defaults.adapter as NonNullable<typeof httpClient.defaults.adapter> & ((c: never) => Promise<never>)
    httpClient.defaults.adapter = ((config: never) =>
      new Promise((resolve) => (release = () => resolve(adapter(config))))) as typeof httpClient.defaults.adapter
    render(<ChangePasswordForm />)
    fill('oldpass1', 'newpass123', 'newpass123')
    const form = screen.getByRole('button', { name: 'Change password' }).closest('form') as HTMLFormElement
    await act(async () => {
      fireEvent.submit(form)
      fireEvent.submit(form)
      fireEvent.submit(form)
    })
    await act(async () => release())
    expect(calls).toHaveLength(1)
  })

  it('posts the change, clears the fields and keeps the session', async () => {
    const calls = stubAdapter(() => ({ status: 204 }))
    render(<ChangePasswordForm />)
    fill('oldpass1', 'newpass123', 'newpass123')
    await submit()
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({
      method: 'post',
      url: '/users/me/password',
      data: { current_password: 'oldpass1', new_password: 'newpass123' },
      authorization: 'Bearer a1',
    })
    expect(screen.getByRole('status').textContent).toMatch(/Password changed/)
    expect((screen.getByLabelText('Current password') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('New password') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('Confirm new password') as HTMLInputElement).value).toBe('')
    expect(getAccessToken()).toBe('a1')
  })

  it.each<[StubReply, RegExp]>([
    [{ status: 403, data: { code: 'PASSWORD_INCORRECT', detail: 'Password is incorrect' } }, /Current password is incorrect/],
    [{ status: 400, data: { code: 'PASSWORD_UNCHANGED' } }, /must be different/],
    [{ status: 429, data: { code: 'ACCOUNT_LOCKED' }, headers: { 'retry-after': '600' } }, /locked for 10 minutes/],
  ])('shows the backend error %# without logging out', async (reply, expected) => {
    const calls = stubAdapter(() => reply)
    render(<ChangePasswordForm />)
    fill('oldpass1', 'newpass123', 'newpass123')
    await submit()
    expect(calls).toHaveLength(1)
    expect(screen.getByRole('alert').textContent).toMatch(expected)
    expect(getAccessToken()).toBe('a1')
    expect((screen.getByLabelText('New password') as HTMLInputElement).value).toBe('newpass123')
  })
})
