'use client'

/**
 * Task 1.2: Check-In Workflow Pipeline - "Implement state machine: only proceed if
 * each step complete."
 * Decision 2 (Section 9): CheckInContext holds wizard state across the 4 steps:
 *   1. session-select  2. camera  3. location  4. confirm
 *
 * Privacy note: `capturedImage` lives only in memory (React state) for the duration of
 * the wizard and is cleared on submit/reset - it is never written to any storage layer.
 */

import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react'
import type { CheckInResponse, SessionSummary } from '@/lib/types'

export type CheckInStep = 'session-select' | 'camera' | 'location' | 'confirm'

const STEP_ORDER: CheckInStep[] = ['session-select', 'camera', 'location', 'confirm']

export interface LocationData {
  latitude: number
  longitude: number
  accuracy: number
}

interface CheckInContextValue {
  step: CheckInStep
  session: SessionSummary | null
  capturedImage: string | null
  location: LocationData | null
  result: CheckInResponse | null
  setSession: (session: SessionSummary) => void
  setCapturedImage: (image: string | null) => void
  setLocation: (location: LocationData | null) => void
  setResult: (result: CheckInResponse | null) => void
  goToStep: (step: CheckInStep) => void
  nextStep: () => void
  previousStep: () => void
  canProceedFrom: (step: CheckInStep) => boolean
  reset: () => void
}

export const CheckInContext = createContext<CheckInContextValue | undefined>(undefined)

export function CheckInProvider({ children }: { children: ReactNode }) {
  const [step, setStep] = useState<CheckInStep>('session-select')
  const [session, setSessionState] = useState<SessionSummary | null>(null)
  const [capturedImage, setCapturedImage] = useState<string | null>(null)
  const [location, setLocation] = useState<LocationData | null>(null)
  const [result, setResult] = useState<CheckInResponse | null>(null)

  const canProceedFrom = useCallback(
    (targetStep: CheckInStep): boolean => {
      switch (targetStep) {
        case 'session-select':
          return session !== null
        case 'camera':
          return capturedImage !== null
        case 'location':
          return location !== null
        case 'confirm':
          return true
        default:
          return false
      }
    },
    [session, capturedImage, location]
  )

  const setSession = useCallback((newSession: SessionSummary) => {
    setSessionState(newSession)
  }, [])

  const goToStep = useCallback((target: CheckInStep) => {
    setStep(target)
  }, [])

  const nextStep = useCallback(() => {
    setStep((current) => {
      const index = STEP_ORDER.indexOf(current)
      const next = STEP_ORDER[Math.min(index + 1, STEP_ORDER.length - 1)]
      return next
    })
  }, [])

  const previousStep = useCallback(() => {
    setStep((current) => {
      const index = STEP_ORDER.indexOf(current)
      const prev = STEP_ORDER[Math.max(index - 1, 0)]
      return prev
    })
  }, [])

  const reset = useCallback(() => {
    setStep('session-select')
    setSessionState(null)
    setCapturedImage(null)
    setLocation(null)
    setResult(null)
  }, [])

  const value = useMemo<CheckInContextValue>(
    () => ({
      step,
      session,
      capturedImage,
      location,
      result,
      setSession,
      setCapturedImage,
      setLocation,
      setResult,
      goToStep,
      nextStep,
      previousStep,
      canProceedFrom,
      reset,
    }),
    [
      step,
      session,
      capturedImage,
      location,
      result,
      setSession,
      goToStep,
      nextStep,
      previousStep,
      canProceedFrom,
      reset,
    ]
  )

  return <CheckInContext.Provider value={value}>{children}</CheckInContext.Provider>
}
