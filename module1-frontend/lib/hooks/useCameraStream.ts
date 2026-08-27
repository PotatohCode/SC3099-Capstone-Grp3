'use client'

/**
 * Task 1.3: WebRTC Camera Access & Frame Capture
 * Component tree Section 2.1: "useCameraStream() [WebRTC setup/teardown - Task 1.3]"
 *
 * CONSTRAINT (Section 4): getUserMedia() requires HTTPS or localhost - this project
 * assumes localhost for development (Risk Analysis Section 7).
 *
 * - Requests { video: { width: 640, height: 480, facingMode: 'user' } }
 * - Calls track.stop() immediately after a frame is captured (privacy: don't keep the
 *   camera live longer than necessary).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { captureFrameAsBase64Jpeg } from '@/lib/utils/frame-capture'

export type CameraStatus = 'idle' | 'requesting' | 'streaming' | 'denied' | 'error' | 'stopped'

export function useCameraStream() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [status, setStatus] = useState<CameraStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setStatus((current) => (current === 'streaming' ? 'stopped' : current))
  }, [])

  const startStream = useCallback(async () => {
    setError(null)
    setStatus('requesting')
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Camera access is not supported in this browser.')
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setStatus('streaming')
    } catch (err) {
      const domError = err as DOMException
      if (domError?.name === 'NotAllowedError' || domError?.name === 'PermissionDeniedError') {
        setStatus('denied')
        setError('Camera permission was denied. Please allow camera access to check in.')
      } else {
        setStatus('error')
        setError(
          domError?.message || 'Unable to access the camera. Please try again.'
        )
      }
    }
  }, [])

  /** Captures the current frame, then immediately stops the stream (Task 1.3). */
  const captureFrame = useCallback((): string | null => {
    if (!videoRef.current || status !== 'streaming') return null
    try {
      const base64 = captureFrameAsBase64Jpeg(videoRef.current)
      stopStream()
      return base64
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to capture frame.')
      return null
    }
  }, [status, stopStream])

  // Ensure the camera is always released on unmount.
  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  return {
    videoRef,
    status,
    error,
    isStreaming: status === 'streaming',
    startStream,
    stopStream,
    captureFrame,
  }
}
