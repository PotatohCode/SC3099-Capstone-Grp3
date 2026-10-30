/** Face identity enrollment: sends one raw base64 JPEG (plus an instructor reset code when replacing a face) to POST /users/me/face/enroll. */
import httpClient from '@/lib/utils/http-client'
import type { FaceEnrollResponse } from '@/lib/types'

export interface ResetCodeCheck {
  required: boolean
  valid: boolean
}

/** Checks an instructor reset code before the camera opens; it doesn't use the code up. */
export async function checkResetCode(resetCode: string): Promise<ResetCodeCheck> {
  const response = await httpClient.post<ResetCodeCheck>('/users/me/face/reset-code/check', { reset_code: resetCode })
  return response.data
}

export async function enrollFace(image: string, resetCode?: string): Promise<FaceEnrollResponse> {
  const body = resetCode ? { image, reset_code: resetCode } : { image }
  const response = await httpClient.post<FaceEnrollResponse>('/users/me/face/enroll', body, { timeout: 30000 })
  return response.data
}
