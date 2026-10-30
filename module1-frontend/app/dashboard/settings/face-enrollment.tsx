'use client'

/** Face identity flow: password re-check, an instructor reset code with a 5-minute window when replacing a face, camera consent, a 5-second look, then one frame is enrolled. */

import { useEffect, useRef, useState, type FormEvent } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/hooks/useAuth'
import { useCameraStream } from '@/lib/hooks/useCameraStream'
import { createFrameGrabber, PHOTO_JPEG } from '@/lib/utils/frame-capture'
import { abortableSleep } from '@/lib/liveness/capture-runner'
import { checkResetCode, enrollFace } from '@/lib/services/face.service'
import { parseApiError } from '@/lib/utils/api-error'
import {
  FACE_CAPTURE_MS,
  FACE_RESET_WINDOW_MS,
  RESET_WINDOW_EXPIRED_MESSAGE,
  enrollErrorMessage,
  formatTimeLeft,
  normalizeResetCode,
  resetCodeCheckErrorMessage,
} from '@/lib/face/enrollment'

type Step = 'password' | 'code' | 'consent' | 'countdown' | 'uploading' | 'done' | 'error'

const TIMED_STEPS: Step[] = ['consent', 'countdown', 'error']

const SECONDS = Math.round(FACE_CAPTURE_MS / 1000)
const PRIMARY =
  'min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60'
const SECONDARY =
  'min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100'

