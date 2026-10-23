import { act, renderHook } from '@testing-library/react'
import { useCameraStream } from '@/lib/hooks/useCameraStream'

function fakeStream() {
  const track = { stop: jest.fn() }
  return { stream: { getTracks: () => [track] } as unknown as MediaStream, track }
}

function setGetUserMedia(impl: () => Promise<MediaStream>) {
  const getUserMedia = jest.fn(impl)
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  return getUserMedia
}

describe('useCameraStream', () => {
  it('requests the front camera at 640x480 without audio', async () => {
    const { stream } = fakeStream()
    const getUserMedia = setGetUserMedia(async () => stream)
    const { result } = renderHook(() => useCameraStream())
    let status
    await act(async () => {
      status = await result.current.startStream()
    })
    expect(status).toBe('streaming')
    expect(getUserMedia).toHaveBeenCalledWith({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
      audio: false,
    })
    expect(result.current.isStreaming).toBe(true)
  })

  it('stops every track on stopStream', async () => {
    const { stream, track } = fakeStream()
    setGetUserMedia(async () => stream)
    const { result } = renderHook(() => useCameraStream())
    await act(async () => {
      await result.current.startStream()
    })
    act(() => result.current.stopStream())
    expect(track.stop).toHaveBeenCalled()
    expect(result.current.status).toBe('stopped')
  })

  it('stops the camera on unmount', async () => {
    const { stream, track } = fakeStream()
    setGetUserMedia(async () => stream)
    const { result, unmount } = renderHook(() => useCameraStream())
    await act(async () => {
      await result.current.startStream()
    })
    unmount()
    expect(track.stop).toHaveBeenCalled()
  })

  it('reports a denied permission', async () => {
    setGetUserMedia(async () => Promise.reject(new DOMException('', 'NotAllowedError')))
    const { result } = renderHook(() => useCameraStream())
    let status
    await act(async () => {
      status = await result.current.startStream()
    })
    expect(status).toBe('denied')
    expect(result.current.error).toBe('Camera permission was denied. Please allow camera access to check in.')
  })

  it('reports an unsupported browser', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined })
    const { result } = renderHook(() => useCameraStream())
    let status
    await act(async () => {
      status = await result.current.startStream()
    })
    expect(status).toBe('error')
    expect(result.current.error).toBe('Camera access is not supported in this browser.')
  })

  it('stops a stream that arrives after unmount', async () => {
    const { stream, track } = fakeStream()
    let resolve: (s: MediaStream) => void = () => undefined
    setGetUserMedia(() => new Promise<MediaStream>((r) => (resolve = r)))
    const { result, unmount } = renderHook(() => useCameraStream())
    let pending: Promise<unknown> = Promise.resolve()
    act(() => {
      pending = result.current.startStream()
    })
    unmount()
    await act(async () => {
      resolve(stream)
      await pending
    })
    expect(track.stop).toHaveBeenCalled()
  })

  it('does not treat a preview play() failure as a permission denial and stops the stream', async () => {
    const { stream, track } = fakeStream()
    setGetUserMedia(async () => stream)
    const play = jest.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new DOMException('', 'NotAllowedError'))
    const { result } = renderHook(() => useCameraStream())
    result.current.videoRef.current = document.createElement('video')
    let status
    await act(async () => {
      status = await result.current.startStream()
    })
    expect(status).toBe('error')
    expect(track.stop).toHaveBeenCalled()
    play.mockRestore()
  })

  it('reports an error when the camera track ends', async () => {
    const listeners: Record<string, () => void> = {}
    const track = { stop: jest.fn(), addEventListener: (name: string, fn: () => void) => (listeners[name] = fn) }
    setGetUserMedia(async () => ({ getTracks: () => [track] }) as unknown as MediaStream)
    const { result } = renderHook(() => useCameraStream())
    await act(async () => {
      await result.current.startStream()
    })
    act(() => listeners.ended())
    expect(result.current.status).toBe('error')
    expect(result.current.error).toBe('The camera stopped. Please try again.')
  })
})
