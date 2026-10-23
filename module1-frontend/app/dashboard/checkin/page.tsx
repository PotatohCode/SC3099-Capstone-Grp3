'use client'

/**
 * Task 1.2: Check-In Workflow Pipeline - wizard controller.
 * Component tree Section 2.1: "app/dashboard/checkin/page.tsx [Check-in wizard controller]"
 *
 * 4 steps: session-select -> location -> camera -> confirm (state machine lives in
 * lib/checkin/wizard-state.ts via CheckInContext).
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useCheckIn } from '@/lib/hooks/useCheckIn'
import type { CheckInStep } from '@/lib/context/CheckInContext'
import { useOfflineSync } from '@/lib/hooks/useOfflineSync'
import { getMySessions } from '@/lib/services/session.service'
import { submitCheckIn } from '@/lib/services/checkin.service'
import { getOrCreateDeviceFingerprint } from '@/lib/utils/device-fingerprint'
import { extractErrorMessage } from '@/lib/utils/http-client'
import { submitAttempt } from '@/lib/checkin/submit'
import type { CheckInErrorAction, CheckInErrorView } from '@/lib/checkin/errors'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { StatusBadge, RiskBadge } from '@/components/StatusBadge'
import { CameraCapture } from './camera-capture'
import { GeolocationStep } from './geolocation'
import type { SessionSummary } from '@/lib/types'

const STEPS: { key: CheckInStep; label: string }[] = [
  { key: 'session-select', label: 'Session' },
  { key: 'location', label: 'Location' },
  { key: 'camera', label: 'Face check' },
  { key: 'confirm', label: 'Confirm' },
]

function StepIndicator({ current }: { current: CheckInStep }) {
  const currentIndex = STEPS.findIndex((s) => s.key === current)
  return (
    <div className="mb-6">
      {/* Labels + arrows only from sm: up - 4 full labels don't fit a 375px
          viewport in one line (mobile responsiveness: no horizontal scrolling). */}
      <ol className="flex items-center text-xs sm:text-sm">
        {STEPS.map((s, index) => (
          <li key={s.key} className="flex items-center">
            <span className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full font-semibold sm:h-8 sm:min-w-[32px] sm:w-auto sm:px-2 ${
                  index <= currentIndex ? 'bg-blue-700 text-white' : 'bg-gray-200 text-gray-500'
                }`}
              >
                {index + 1}
              </span>
              {/* Labels hidden below sm: - see the mobile caption after this list. */}
              <span
                className={`hidden truncate sm:inline ${
                  index <= currentIndex ? 'text-gray-900' : 'text-gray-400'
                }`}
              >
                {s.label}
              </span>
            </span>
            {index < STEPS.length - 1 && (
              <span
                aria-hidden="true"
                className={`mx-1.5 h-px w-4 shrink-0 sm:mx-2 sm:w-6 ${
                  index < currentIndex ? 'bg-blue-700' : 'bg-gray-300'
                }`}
              />
            )}
          </li>
        ))}
      </ol>
      {/* Mobile-only caption since labels are hidden on the circles above. */}
      <p className="mt-2 text-sm font-medium text-gray-700 sm:hidden">
        Step {currentIndex + 1} of {STEPS.length}: {STEPS[currentIndex].label}
      </p>
    </div>
  )
}

function SessionSelectStep() {
  const { selectSession } = useCheckIn()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setIsLoading(true)
      setError(null)
      try {
        const data = await getMySessions({ status: 'active' })
        if (!cancelled) setSessions(data)
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err, 'Failed to load sessions.'))
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  if (isLoading) return <LoadingSpinner label="Loading your sessions..." />

  if (error) {
    return <p className="text-sm text-red-600" role="alert">{error}</p>
  }

  if (sessions.length === 0) {
    return (
      <p className="text-sm text-gray-600">
        No active check-in sessions right now. Check back once your instructor opens one.
      </p>
    )
  }

  return (
    <ul className="space-y-3">
      {sessions.map((session) => (
        <li key={session.id}>
          <button
            type="button"
            onClick={() => selectSession(session)}
            className="min-h-[44px] w-full rounded-lg border border-gray-200 bg-white p-4 text-left hover:border-blue-400 hover:bg-blue-50"
          >
            <p className="font-semibold text-gray-900">{session.name}</p>
            <p className="text-sm text-gray-500">
              {session.course_code ?? session.course_name} &middot; {session.venue_name ?? 'Venue TBD'}
            </p>
          </button>
        </li>
      ))}
    </ul>
  )
}

const ACTION_LABELS: Record<Exclude<CheckInErrorAction, 'queue-offline' | 'view-history'>, string> = {
  'retry-capture': 'Redo face check',
  'retry-location': 'Update my location',
  'reselect-session': 'Choose another session',
}

/** Error panel with the recovery buttons for a failed check-in. */
function CheckInErrorPanel({ view, onAction }: { view: CheckInErrorView; onAction: (action: CheckInErrorAction) => void }) {
  const actions = [view.action, view.alternateAction].filter((a): a is CheckInErrorAction => !!a)
  return (
    <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-5" role="alert">
      {view.title && <h2 className="text-lg font-semibold text-red-800">{view.title}</h2>}
      <p className="text-sm text-red-700">{view.message}</p>
      {view.secondary && <p className="text-sm text-red-700">{view.secondary}</p>}
      <div className="flex flex-wrap gap-3">
        {actions.map((action, index) =>
          action === 'view-history' ? (
            <Link
              key={action}
              href="/dashboard/history"
              className="flex min-h-[44px] items-center rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800"
            >
              Go to history
            </Link>
          ) : action === 'queue-offline' ? null : (
            <button
              key={action}
              type="button"
              onClick={() => onAction(action)}
              className={
                index === 0
                  ? 'min-h-[44px] rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800'
                  : 'min-h-[44px] rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100'
              }
            >
              {ACTION_LABELS[action]}
            </button>
          )
        )}
      </div>
    </div>
  )
}

function ConfirmStep() {
  const { session, media, location, result, previousStep, goToStep, retakeLocation, reset, submitSucceeded, submitQueued, submitFailed } =
    useCheckIn()
  const { isOnline, queueCheckIn } = useOfflineSync()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorView, setErrorView] = useState<CheckInErrorView | null>(null)
  const [queuedOffline, setQueuedOffline] = useState(false)

  async function handleSubmit() {
    if (!session || !media || !location) return
    setIsSubmitting(true)
    setErrorView(null)
    setQueuedOffline(false)
    const outcome = await submitAttempt({
      sessionId: session.id,
      location,
      media,
      fingerprint: getOrCreateDeviceFingerprint(),
      isOnline,
      browserOnline: () => navigator.onLine,
      now: () => performance.now(),
      submit: submitCheckIn,
      queue: queueCheckIn,
    })
    if (outcome.kind === 'success') {
      submitSucceeded(outcome.result)
    } else if (outcome.kind === 'queued') {
      submitQueued()
      setQueuedOffline(true)
    } else {
      submitFailed(!!outcome.view.challengeInvalid)
      setErrorView(outcome.view)
    }
    setIsSubmitting(false)
  }

  function handleErrorAction(action: CheckInErrorAction) {
    setErrorView(null)
    if (action === 'retry-capture') goToStep('camera')
    else if (action === 'retry-location') retakeLocation()
    else if (action === 'reselect-session') reset()
  }

  if (result) {
    return (
      <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Check-in submitted</h2>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={result.status} />
          <RiskBadge riskLevel={result.risk_level} riskScore={result.risk_score} />
        </div>
        {typeof result.distance_from_venue_meters === 'number' && (
          <p className="text-sm text-gray-600">
            Distance from venue: {Math.round(result.distance_from_venue_meters)}m
          </p>
        )}
        <button
          type="button"
          onClick={reset}
          className="min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
        >
          Check in to another session
        </button>
      </div>
    )
  }

  if (queuedOffline) {
    return (
      <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-5">
        <h2 className="text-lg font-semibold text-amber-800">Saved for sync</h2>
        <p className="text-sm text-amber-700">
          You&apos;re offline. Your check-in has been saved and will be submitted
          automatically once you&apos;re back online. Keep this tab open.
        </p>
        <button
          type="button"
          onClick={reset}
          className="min-h-[44px] rounded-md border border-amber-400 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100"
        >
          Done
        </button>
      </div>
    )
  }

  if (errorView) {
    return <CheckInErrorPanel view={errorView} onAction={handleErrorAction} />
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Review &amp; submit</h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-500">Session</dt>
            <dd className="font-medium text-gray-900">{session?.name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Face check</dt>
            <dd className="font-medium text-gray-900">
              {!media
                ? 'Missing'
                : media.kind === 'burst'
                  ? media.verification === 'passed'
                    ? `Movements confirmed (${media.sequence.length} actions)`
                    : `Completed (${media.sequence.length} actions)`
                  : media.kind === 'photo' && media.verification !== 'review'
                    ? 'Photo taken'
                    : 'Not completed'}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Location</dt>
            <dd className="font-medium text-gray-900">
              {location ? `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}` : 'Missing'}
            </dd>
          </div>
        </dl>
        {media?.verification === 'review' && (
          <p className="mt-3 text-xs text-amber-700" role="status">
            Your liveliness check was unsuccessful, please approach your instructor to mark your attendance.
          </p>
        )}
        {!isOnline && (
          <p className="mt-3 text-xs text-amber-700">
            You&apos;re currently offline - this check-in will be queued and synced automatically.
          </p>
        )}
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={previousStep}
          disabled={isSubmitting}
          className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-60"
        >
          Back
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || !session || !media || !location}
          className="min-h-[44px] flex-1 rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60"
        >
          {isSubmitting ? 'Submitting...' : 'Submit check-in'}
        </button>
      </div>
    </div>
  )
}

export default function CheckInWizardPage() {
  const { step, photoMode, session, location, setMedia, setLocation, continueFromLocation, previousStep, reset } = useCheckIn()

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Check In</h1>
      <StepIndicator current={step} />

      {step === 'session-select' && <SessionSelectStep />}

      {step === 'location' && (
        <div className="space-y-4">
          <GeolocationStep knownLocation={location} onLocationConfirmed={setLocation} onContinue={continueFromLocation} />
          <button
            type="button"
            onClick={previousStep}
            className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Back
          </button>
        </div>
      )}

      {step === 'camera' && session && (
        <div className="space-y-4">
          <CameraCapture sessionId={session.id} photoMode={photoMode} onComplete={setMedia} onReselectSession={reset} />
          <button
            type="button"
            onClick={previousStep}
            className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Back
          </button>
        </div>
      )}

      {step === 'confirm' && <ConfirmStep />}
    </div>
  )
}
