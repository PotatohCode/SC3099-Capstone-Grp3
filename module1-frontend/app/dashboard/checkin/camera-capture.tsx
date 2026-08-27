'use client'

/**
 * Tasks 1.3 & 1.4: WebRTC Camera Access, Frame Capture, and Liveness Challenge UI.
 * Component tree Section 2.1: "camera-capture.tsx [WebRTC + liveness UI]"
 *
 * Decision 5 (Section 9): "Liveness Implementation: UI prompt only; backend validates
 * image (bonus feature)." This component only shows the challenge prompt + countdown
 * and captures a single frame; all liveness scoring happens server-side.
 */

import { useEffect, useState } from 'react'
import { useCameraStream } from '@/lib/hooks/useCameraStream'
import { hasConsented, setConsent } from '@/lib/utils/consent-tracker'

const COUNTDOWN_SECONDS = 4

interface CameraCaptureProps {
  onCapture: (imageBase64: string) => void
}

export function CameraCapture({ onCapture }: CameraCaptureProps) {
  const { videoRef, status, error, isStreaming, startStream, captureFrame } = useCameraStream()
  const [hasConsentedToCamera, setHasConsentedToCamera] = useState(hasConsented('camera'))
  const [countdown, setCountdown] = useState<number | null>(null)

  function grantConsentAndStart() {
    setConsent('camera', true)
    setHasConsentedToCamera(true)
    startStream()
  }

  // Task 1.4: 3-5 second countdown, then auto-capture.
  useEffect(() => {
    if (!isStreaming) return
    setCountdown(COUNTDOWN_SECONDS)
  }, [isStreaming])

  useEffect(() => {
    if (countdown === null) return
    if (countdown <= 0) {
      const image = captureFrame()
      if (image) onCapture(image)
      return
    }
    const timer = setTimeout(() => setCountdown((c) => (c ?? 1) - 1), 1000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown])

  function handleManualCapture() {
    const image = captureFrame()
    if (image) onCapture(image)
  }

  if (!hasConsentedToCamera) {
    return (
      <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Camera access required</h2>
        <p className="text-sm text-gray-600">
          We need to use your camera for a quick liveness check to confirm you&apos;re
          physically present. Your photo is used only for this check-in and is never
          stored as an image - only a hash is kept.
        </p>
        <button
          type="button"
          onClick={grantConsentAndStart}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Allow camera access
        </button>
      </div>
    )
  }

  if (status === 'denied') {
    return (
      <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-5">
        <p className="text-sm text-red-700">{error}</p>
        <button
          type="button"
          onClick={startStream}
          className="min-h-[44px] rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="relative mx-auto w-full max-w-[640px] overflow-hidden rounded-lg bg-black">
        <video
          ref={videoRef}
          className="w-full aspect-[4/3] object-cover"
          playsInline
          muted
          aria-label="Live camera preview"
        />
        {status === 'requesting' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
            Requesting camera access...
          </div>
        )}
        {isStreaming && countdown !== null && (
          <div className="absolute inset-x-0 top-0 bg-black/60 p-3 text-center text-white">
            <p className="font-medium">Please look at the camera and stay still</p>
            <p className="text-3xl font-bold" aria-live="assertive">
              {countdown > 0 ? countdown : 'Capturing...'}
            </p>
          </div>
        )}
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {status === 'idle' && (
        <button
          type="button"
          onClick={startStream}
          className="min-h-[44px] w-full rounded-md bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 sm:w-auto"
        >
          Start camera
        </button>
      )}

      {isStreaming && (
        <button
          type="button"
          onClick={handleManualCapture}
          className="min-h-[44px] w-full rounded-md border border-blue-700 px-4 py-2 font-medium text-blue-700 hover:bg-blue-50 sm:w-auto"
        >
          Capture now
        </button>
      )}
    </div>
  )
}
