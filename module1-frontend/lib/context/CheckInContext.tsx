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

import { createContext, useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import type { CapturedMedia } from '@/lib/checkin/payload'
import {
  initialWizardState,
  shouldUsePhotoMode,
  wizardReducer,
  type AlreadyCheckedIn,
  type CheckInStep,
} from '@/lib/checkin/wizard-state'
import type { CheckInResponse, LocationData, SessionSummary } from '@/lib/types'
import { useAuth } from '@/lib/hooks/useAuth'
import { CHECKIN_RESTART_EVENT, forgetLegacyProgress } from '@/lib/checkin/restart'
import { clearAttempts } from '@/lib/liveness/verify'

export type { CheckInStep }

interface CheckInContextValue {
  step: CheckInStep
  session: SessionSummary | null
  location: LocationData | null
  media: CapturedMedia | null
  result: CheckInResponse | null
  photoMode: boolean
  alreadyCheckedIn: AlreadyCheckedIn
  restartCount: number
  setSubmitting: (submitting: boolean) => void
  selectSession: (session: SessionSummary) => void
  markAlreadyCheckedIn: (session: SessionSummary, queued: boolean) => void
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

  const { user } = useAuth()
  const userId = user?.id ?? null
  const stateRef = useRef(state)
  stateRef.current = state
  const submittingRef = useRef(false)
  const [restartCount, setRestartCount] = useState(0)

  const selectSession = useCallback((session: SessionSummary) => dispatch({ type: 'SELECT_SESSION', session }), [])
  const markAlreadyCheckedIn = useCallback(
    (session: SessionSummary, queued: boolean) => {
      if (userId) clearAttempts(userId, session.id)
      dispatch({ type: 'ALREADY_CHECKED_IN', session, queued })
    },
    [userId]
  )
  const setLocation = useCallback((location: LocationData) => dispatch({ type: 'SET_LOCATION', location }), [])
  const setMedia = useCallback((media: CapturedMedia) => dispatch({ type: 'SET_MEDIA', media }), [])
  const goToStep = useCallback((step: CheckInStep) => dispatch({ type: 'GO_TO', step }), [])
  const previousStep = useCallback(() => dispatch({ type: 'BACK' }), [])
  const continueFromLocation = useCallback(() => dispatch({ type: 'CONTINUE' }), [])
  const retakeLocation = useCallback(() => dispatch({ type: 'RETAKE_LOCATION' }), [])
  const finishSession = useCallback(() => {
    const sessionId = stateRef.current.session?.id
    if (userId && sessionId) clearAttempts(userId, sessionId)
  }, [userId])
  const submitSucceeded = useCallback(
    (result: CheckInResponse) => {
      finishSession()
      dispatch({ type: 'SUBMIT_SUCCEEDED', result })
    },
    [finishSession]
  )
  const submitQueued = useCallback(() => {
    finishSession()
    dispatch({ type: 'SUBMIT_QUEUED' })
  }, [finishSession])
  const submitFailed = useCallback(
    (challengeInvalid: boolean) => dispatch({ type: 'SUBMIT_FAILED', challengeInvalid }),
    []
  )
  const reset = useCallback(() => dispatch({ type: 'RESET' }), [])
  const setSubmitting = useCallback((submitting: boolean) => {
    submittingRef.current = submitting
  }, [])

  useEffect(() => {
    forgetLegacyProgress()
    function restart() {
      if (submittingRef.current) return
      setRestartCount((n) => n + 1)
      dispatch({ type: 'RESET' })
    }
    window.addEventListener(CHECKIN_RESTART_EVENT, restart)
    return () => window.removeEventListener(CHECKIN_RESTART_EVENT, restart)
  }, [])

  const value = useMemo<CheckInContextValue>(
    () => ({
      step: state.step,
      session: state.session,
      location: state.location,
      media: state.media,
      result: state.result,
      photoMode: shouldUsePhotoMode(state),
      alreadyCheckedIn: state.alreadyCheckedIn,
      restartCount,
      setSubmitting,
      selectSession,
      markAlreadyCheckedIn,
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
    [state, restartCount, setSubmitting, selectSession, markAlreadyCheckedIn, setLocation, setMedia, goToStep, continueFromLocation, retakeLocation, previousStep, submitSucceeded, submitQueued, submitFailed, reset]
  )

  return <CheckInContext.Provider value={value}>{children}</CheckInContext.Provider>
}