export function FaceEnrollmentFlow({ onClose }: { onClose: () => void }) {
  const { user, reauthenticate, saveConsent, refreshUser } = useAuth()
  const { videoRef, status, startStream, stopStream } = useCameraStream()
  const [step, setStep] = useState<Step>('password')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [secondsLeft, setSecondsLeft] = useState(SECONDS)
  const [refreshed, setRefreshed] = useState(true)
  const [needsCode, setNeedsCode] = useState(user?.face_enrolled === true)
  const [code, setCode] = useState('')
  const [deadline, setDeadline] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const abortRef = useRef<AbortController | null>(null)
  const deadlineRef = useRef<number | null>(null)
  const codeInputRef = useRef<HTMLInputElement | null>(null)
  const checkingRef = useRef(false)

  const cameraStoppedRef = useRef(false)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    if (status !== 'error') return
    cameraStoppedRef.current = true
    abortRef.current?.abort()
  }, [status])

  useEffect(() => {
    if (step === 'code') codeInputRef.current?.focus()
  }, [step])

  useEffect(() => {
    if (deadline === null || !TIMED_STEPS.includes(step)) return
    const timer = setInterval(() => {
      const current = Date.now()
      setNow(current)
      if (current >= deadline) expireRef.current()
    }, 1000)
    return () => clearInterval(timer)
  }, [deadline, step])

  useEffect(() => {
    function handleVisibility() {
      if (document.visibilityState !== 'hidden') return
      cameraStoppedRef.current = true
      abortRef.current?.abort()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [])

  async function submitPassword(event: FormEvent) {
    event.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setMessage(null)
    try {
      await reauthenticate(password)
      setPassword('')
      setStep(needsCode ? 'code' : 'consent')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Password check failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  function setWindow(end: number | null) {
    deadlineRef.current = end
    setDeadline(end)
    if (end !== null) setNow(Date.now())
  }

  function windowOpen(): boolean {
    if (!needsCode) return true
    return deadlineRef.current !== null && Date.now() < deadlineRef.current
  }

  function askForCode(text: string | null, keepCode = false) {
    abortRef.current?.abort()
    stopStream()
    setWindow(null)
    if (!keepCode) setCode('')
    setBusy(false)
    setMessage(text)
    setStep('code')
  }

  function expireWindow() {
    askForCode(RESET_WINDOW_EXPIRED_MESSAGE)
  }
  const expireRef = useRef(expireWindow)
  expireRef.current = expireWindow

  async function submitCode(event: FormEvent) {
    event.preventDefault()
    const normalized = normalizeResetCode(code)
    if (!normalized || checkingRef.current) return
    checkingRef.current = true
    setBusy(true)
    setMessage(null)
    try {
      const result = await checkResetCode(normalized).catch((error: unknown) => {
        if (parseApiError(error).status === 404) return { required: true, valid: true }
        throw error
      })
      if (!result.required) {
        setNeedsCode(false)
        setWindow(null)
      } else {
        setWindow(Date.now() + FACE_RESET_WINDOW_MS)
      }
      setStep('consent')
    } catch (error) {
      setMessage(resetCodeCheckErrorMessage(error))
      codeInputRef.current?.focus()
    } finally {
      checkingRef.current = false
      setBusy(false)
    }
  }

  function fail(text: string) {
    stopStream()
    setMessage(text)
    setStep('error')
  }

  async function allowCamera() {
    if (busy) return
    setBusy(true)
    setMessage(null)
    cameraStoppedRef.current = false
    const cameraStatus = await startStream()
    if (!windowOpen()) {
      stopStream()
      return
    }
    if (cameraStatus === 'denied') {
      await saveConsent('camera', false)
      setBusy(false)
      setMessage('Camera access was denied. Allow camera access for this site in your browser settings, then try again.')
      return
    }
    if (cameraStatus !== 'streaming') {
      stopStream()
      setBusy(false)
      setMessage("Couldn't start the camera. Please try again.")
      return
    }
    const saved = await saveConsent('camera', true)
    setBusy(false)
    if (!windowOpen()) {
      stopStream()
      return
    }
    if (!saved) {
      fail("Couldn't save your camera consent. Check your connection and try again.")
      return
    }
    await captureAndEnroll()
  }

  async function captureAndEnroll() {
    const video = videoRef.current
    if (!video) {
      fail("Couldn't start the camera. Please try again.")
      return
    }
    if (cameraStoppedRef.current) {
      cameraStoppedRef.current = false
      fail('The camera stopped before your photo was taken. Keep this page open and try again.')
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    setSecondsLeft(SECONDS)
    setStep('countdown')
    const ticker = setInterval(() => setSecondsLeft((s) => Math.max(1, s - 1)), 1000)
    try {
      await abortableSleep(FACE_CAPTURE_MS, controller.signal)
    } catch {
      clearInterval(ticker)
      abortRef.current = null
      if (cameraStoppedRef.current) {
        cameraStoppedRef.current = false
        fail('The camera stopped before your photo was taken. Keep this page open and try again.')
      } else {
        stopStream()
      }
      return
    } finally {
      clearInterval(ticker)
    }
    abortRef.current = null
    const image = createFrameGrabber(video, PHOTO_JPEG)()
    stopStream()
    if (!image) {
      fail("Couldn't capture a photo. Please try again.")
      return
    }
    if (!windowOpen()) return
    setStep('uploading')
    try {
      await enrollFace(image, needsCode ? normalizeResetCode(code) : undefined)
    } catch (error) {
      const errorCode = parseApiError(error).code
      if (errorCode === 'FACE_RESET_CODE_REQUIRED') setNeedsCode(true)
      if (errorCode === 'FACE_RESET_CODE_REQUIRED' || errorCode === 'FACE_RESET_CODE_INVALID') {
        askForCode(enrollErrorMessage(error), errorCode === 'FACE_RESET_CODE_INVALID')
        return
      }
      fail(enrollErrorMessage(error))
      return
    }
    setWindow(null)
    try {
      await refreshUser()
      setRefreshed(true)
    } catch {
      setRefreshed(false)
    }
    setStep('done')
  }

  function cancel() {
    setWindow(null)
    abortRef.current?.abort()
    stopStream()
    onClose()
  }

  function retry() {
    setMessage(null)
    setStep('consent')
  }

  const showVideo = step === 'consent' || step === 'countdown'
  const showTimer = needsCode && deadline !== null && TIMED_STEPS.includes(step)

  return (
    <div className="mt-4 space-y-4">
      {step === 'password' && (
        <form onSubmit={submitPassword} className="space-y-3" noValidate>
          <p className="text-sm text-gray-600">Enter your password to continue.</p>
          <div>
            <label htmlFor="face-reauth-password" className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="face-reauth-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || !password} className={PRIMARY}>
              {busy ? 'Checking...' : 'Continue'}
            </button>
            <button type="button" onClick={cancel} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {step === 'code' && (
        <form onSubmit={submitCode} className="space-y-3" noValidate>
          <p className="text-sm text-gray-600">
            Replacing your face needs a one-time reset code. Ask an instructor of one of your courses: they&apos;ll
            check your student card, then give you the code. After you enter it, you have 5 minutes to take your
            new photo.
          </p>
          <div>
            <label htmlFor="face-reset-code" className="block text-sm font-medium text-gray-700">
              Reset code from your instructor
            </label>
            <input
              id="face-reset-code"
              ref={codeInputRef}
              type="text"
              inputMode="text"
              autoComplete="off"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              maxLength={32}
              placeholder="XXXX-XXXX"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              readOnly={busy}
              className="mt-1 block min-h-[44px] w-full rounded-md border border-gray-300 px-3 py-2 font-mono uppercase tracking-widest text-gray-900 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-600"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || !normalizeResetCode(code)} className={PRIMARY}>
              {busy ? 'Checking...' : 'Continue'}
            </button>
            <button type="button" onClick={cancel} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {showTimer && deadline !== null && (
        <p role="timer" className="text-sm font-medium text-amber-800" data-testid="face-reset-timer">
          Time left to finish: {formatTimeLeft(deadline - now)}
        </p>
      )}

      {step === 'consent' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            We&apos;ll turn on your camera for {SECONDS} seconds and take one photo. Only a hash of your face
            is kept; the photo itself is never stored.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={allowCamera} disabled={busy} className={PRIMARY}>
              {busy ? 'Starting camera...' : 'Allow camera access'}
            </button>
            <button type="button" onClick={cancel} className={SECONDARY}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div
        className={`relative mx-auto w-full max-w-[480px] overflow-hidden rounded-lg bg-black ${showVideo && status === 'streaming' ? '' : 'hidden'}`}
      >
        <video
          ref={videoRef}
          className="aspect-[4/3] w-full -scale-x-100 object-cover"
          playsInline
          muted
          aria-label="Live camera preview"
        />
        {step === 'countdown' && (
          <div className="absolute inset-x-0 top-0 bg-black/60 p-3 text-center text-white" aria-live="polite">
            <p className="font-medium">Look at the camera</p>
            <p className="text-3xl font-bold" data-testid="face-countdown">
              {secondsLeft}
            </p>
          </div>
        )}
      </div>

      {step === 'countdown' && (
        <button type="button" onClick={cancel} className={SECONDARY}>
          Cancel
        </button>
      )}

      {step === 'uploading' && (
        <p className="text-sm text-gray-600" aria-live="polite">
          Registering your face...
        </p>
      )}

      {step === 'done' && (
        <div className="space-y-3 rounded-md bg-green-50 p-4" role="status">
          <p className="text-sm font-medium text-green-800">
            {refreshed
              ? 'Your face identity is registered. You can now check in.'
              : 'Your face identity is registered. Reload the page to turn check-in back on.'}
          </p>
          <div className="flex flex-wrap gap-2">
            {refreshed && (
              <Link href="/dashboard/checkin" className={`${PRIMARY} inline-flex items-center`}>
                Go to Check In
              </Link>
            )}
            <button type="button" onClick={onClose} className={SECONDARY}>
              Done
            </button>
          </div>
        </div>
      )}

      {step === 'error' && (
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={retry} className={PRIMARY}>
            Try again
          </button>
          <button type="button" onClick={cancel} className={SECONDARY}>
            Cancel
          </button>
        </div>
      )}

      {message && (
        <div
          role={step === 'done' ? 'status' : 'alert'}
          className={`rounded-md p-3 text-sm ${step === 'done' ? 'bg-amber-50 text-amber-800' : 'bg-red-50 text-red-700'}`}
        >
          {message}
        </div>
      )}
    </div>
  )
}
