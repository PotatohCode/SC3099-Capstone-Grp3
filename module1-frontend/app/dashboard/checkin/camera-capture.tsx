'use client'

/**
 * Tasks 1.3 & 1.4: WebRTC Camera Access, Frame Capture, and Liveness Challenge UI.
 * Component tree Section 2.1: "camera-capture.tsx [WebRTC + liveness UI]"
 *
 * Fetches a server-issued challenge (POST /checkins/challenge) when the student taps
 * Start, prompts each step and captures a frame burst; falls back to a single photo
 * when challenges are unavailable. All liveness scoring happens server-side.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/lib/hooks/useAuth'
import { useCameraStream, type CameraStatus } from '@/lib/hooks/useCameraStream'
import { requestChallenge, verifyChallenge } from '@/lib/services/checkin.service'
import { classifyChallengeError, type CheckInErrorView } from '@/lib/checkin/errors'
import { middleFrame, type CapturedMedia } from '@/lib/checkin/payload'

type BurstMedia = Extract<CapturedMedia, { kind: 'burst' }>
import { CAPTURE, planCapture } from '@/lib/liveness/challenge'
import { MAX_ATTEMPTS, REVIEW_MESSAGE, attemptsUsed, decideAttempt, startAttempt, undoAttempt, type AttemptDecision, type AttemptOutcome } from '@/lib/liveness/verify'
import { abortableSleep, runCapturePlan } from '@/lib/liveness/capture-runner'
import { decideConsentGate, queryPermission, type ConsentGate } from '@/lib/utils/consent-tracker'
import { BURST_JPEG, createFrameGrabber, PHOTO_JPEG } from '@/lib/utils/frame-capture'
import { FLAGGED_WARNING } from '@/components/FlaggedNotice'

type Phase = 'ready' | 'preparing' | 'countdown' | 'step' | 'verifying' | 'photo-countdown' | 'done'

interface CameraCaptureProps {
  sessionId: string
  photoMode: boolean
  onComplete: (media: CapturedMedia) => void
  onReselectSession: () => void
}

/** Skip button with a confirm prompt, for students who can't or won't do the face check. */
function SkipFaceCheck({ onSkip }: { onSkip: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const keepRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    if (confirming) keepRef.current?.focus()
  }, [confirming])
  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="min-h-[44px] w-full rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 sm:w-auto"
      >
        Skip face check
      </button>
    )
  }
  return (
    <div className="space-y-3 rounded-md border border-amber-300 bg-amber-50 p-4" role="alertdialog" aria-labelledby="skip-face-check-title">
      <p id="skip-face-check-title" className="text-sm font-semibold text-amber-900">
        Skip the face check?
      </p>
      <p className="text-sm text-amber-800">Your check-in may be flagged. {FLAGGED_WARNING}</p>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onSkip}
          className="min-h-[44px] rounded-md bg-amber-700 px-4 py-2 text-sm font-medium text-white hover:bg-amber-800"
        >
          Skip and continue
        </button>
        <button
          ref={keepRef}
          type="button"
          onClick={() => setConfirming(false)}
          className="min-h-[44px] rounded-md border border-amber-400 px-4 py-2 text-sm font-medium text-amber-900 hover:bg-amber-100"
        >
          Don&apos;t skip
        </button>
      </div>
    </div>
  )
}

const INTERRUPTED = "The face check was interrupted. Let's try again."
const NO_FRAMES = "We couldn't get images from your camera. Please try again."

