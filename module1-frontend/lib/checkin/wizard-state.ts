/** Pure reducer for the check-in wizard; every submit outcome and every return to the camera step discards captured media. */
import type { CapturedMedia } from '@/lib/checkin/payload'
import type { CheckInResponse, LocationData, SessionSummary } from '@/lib/types'

export type CheckInStep = 'session-select' | 'location' | 'camera' | 'confirm'

export const STEP_ORDER: CheckInStep[] = ['session-select', 'location', 'camera', 'confirm']

export interface WizardState {
  step: CheckInStep
  session: SessionSummary | null
  location: LocationData | null
  media: CapturedMedia | null
  result: CheckInResponse | null
  challengeInvalidStreak: number
}

export type WizardAction =
  | { type: 'SELECT_SESSION'; session: SessionSummary }
  | { type: 'SET_LOCATION'; location: LocationData }
  | { type: 'SET_MEDIA'; media: CapturedMedia }
  | { type: 'GO_TO'; step: CheckInStep }
  | { type: 'CONTINUE' }
  | { type: 'RETAKE_LOCATION' }
  | { type: 'BACK' }
  | { type: 'SUBMIT_SUCCEEDED'; result: CheckInResponse }
  | { type: 'SUBMIT_QUEUED' }
  | { type: 'SUBMIT_FAILED'; challengeInvalid: boolean }
  | { type: 'RESET' }

export const initialWizardState: WizardState = {
  step: 'session-select',
  session: null,
  location: null,
  media: null,
  result: null,
  challengeInvalidStreak: 0,
}

function goTo(state: WizardState, step: CheckInStep): WizardState {
  return step === 'camera' || step === 'location' || step === 'session-select'
    ? { ...state, step, media: null }
    : { ...state, step }
}

/** Applies one wizard transition. */
export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case 'SELECT_SESSION':
      return { ...initialWizardState, session: action.session, step: 'location' }
    case 'SET_LOCATION':
      return state.step === 'location' ? { ...state, location: action.location, media: null, step: 'camera' } : state
    case 'SET_MEDIA':
      return state.step === 'camera' ? { ...state, media: action.media, step: 'confirm' } : state
    case 'RETAKE_LOCATION':
      return { ...state, location: null, media: null, step: 'location' }
    case 'CONTINUE':
      return state.step === 'location' && state.location ? { ...state, media: null, step: 'camera' } : state
    case 'GO_TO':
      return goTo(state, action.step)
    case 'BACK': {
      const index = STEP_ORDER.indexOf(state.step)
      return goTo(state, STEP_ORDER[Math.max(index - 1, 0)])
    }
    case 'SUBMIT_SUCCEEDED':
      return { ...state, media: null, result: action.result, challengeInvalidStreak: 0 }
    case 'SUBMIT_QUEUED':
      return { ...state, media: null }
    case 'SUBMIT_FAILED':
      return {
        ...state,
        media: null,
        challengeInvalidStreak: action.challengeInvalid ? state.challengeInvalidStreak + 1 : state.challengeInvalidStreak,
      }
    case 'RESET':
      return { ...initialWizardState }
    default:
      return state
  }
}

/** True once two CHALLENGE_INVALID results have occurred since the last success, when the wizard switches to a single photo. */
export function shouldUsePhotoMode(state: WizardState): boolean {
  return state.challengeInvalidStreak >= 2
}
