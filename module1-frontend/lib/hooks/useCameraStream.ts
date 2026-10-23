'use client'

/**
 * Task 1.3: WebRTC Camera Access & Frame Capture
 * Component tree Section 2.1: "useCameraStream() [WebRTC setup/teardown - Task 1.3]"
 *
 * CONSTRAINT (Section 4): getUserMedia() requires HTTPS or localhost - this project
 * assumes localhost for development (Risk Analysis Section 7).
 *
 * - Requests { video: { width: 640, height: 480, facingMode: 'user' } }
 * - The caller stops the stream as soon as capture finishes (privacy: don't keep the
 *   camera live longer than necessary); unmount always stops it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type CameraStatus = 'idle' | 'requesting' | 'streaming' | 'denied' | 'error' | 'stopped'

export function useCameraStream() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const mountedRef = useRef(true)
  const pendingRef = useRef<Promise<CameraStatus> | null>(null)
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

  const openStream = useCallback(async (): Promise<CameraStatus> => {
    setError(null)
    setStatus('requesting')
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('error')
      setError('Camera access is not supported in this browser.')
      return 'error'
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      })
    } catch (err) {
      const domError = err as DOMException
      if (domError?.name === 'NotAllowedError' || domError?.name === 'PermissionDeniedError') {
        setStatus('denied')
        setError('Camera permission was denied. Please allow camera access to check in.')
        return 'denied'
      }
      setStatus('error')
      setError(domError?.message || 'Unable to access the camera. Please try again.')
      return 'error'
    }
    if (!mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop())
      return 'stopped'
    }
    streamRef.current = stream
    stream.getTracks().forEach((track) =>
      track.addEventListener?.('ended', () => {
        if (streamRef.current !== stream) return
        streamRef.current = null
        setStatus('error')
        setError('The camera stopped. Please try again.')
      })
    )
    try {
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
    } catch {
      stream.getTracks().forEach((track) => track.stop())
      streamRef.current = null
      setStatus('error')
      setError("Couldn't start the camera preview. Please try again.")
      return 'error'
    }
    setStatus('streaming')
    return 'streaming'
  }, [])

  const startStream = useCallback((): Promise<CameraStatus> => {
    if (streamRef.current) return Promise.resolve('streaming')
    if (!pendingRef.current) {
      pendingRef.current = openStream().finally(() => {
        pendingRef.current = null
      })
    }
    return pendingRef.current
  }, [openStream])

  useEffect(() => {
    const video = videoRef.current
    const stream = streamRef.current
    if (status === 'streaming' && video && stream && video.srcObject !== stream) {
      video.srcObject = stream
      video.play().catch(() => undefined)
    }
  })

  // Ensure the camera is always released on unmount.
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
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
  }
}
