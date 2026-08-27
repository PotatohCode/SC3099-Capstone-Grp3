/**
 * Task 1.3: "Implement frame capture: video -> canvas -> base64 JPEG"
 * Component tree Section 2.1: "frame-capture.ts [Canvas to base64 JPEG - Task 1.3]"
 *
 * Privacy constraint (CLAUDE.md / IMPLEMENTATION_PLAN.html): never persist raw camera
 * frames anywhere. This function only returns an in-memory base64 string for immediate
 * submission; callers must not write it to localStorage/IndexedDB.
 */

const JPEG_QUALITY = 0.8

/**
 * Draws the current frame of a <video> element onto an offscreen canvas and returns
 * it as a base64-encoded JPEG string (without the `data:image/jpeg;base64,` prefix,
 * matching the shape expected by POST /checkins/ `liveness_challenge_response` and
 * POST /users/me/face/enroll `image`).
 */
export function captureFrameAsBase64Jpeg(video: HTMLVideoElement): string {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth || 640
  canvas.height = video.videoHeight || 480

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('Canvas 2D context unavailable')
  }
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY)
  return dataUrl.replace(/^data:image\/\w+;base64,/, '')
}

/** Rough size estimate in KB for a base64 string, used to warn if a frame is too large. */
export function estimateBase64SizeKb(base64: string): number {
  const bytes = (base64.length * 3) / 4
  return Math.round(bytes / 1024)
}
