/**
 * Component tree Section 2.1: "device.service.ts [Device fingerprint + registration - Task 1.7]"
 * Endpoint: POST /devices/register
 */

import httpClient from '@/lib/utils/http-client'
import type { DeviceRegisterRequest, DeviceRegisterResponse } from '@/lib/types'
import { parseApiError } from '@/lib/utils/api-error'
import {
  detectPlatform,
  getOrCreateDeviceFingerprint,
  rotateDeviceFingerprint,
} from '@/lib/utils/device-fingerprint'

export async function registerDevice(
  payload: DeviceRegisterRequest
): Promise<DeviceRegisterResponse> {
  const response = await httpClient.post<DeviceRegisterResponse>('/devices/register', payload)
  return response.data
}

/** Registers this install's device id, rotating it and retrying once if another user already owns it. */
export async function registerCurrentDevice(): Promise<DeviceRegisterResponse> {
  const attempt = (fingerprint: string) =>
    registerDevice({ device_fingerprint: fingerprint, device_name: 'Web Browser', platform: detectPlatform() })
  try {
    return await attempt(getOrCreateDeviceFingerprint())
  } catch (error) {
    const parsed = parseApiError(error)
    if (parsed.status === 400 && parsed.code === 'DEVICE_FINGERPRINT_TAKEN') {
      return attempt(rotateDeviceFingerprint())
    }
    throw error
  }
}
