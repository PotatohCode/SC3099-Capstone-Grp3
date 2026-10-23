/** Test doubles for camera, canvas, permissions and geolocation browser APIs used by the check-in components. */

export interface CameraMock {
  getUserMedia: jest.Mock
  track: { stop: jest.Mock }
}

/** Installs getUserMedia, a 640x480 video element and a canvas that encodes each grab as a distinct frame. */
export function installCamera(options: { deny?: boolean } = {}): CameraMock {
  const track = { stop: jest.fn() }
  const getUserMedia = jest.fn(async () => {
    if (options.deny) throw new DOMException('', 'NotAllowedError')
    return { getTracks: () => [track] } as unknown as MediaStream
  })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 640 })
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 480 })
  Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: jest.fn(async () => undefined) })
  Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', { configurable: true, writable: true, value: null })
  let n = 0
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value: () => ({ drawImage: () => undefined }) })
  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    configurable: true,
    value: () => `data:image/jpeg;base64,RlJBTUU${n++}`,
  })
  return { getUserMedia, track }
}

/** Makes navigator.permissions.query answer the given state for every name. */
export function installPermissions(state: 'granted' | 'denied' | 'prompt' | null) {
  Object.defineProperty(navigator, 'permissions', {
    configurable: true,
    value: state === null ? undefined : { query: jest.fn(async () => ({ state })) },
  })
}

/** Makes getCurrentPosition succeed with the given coordinates, or fail with the given error code. */
export function installGeolocation(result: { latitude: number; longitude: number; accuracy: number } | { errorCode: number }) {
  const getCurrentPosition = jest.fn((ok: PositionCallback, err: PositionErrorCallback) => {
    if ('errorCode' in result) err({ code: result.errorCode, PERMISSION_DENIED: 1 } as GeolocationPositionError)
    else ok({ coords: result } as GeolocationPosition)
  })
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition } })
  return getCurrentPosition
}
