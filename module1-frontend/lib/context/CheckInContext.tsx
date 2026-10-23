'use client'

/**
 * Task 1.2: Check-In Workflow Pipeline - "Implement state machine: only proceed if
 * each step complete."
 * Decision 2 (Section 9): CheckInContext holds wizard state across the 4 steps:
 *   1. session-select  2. location  3. camera  4. confirm
 *
 * Privacy note: captured media lives only in memory (React state) for the duration of
 * the wizard and is cleared on submit/reset - it is never written to any storage layer.
 */

import { createContext, useCallback, useMemo, useReducer, type ReactNode } from 'react'
import type { CapturedMedia } from '@/lib/checkin/payload'
import {
  initialWizardState,
  shouldUsePhotoMode,
  wizardReducer,
  type CheckInStep,
} from '@/lib/checkin/wizard-state'
import type { CheckInResponse, LocationData, SessionSummary } from '@/lib/types'

export type { CheckInStep }

interface CheckInContextValue {
  step: CheckInStep
  session: SessionSummary | null
  location: LocationData | null
  media: CapturedMedia | null
  result: CheckInResponse | null
  photoMode: boolean
  selectSession: (session: SessionSummary) => void
  setLocation: (location: LocationData) => void
  setMedia: (media: CapturedMedia) => void
  goToStep: (step: CheckInStep) => void
  continueFromLocation: () => void
  retakeLocation: () => void
  previousStep: () => void
  submitSucceeded: (result: CheckInResponse) => void
  submitQueued: () => void
  submitFailed: (challengeInvalid: boolean) => void
  reset: () => void
}

export const CheckInContext = createContext<CheckInContextValue | undefined>(undefined)

export function CheckInProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(wizardReducer, initialWizardState)

  const selectSession = useCallback((session: SessionSummary) => dispatch({ type: 'SELECT_SESSION', session }), [])
  const setLocation = useCallback((location: LocationData) => dispatch({ type: 'SET_LOCATION', location }), [])
  const setMedia = useCallback((media: CapturedMedia) => dispatch({ type: 'SET_MEDIA', media }), [])
  const goToStep = useCallback((step: CheckInStep) => dispatch({ type: 'GO_TO', step }), [])
  const previousStep = useCallback(() => dispatch({ type: 'BACK' }), [])
  const continueFromLocation = useCallback(() => dispatch({ type: 'CONTINUE' }), [])
  const retakeLocation = useCallback(() => dispatch({ type: 'RETAKE_LOCATION' }), [])
  const submitSucceeded = useCallback((result: CheckInResponse) => dispatch({ type: 'SUBMIT_SUCCEEDED', result }), [])
  const submitQueued = useCallback(() => dispatch({ type: 'SUBMIT_QUEUED' }), [])
  const submitFailed = useCallback(
    (challengeInvalid: boolean) => dispatch({ type: 'SUBMIT_FAILED', challengeInvalid }),
    []
  )
  const reset = useCallback(() => dispatch({ type: 'RESET' }), [])

  const value = useMemo<CheckInContextValue>(
    () => ({
      step: state.step,
      session: state.session,
      location: state.location,
      media: state.media,
      result: state.result,
      photoMode: shouldUsePhotoMode(state),
      selectSession,
      setLocation,
      setMedia,
      goToStep,
      continueFromLocation,
      retakeLocation,
      previousStep,
      submitSucceeded,
      submitQueued,
      submitFailed,
      reset,
    }),
    [state, selectSession, setLocation, setMedia, goToStep, continueFromLocation, retakeLocation, previousStep, submitSucceeded, submitQueued, submitFailed, reset]
  )

  return <CheckInContext.Provider value={value}>{children}</CheckInContext.Provider>
}
