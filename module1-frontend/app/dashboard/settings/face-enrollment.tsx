'use client'

/** Update Face Identity flow: password re-check, camera consent, a 5-second look at the camera, then one captured frame is sent for enrollment. */

import { useEffect, useRef, useState, type FormEvent } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/hooks/useAuth'
import { useCameraStream } from '@/lib/hooks/useCameraStream'
import { createFrameGrabber, PHOTO_JPEG } from '@/lib/utils/frame-capture'
import { abortableSleep } from '@/lib/liveness/capture-runner'
import { enrollFace } from '@/lib/services/face.service'
import { FACE_CAPTURE_MS, enrollErrorMessage } from '@/lib/face/enrollment'

type Step = 'password' | 'consent' | 'countdown' | 'uploading' | 'done' | 'error'

const SECONDS = Math.round(FACE_CAPTURE_MS / 1000)
const PRIMARY =
  'min-h-[44px] rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:opacity-60'
const SECONDARY =
  'min-h-[44px] rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100'

export function FaceEnrollmentFlow({ onClose }: { onClose: () => void }) {
  const { reauthenticate, saveConsent, refreshUser } = useAuth()
  const { videoRef, status, startStream, stopStream } = useCameraStream()
  const [step, setStep] = useState<Step>('password')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [secondsLeft, setSecondsLeft] = useState(SECONDS)
  const [refreshed, setRefreshed] = useState(true)
  const abortRef = useRef<AbortController | null>(null)

  const cameraStoppedRef = useRef(false)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    if (status !== 'error') return
    cameraStoppedRef.current = true
    abortRef.current?.abort()
  }, [status])

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
      setStep('consent')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Password check failed. Please try again.')
    } finally {
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
    setStep('uploading')
    try {
      await enrollFace(image)
    } catch (error) {
      fail(enrollErrorMessage(error))
      return
    }
    try {
      await refreshUser()
      setRefreshed(true)
    } catch {
      setRefreshed(false)
    }
    setStep('done')
  }

  function cancel() {
    abortRef.current?.abort()
    stopStream()
    onClose()
  }

  function retry() {
    setMessage(null)
    setStep('consent')
  }

  const showVideo = step === 'consent' || step === 'countdown'

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
