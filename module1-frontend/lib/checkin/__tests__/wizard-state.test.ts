import type { CapturedMedia } from '@/lib/checkin/payload'
import { initialWizardState, shouldUsePhotoMode, STEP_ORDER, wizardReducer, type WizardState } from '@/lib/checkin/wizard-state'
import type { CheckInResponse, SessionSummary } from '@/lib/types'

const session = { id: 's1', course_id: 'c1', name: 'Lecture 1', status: 'active', scheduled_start: '', scheduled_end: '' } as SessionSummary
const location = { latitude: 1.35, longitude: 103.8, accuracy: 10 }
const media: CapturedMedia = { kind: 'photo', photo: 'p1' }
const result = { id: 'ci1', status: 'approved' } as CheckInResponse

function atConfirm(): WizardState {
  let s = wizardReducer(initialWizardState, { type: 'SELECT_SESSION', session })
  s = wizardReducer(s, { type: 'SET_LOCATION', location })
  return wizardReducer(s, { type: 'SET_MEDIA', media })
}

describe('wizardReducer', () => {
  it('orders steps session, location, camera, confirm', () => {
    expect(STEP_ORDER).toEqual(['session-select', 'location', 'camera', 'confirm'])
    let s = wizardReducer(initialWizardState, { type: 'SELECT_SESSION', session })
    expect(s.step).toBe('location')
    s = wizardReducer(s, { type: 'SET_LOCATION', location })
    expect(s.step).toBe('camera')
    s = wizardReducer(s, { type: 'SET_MEDIA', media })
    expect(s).toMatchObject({ step: 'confirm', session, location, media })
  })

  it('clears media after a failed submit and keeps session and location', () => {
    const s = wizardReducer(atConfirm(), { type: 'SUBMIT_FAILED', challengeInvalid: false })
    expect(s.media).toBeNull()
    expect(s.session).toBe(session)
    expect(s.location).toBe(location)
  })

  it('clears media after a successful or queued submit', () => {
    expect(wizardReducer(atConfirm(), { type: 'SUBMIT_SUCCEEDED', result })).toMatchObject({ media: null, result })
    expect(wizardReducer(atConfirm(), { type: 'SUBMIT_QUEUED' }).media).toBeNull()
  })

  it('clears media whenever the camera step is entered again', () => {
    expect(wizardReducer(atConfirm(), { type: 'GO_TO', step: 'camera' })).toMatchObject({ step: 'camera', media: null })
    expect(wizardReducer(atConfirm(), { type: 'BACK' })).toMatchObject({ step: 'camera', media: null })
    expect(wizardReducer(atConfirm(), { type: 'GO_TO', step: 'location' })).toMatchObject({ step: 'location', media: null, location })
  })

  it('retaking the location clears it and any media', () => {
    const s = wizardReducer(atConfirm(), { type: 'RETAKE_LOCATION' })
    expect(s).toMatchObject({ step: 'location', location: null, media: null })
    const next = wizardReducer(s, { type: 'SET_LOCATION', location: { latitude: 1.3, longitude: 103.7 } })
    expect(next).toMatchObject({ step: 'camera', media: null })
  })

  it('selecting a session starts from a clean state', () => {
    const s = wizardReducer(atConfirm(), { type: 'SELECT_SESSION', session: { ...session, id: 's2' } })
    expect(s).toMatchObject({ location: null, media: null, result: null, step: 'location' })
  })

  it('switches to photo mode after two consecutive invalid challenges and resets on success', () => {
    let s = wizardReducer(atConfirm(), { type: 'SUBMIT_FAILED', challengeInvalid: true })
    expect(shouldUsePhotoMode(s)).toBe(false)
    s = wizardReducer(s, { type: 'SUBMIT_FAILED', challengeInvalid: true })
    expect(shouldUsePhotoMode(s)).toBe(true)
    s = wizardReducer(s, { type: 'SUBMIT_FAILED', challengeInvalid: false })
    expect(shouldUsePhotoMode(s)).toBe(true)
    s = wizardReducer(s, { type: 'SUBMIT_SUCCEEDED', result })
    expect(shouldUsePhotoMode(s)).toBe(false)
  })

  it('BACK from the first step stays put, and RESET returns the initial state', () => {
    expect(wizardReducer(initialWizardState, { type: 'BACK' }).step).toBe('session-select')
    expect(wizardReducer(atConfirm(), { type: 'RESET' })).toEqual(initialWizardState)
  })

  it('ignores a late location result after the student went back', () => {
    let s = wizardReducer(initialWizardState, { type: 'SELECT_SESSION', session })
    s = wizardReducer(s, { type: 'BACK' })
    s = wizardReducer(s, { type: 'SET_LOCATION', location })
    expect(s).toMatchObject({ step: 'session-select', location: null })
  })

  it('ignores media that arrives when the camera step is no longer shown', () => {
    let s = wizardReducer(initialWizardState, { type: 'SELECT_SESSION', session })
    s = wizardReducer(s, { type: 'SET_LOCATION', location })
    s = wizardReducer(s, { type: 'BACK' })
    s = wizardReducer(s, { type: 'SET_MEDIA', media })
    expect(s).toMatchObject({ step: 'location', media: null })
  })

  it('CONTINUE from location keeps the known location and goes to the camera', () => {
    let s = wizardReducer(atConfirm(), { type: 'GO_TO', step: 'location' })
    s = wizardReducer(s, { type: 'CONTINUE' })
    expect(s).toMatchObject({ step: 'camera', location, media: null })
  })
})
