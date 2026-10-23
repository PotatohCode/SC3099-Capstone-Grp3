/**
 * Task 1.3: "Implement frame capture: video -> canvas -> base64 JPEG"
 * Component tree Section 2.1: "frame-capture.ts [Canvas to base64 JPEG - Task 1.3]"
 *
 * Privacy constraint (Project Brief / IMPLEMENTATION_PLAN.html): never persist raw camera
 * frames anywhere. This function only returns an in-memory base64 string for immediate
 * submission; callers must not write it to localStorage/IndexedDB.
 */

export interface GrabOptions {
  maxWidth: number
  quality: number
}

export const BURST_JPEG: GrabOptions = { maxWidth: 640, quality: 0.7 }
export const PHOTO_JPEG: GrabOptions = { maxWidth: 640, quality: 0.8 }

/** Returns a function that draws the current video frame (never flipped) to one reused canvas and returns raw base64 JPEG, or null if the video is not ready. */
export function createFrameGrabber(video: HTMLVideoElement, opts: GrabOptions): () => string | null {
  const canvas = document.createElement('canvas')
  return () => {
    const sourceWidth = video.videoWidth
    const sourceHeight = video.videoHeight
    if (!sourceWidth || !sourceHeight) return null
    const scale = Math.min(1, opts.maxWidth / sourceWidth)
    const width = Math.round(sourceWidth * scale)
    const height = Math.round(sourceHeight * scale)
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0, width, height)
    const match = /^data:image\/\w+;base64,(.+)$/.exec(canvas.toDataURL('image/jpeg', opts.quality))
    return match ? match[1] : null
  }
}

/** Rough size estimate in KB for a base64 string, used to warn if a frame is too large. */
export function estimateBase64SizeKb(base64: string): number {
  const bytes = (base64.length * 3) / 4
  return Math.round(bytes / 1024)
}