export function CameraCapture({ sessionId, photoMode, onComplete, onReselectSession }: CameraCaptureProps) {
  const { user, saveConsent } = useAuth()
  const { videoRef, status, error, isStreaming, startStream, stopStream } = useCameraStream()
  const [gate, setGate] = useState<ConsentGate | null>(null)
  const [phase, setPhase] = useState<Phase>('ready')
  const [stepIndex, setStepIndex] = useState(0)
  const [steps, setSteps] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [message, setMessage] = useState<CheckInErrorView | null>(null)
  const [attemptNumber, setAttemptNumber] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const statusRef = useRef(status)
  statusRef.current = status

  const begin = useCallback(async (): Promise<CameraStatus> => {
    const result = await startStream()
    if (result === 'streaming') await saveConsent('camera', true)
    if (result === 'denied') {
      await saveConsent('camera', false)
      setGate('blocked')
    }
    return result
  }, [saveConsent, startStream])

  const initialConsent = useRef(user?.camera_consent)
  const [exhausted] = useState(() => attemptsUsed(user?.id ?? 'anonymous', sessionId) >= MAX_ATTEMPTS)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    if (exhausted) return
    queryPermission('camera').then((permission) => {
      if (!cancelled) setGate(decideConsentGate(initialConsent.current, permission))
    })
    return () => {
      cancelled = true
      abortRef.current?.abort()
    }
  }, [exhausted])

  const beginRef = useRef(begin)
  beginRef.current = begin

  useEffect(() => {
    if (gate === 'proceed') beginRef.current()
  }, [gate])

  useEffect(() => {
    if (phase !== 'countdown' && phase !== 'photo-countdown') return
    const timer = setInterval(() => setCountdown((c) => Math.max(1, c - 1)), 1000)
    return () => clearInterval(timer)
  }, [phase])

  useEffect(() => {
    if (status === 'error' && abortRef.current) abortRef.current.abort()
  }, [status])

  useEffect(() => {
    function handleVisibility() {
      if (document.visibilityState === 'hidden' && abortRef.current) abortRef.current.abort()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [])

  function allowCamera() {
    setGate('proceed')
  }

  async function retryBlocked() {
    if ((await begin()) === 'streaming') setGate('proceed')
  }

  function failCapture(text: string) {
    abortRef.current = null
    setPhase('ready')
    setMessage({ message: text, action: 'retry-capture' })
  }

  async function countdownFrom(seconds: number, signal: AbortSignal) {
    setCountdown(seconds)
    await abortableSleep(seconds * 1000, signal)
  }

  async function takePhoto(controller: AbortController) {
    const video = videoRef.current
    if (!video) return failCapture(NO_FRAMES)
    setPhase('photo-countdown')
    await countdownFrom(Math.round(CAPTURE.countdownMs / 1000), controller.signal)
    const photo = createFrameGrabber(video, PHOTO_JPEG)()
    if (!mountedRef.current) return
    if (!photo) return failCapture(NO_FRAMES)
    stopStream()
    abortRef.current = null
    setPhase('done')
    onComplete({ kind: 'photo', photo })
  }

  function finishAttempt(decision: AttemptDecision, burst: BurstMedia | null) {
    if (!mountedRef.current) return
    abortRef.current = null
    if (decision.kind === 'retry') {
      setPhase('ready')
      setMessage({ message: decision.message, secondary: decision.secondary, action: 'retry-capture' })
      if (statusRef.current !== 'streaming') void begin()
      return
    }
    stopStream()
    setPhase('done')
    if (decision.media === 'burst' && burst) {
      onComplete({
        ...burst,
        fetchedAtMs: decision.restartFreshness ? performance.now() : burst.fetchedAtMs,
        verification: decision.verification,
      })
    } else if (decision.media === 'frame' && burst) {
      onComplete({ kind: 'photo', photo: middleFrame(burst.frames), verification: 'review' })
    } else {
      onComplete({ kind: 'none', verification: 'review' })
    }
  }

  async function start() {
    const video = videoRef.current
    if (!video) return
    setMessage(null)
    const controller = new AbortController()
    abortRef.current = controller
    if (photoMode) {
      try {
        return await takePhoto(controller)
      } catch (err) {
        const aborted = err instanceof DOMException && err.name === 'AbortError'
        return failCapture(aborted ? INTERRUPTED : NO_FRAMES)
      }
    }
    const userId = user?.id ?? 'anonymous'
    if (attemptsUsed(userId, sessionId) >= MAX_ATTEMPTS) {
      return finishAttempt({ kind: 'submit', media: 'none', verification: 'review', restartFreshness: false }, null)
    }
    const attempt = startAttempt(userId, sessionId)
    setAttemptNumber(attempt)
    try {
      setPhase('preparing')
      let challenge
      try {
        challenge = await requestChallenge(sessionId)
      } catch (err) {
        if (!mountedRef.current) return
        const classified = classifyChallengeError(err)
        if (classified.fallbackToPhoto && classified.attemptsExhausted) {
          return finishAttempt({ kind: 'submit', media: 'none', verification: 'review', restartFreshness: false }, null)
        }
        if (classified.fallbackToPhoto) {
          undoAttempt(userId, sessionId)
          return await takePhoto(controller)
        }
        if (classified.view.action === 'reselect-session') {
          undoAttempt(userId, sessionId)
          abortRef.current = null
          setPhase('ready')
          setMessage(classified.view)
          return
        }
        return finishAttempt(decideAttempt({ kind: 'no-capture' }, attempt), null)
      }
      if (!mountedRef.current) return
      const fetchedAtMs = performance.now()
      const plan = planCapture(challenge.sequence, challenge.max_frames)
      if (!plan) {
        undoAttempt(userId, sessionId)
        return await takePhoto(controller)
      }
      setSteps(challenge.sequence)
      const frames = await runCapturePlan(
        plan,
        createFrameGrabber(video, BURST_JPEG),
        {
          onStep: (index, step) => {
            setStepIndex(index)
            setPrompt(step.prompt)
            setCountdown(Math.round(CAPTURE.countdownMs / 1000))
            setPhase('countdown')
          },
          onCapture: () => setPhase('step'),
        },
        controller.signal
      )
      const burst: BurstMedia = {
        kind: 'burst',
        challengeId: challenge.challenge_id,
        sequence: challenge.sequence,
        frames,
        fetchedAtMs,
        maxFrames: challenge.max_frames,
      }
      if (!mountedRef.current) return
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        stopStream()
        abortRef.current = null
        setPhase('done')
        onComplete(burst)
        return
      }
      abortRef.current = null
      setPhase('verifying')
      let outcome: AttemptOutcome
      try {
        outcome = { kind: 'verified', response: await verifyChallenge(challenge.challenge_id, frames) }
      } catch (error) {
        outcome = { kind: 'verify-error', error }
      }
      finishAttempt(decideAttempt(outcome, attempt), burst)
    } catch {
      finishAttempt(decideAttempt({ kind: 'no-capture' }, attempt), null)
    }
  }

  function cancel() {
    abortRef.current?.abort()
  }

  function skip() {
    abortRef.current?.abort()
    abortRef.current = null
    stopStream()
    setPhase('done')
    onComplete({ kind: 'none', verification: 'review', skipped: true })
  }

  if (exhausted) {
    return (
      <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-5" role="alert">
        <h2 className="text-lg font-semibold text-amber-900">No face-check tries left</h2>
        <p className="text-sm text-amber-800">
          You&apos;ve used all {MAX_ATTEMPTS} face-check tries for this session. {REVIEW_MESSAGE}
        </p>
        <button
          type="button"
          onClick={() => onComplete({ kind: 'none', verification: 'review' })}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Continue
        </button>
      </div>
    )
  }

  if (gate === null) {
    return <p className="text-sm text-gray-600">Checking camera access...</p>
  }

  if (gate === 'ask') {
    return (
      <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Camera access for the face check</h2>
        <p className="text-sm text-gray-600">
          We need to use your camera for a quick liveness check to confirm you&apos;re
          physically present. Your photo is used only for this check-in and is never
          stored as an image - only a hash is kept.
        </p>
        <button
          type="button"
          onClick={allowCamera}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Allow camera access
        </button>
        <SkipFaceCheck onSkip={skip} />
      </div>
    )
  }

  if (gate === 'blocked' || status === 'denied') {
    return (
      <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-5">
        <p className="text-sm text-red-700">
          Camera access is blocked for this site. Turn it on in your browser&apos;s site settings, then tap Try again.
        </p>
        <button
          type="button"
          onClick={retryBlocked}
          className="min-h-[44px] rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
        >
          Try again
        </button>
        <SkipFaceCheck onSkip={skip} />
      </div>
    )
  }

  const triesUsed = attemptsUsed(user?.id ?? 'anonymous', sessionId)
  const capturing =
    phase === 'preparing' || phase === 'countdown' || phase === 'step' || phase === 'verifying' || phase === 'photo-countdown'

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Face check</h2>
      <div className="relative mx-auto w-full max-w-[640px] overflow-hidden rounded-lg bg-black">
        <video
          ref={videoRef}
          className="aspect-[4/3] w-full -scale-x-100 object-cover"
          playsInline
          muted
          aria-label="Live camera preview"
        />
        {status === 'requesting' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
            Starting camera...
          </div>
        )}
        {capturing && (
          <div className="absolute inset-x-0 top-0 bg-black/60 p-3 text-center text-white">
            {phase === 'preparing' && (
              <p className="font-medium" aria-live="polite">
                Getting your check ready...
              </p>
            )}
            {(phase === 'countdown' || phase === 'step') && (
              <div>
                <p className="text-sm">
                  Step {stepIndex + 1} of {steps.length}
                </p>
                {stepIndex === 0 && attemptNumber === MAX_ATTEMPTS && (
                  <p className="text-sm font-medium">This is your last try.</p>
                )}
                <p className="text-lg font-bold sm:text-2xl" aria-live="assertive">
                  {prompt}
                </p>
                {phase === 'countdown' ? (
                  <p className="text-3xl font-bold" aria-label={`Starting in ${countdown}`}>
                    {countdown}
                  </p>
                ) : (
                  <p className="text-3xl font-bold text-green-300">Go!</p>
                )}
              </div>
            )}
            {phase === 'verifying' && (
              <p className="font-medium" aria-live="polite">
                Checking your movements...
              </p>
            )}
            {phase === 'photo-countdown' && (
              <div aria-live="polite">
                <p className="font-medium">Look at the camera and hold still</p>
                <p className="text-3xl font-bold">{countdown}</p>
              </div>
            )}
          </div>
        )}
        {phase === 'done' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
            Face check complete
          </div>
        )}
      </div>

      {error && status === 'error' && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {message && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
          {message.title && <p className="font-semibold">{message.title}</p>}
          {message.message}
          {message.secondary && <p className="mt-1 font-medium">{message.secondary}</p>}
          {message.action === 'reselect-session' && (
            <button type="button" onClick={onReselectSession} className="ml-2 font-medium underline">
              Choose another session
            </button>
          )}
        </div>
      )}

      {phase === 'ready' && isStreaming && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            {photoMode
              ? "When you're ready, tap Take photo and look at the camera."
              : "When you're ready, tap Start. You'll be asked to do a few quick actions while we take some photos."}
          </p>
          {!photoMode && triesUsed > 0 && triesUsed < MAX_ATTEMPTS && (
            <p className="text-sm font-medium text-gray-800">
              You have {MAX_ATTEMPTS - triesUsed} {MAX_ATTEMPTS - triesUsed === 1 ? 'try' : 'tries'} left.
            </p>
          )}
          <button
            type="button"
            onClick={start}
            className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
          >
            {photoMode ? 'Take photo' : 'Start'}
          </button>
        </div>
      )}

      {(status === 'idle' || status === 'stopped' || status === 'error') && phase === 'ready' && (
        <button
          type="button"
          onClick={() => begin()}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Start camera
        </button>
      )}

      {phase === 'ready' && <SkipFaceCheck onSkip={skip} />}

      {capturing && phase !== 'verifying' && (
        <button
          type="button"
          onClick={cancel}
          className="min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
        >
          Cancel
        </button>
      )}
    </div>
  )
}
