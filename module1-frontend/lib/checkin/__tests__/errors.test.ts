import { classifyChallengeError, classifyCheckInError } from '@/lib/checkin/errors'
import { PayloadTooLargeError } from '@/lib/checkin/payload'
import { httpError, networkError } from '@/test/axios-stub'

describe('classifyCheckInError', () => {
  it('explains OUTSIDE_SINGAPORE, says nothing was saved, and allows retry', () => {
    const view = classifyCheckInError(
      httpError(403, { detail: 'Check-in only allowed from within Singapore', code: 'OUTSIDE_SINGAPORE' }),
      true
    )
    expect(view).toEqual({
      title: 'Check-in not available here',
      message: "Check-in is only available within Singapore. If you're using a VPN, turn it off and try again.",
      secondary: 'Nothing was saved, so you can try again.',
      action: 'retry-location',
      alternateAction: 'retry-capture',
    })
  })

  it('tells a 403 NOT_ENROLLED apart from the Singapore rule by code', () => {
    const view = classifyCheckInError(httpError(403, { code: 'NOT_ENROLLED' }), true)
    expect(view.message).toBe("You're not enrolled in this course.")
    expect(view.action).toBe('reselect-session')
  })

  it.each([
    [400, 'CHALLENGE_INVALID', "That check took too long. Let's try again.", 'retry-capture'],
    [404, 'SESSION_NOT_FOUND', 'This session no longer exists. Please choose another session.', 'reselect-session'],
    [400, 'SESSION_NOT_ACTIVE', 'Check-in for this session is closed.', 'reselect-session'],
    [400, 'SESSION_WINDOW_CLOSED', 'Check-in for this session is closed.', 'reselect-session'],
    [400, 'ALREADY_CHECKED_IN', "You've already checked in to this session. You can view it, or appeal it, in your history.", 'view-history'],
    [403, 'CONSENT_REQUIRED', 'Camera and location permission are needed to check in. Please allow both and try again.', 'retry-location'],
    [413, 'TOO_MANY_FRAMES', 'Something went wrong with the face check. Please try again.', 'retry-capture'],
    [413, 'IMAGE_TOO_LARGE', 'Photo too large, please retake.', 'retry-capture'],
    [413, 'REQUEST_TOO_LARGE', 'Photo too large, please retake.', 'retry-capture'],
    [422, undefined, 'Some check-in details were invalid. Please try again.', 'retry-location'],
    [500, undefined, 'The server had a problem. Please try again.', 'retry-capture'],
  ])('%p %p -> message and %p', (status, code, message, action) => {
    const view = classifyCheckInError(httpError(status, code ? { code } : { detail: [{ msg: 'x' }] }), true)
    expect(view.message).toBe(message)
    expect(view.action).toBe(action)
  })

  it('marks CHALLENGE_INVALID for the streak counter', () => {
    expect(classifyCheckInError(httpError(400, { code: 'CHALLENGE_INVALID' }), true).challengeInvalid).toBe(true)
  })

  it('shows the rate-limit wait time', () => {
    expect(classifyCheckInError(httpError(429, { code: 'RATE_LIMITED' }, { 'retry-after': '42' }), true).message).toBe(
      'Too many check-in attempts. Please wait 42 seconds and try again.'
    )
  })

  it('queues only when the browser is offline', () => {
    expect(classifyCheckInError(networkError(), false).action).toBe('queue-offline')
    expect(classifyCheckInError(networkError(), true)).toEqual({
      message: "We couldn't reach the server. Check your connection and try again.",
      action: 'retry-capture',
    })
  })

  it('maps a client-side size error and unknown errors', () => {
    expect(classifyCheckInError(new PayloadTooLargeError('x'), true).message).toBe('Photo too large, please retake.')
    expect(classifyCheckInError(httpError(400, { detail: 'Odd', code: 'SOMETHING_NEW' }), true).message).toBe('Odd')
    expect(classifyCheckInError(new Error('x'), true).message).toBe('Check-in failed. Please try again.')
  })
})

describe('classifyChallengeError', () => {
  it('falls back to a photo on 503 or no response', () => {
    expect(classifyChallengeError(httpError(503, { code: 'CHALLENGE_UNAVAILABLE' }))).toEqual({ fallbackToPhoto: true })
    expect(classifyChallengeError(networkError())).toEqual({ fallbackToPhoto: true })
  })

  it('sends session problems back to session select', () => {
    const r = classifyChallengeError(httpError(400, { code: 'SESSION_WINDOW_CLOSED' }))
    expect(r).toEqual({ fallbackToPhoto: false, view: { message: 'Check-in for this session is closed.', action: 'reselect-session' } })
  })

  it('shows a wait message on 429 and a generic retry otherwise', () => {
    const limited = classifyChallengeError(httpError(429, { code: 'RATE_LIMITED' }, { 'retry-after': '10' }))
    expect(limited).toEqual({
      fallbackToPhoto: false,
      view: { message: 'Too many attempts. Please wait 10 seconds and try again.', action: 'retry-capture' },
    })
    const other = classifyChallengeError(httpError(500, {}))
    expect(other).toEqual({
      fallbackToPhoto: false,
      view: { message: "We couldn't start the face check. Please try again.", action: 'retry-capture' },
    })
  })
})
