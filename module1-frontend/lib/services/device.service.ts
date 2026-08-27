/**
 * Component tree Section 2.1: "device.service.ts [Device fingerprint + registration - Task 1.7]"
 * Endpoint: POST /devices/register
 */

import httpClient from '@/lib/utils/http-client'
import type { DeviceRegisterRequest, DeviceRegisterResponse } from '@/lib/types'

export async function registerDevice(
  payload: DeviceRegisterRequest
): Promise<DeviceRegisterResponse> {
  const response = await httpClient.post<DeviceRegisterResponse>('/devices/register', payload)
  return response.data
}
