/** Runs a liveness capture plan against a frame grabber on a drift-free schedule, with abort support. */
import type { CapturePlan, StepPlan } from '@/lib/liveness/challenge'

export interface RunCallbacks {
  onStep: (index: number, step: StepPlan) => void
  onCapture?: (index: number, step: StepPlan) => void
}

export interface RunClock {
  now: () => number
  sleep: (ms: number, signal: AbortSignal) => Promise<void>
}

function abortError(): DOMException {
  return new DOMException('Capture aborted', 'AbortError')
}

/** Waits for ms, rejecting with AbortError as soon as the signal aborts. */
export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      clearTimeout(timer)
      reject(abortError())
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

const defaultClock: RunClock = {
  now: () => performance.now(),
  sleep: abortableSleep,
}

/** Captures frames at the planned offsets and resolves them oldest first; rejects AbortError on abort or NO_FRAMES if a step got none. */
export async function runCapturePlan(
  plan: CapturePlan,
  grab: () => string | null,
  callbacks: RunCallbacks,
  signal: AbortSignal,
  clock: RunClock = defaultClock
): Promise<string[]> {
  const start = clock.now()
  const waitUntil = async (offsetMs: number) => {
    if (signal.aborted) throw abortError()
    const delay = offsetMs - (clock.now() - start)
    if (delay > 0) await clock.sleep(delay, signal)
    if (signal.aborted) throw abortError()
  }
  const frames: string[] = []
  for (let index = 0; index < plan.steps.length; index++) {
    const step = plan.steps[index]
    await waitUntil(step.startMs)
    callbacks.onStep(index, step)
    await waitUntil(step.captureStartMs)
    callbacks.onCapture?.(index, step)
    let taken = 0
    for (const offset of step.frameOffsetsMs) {
      await waitUntil(offset)
      const frame = grab()
      if (frame) {
        frames.push(frame)
        taken++
      }
    }
    if (taken === 0) throw new Error('NO_FRAMES')
  }
  await waitUntil(plan.durationMs)
  return frames
}
