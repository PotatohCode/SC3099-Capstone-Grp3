import { runCapturePlan, type RunClock } from '@/lib/liveness/capture-runner'
import { planCapture } from '@/lib/liveness/challenge'

function fakeClock(): RunClock & { t: number; sleeps: number[] } {
  const clock = {
    t: 0,
    sleeps: [] as number[],
    now: () => clock.t,
    sleep: async (ms: number) => {
      clock.sleeps.push(ms)
      clock.t += ms
    },
  }
  return clock
}

describe('runCapturePlan', () => {
  it('grabs every planned frame at its offset, oldest first', async () => {
    const plan = planCapture(['blink', 'turn_left'], 30)!
    const clock = fakeClock()
    const grabTimes: number[] = []
    let n = 0
    const grab = () => {
      grabTimes.push(clock.t)
      return `f${n++}`
    }
    const steps: number[] = []
    const frames = await runCapturePlan(plan, grab, { onStep: (i) => steps.push(i) }, new AbortController().signal, clock)
    expect(frames).toEqual(Array.from({ length: 16 }, (_, i) => `f${i}`))
    expect(grabTimes).toEqual(plan.steps.flatMap((s) => s.frameOffsetsMs))
    expect(steps).toEqual([0, 1])
    expect(clock.t).toBe(plan.durationMs)
  })

  it('does not accumulate drift when grabs are slow', async () => {
    const plan = planCapture(['blink'], 30)!
    const clock = fakeClock()
    const grabTimes: number[] = []
    const grab = () => {
      grabTimes.push(clock.t)
      clock.t += 50
      return 'f'
    }
    await runCapturePlan(plan, grab, { onStep: () => undefined }, new AbortController().signal, clock)
    expect(grabTimes).toEqual(plan.steps[0].frameOffsetsMs)
  })

  it('skips frames the video could not provide', async () => {
    const plan = planCapture(['blink'], 30)!
    let n = 0
    const frames = await runCapturePlan(plan, () => (n++ % 2 === 0 ? `f${n}` : null), { onStep: () => undefined }, new AbortController().signal, fakeClock())
    expect(frames).toHaveLength(4)
  })

  it('fails with NO_FRAMES when a step yields no frames', async () => {
    const plan = planCapture(['blink'], 30)!
    await expect(
      runCapturePlan(plan, () => null, { onStep: () => undefined }, new AbortController().signal, fakeClock())
    ).rejects.toThrow('NO_FRAMES')
  })

  it('stops grabbing and rejects with AbortError when aborted', async () => {
    const plan = planCapture(['blink', 'turn_left'], 30)!
    const controller = new AbortController()
    let grabs = 0
    const grab = () => {
      grabs++
      if (grabs === 3) controller.abort()
      return 'f'
    }
    await expect(runCapturePlan(plan, grab, { onStep: () => undefined }, controller.signal, fakeClock())).rejects.toMatchObject({
      name: 'AbortError',
    })
    expect(grabs).toBe(3)
  })

  it('uses real timers by default', async () => {
    jest.useFakeTimers()
    const plan = planCapture(['blink'], 1)!
    const promise = runCapturePlan(plan, () => 'f', { onStep: () => undefined }, new AbortController().signal)
    await jest.advanceTimersByTimeAsync(plan.durationMs + 10)
    await expect(promise).resolves.toEqual(['f'])
    jest.useRealTimers()
  })

  it('rejects promptly when aborted during a long wait', async () => {
    jest.useFakeTimers()
    try {
      const plan = planCapture(['blink'], 30)!
      const controller = new AbortController()
      const promise = runCapturePlan(plan, () => 'f', { onStep: () => undefined }, controller.signal)
      const settled = jest.fn()
      promise.catch(settled)
      await jest.advanceTimersByTimeAsync(100)
      controller.abort()
      await jest.advanceTimersByTimeAsync(1)
      expect(settled).toHaveBeenCalled()
    } finally {
      jest.useRealTimers()
    }
  })
})
