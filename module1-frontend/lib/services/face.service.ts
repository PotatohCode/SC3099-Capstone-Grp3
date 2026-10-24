/** Face identity enrollment: sends one raw base64 JPEG to POST /users/me/face/enroll; the backend keeps only a hash. */
import httpClient from '@/lib/utils/http-client'
import type { FaceEnrollResponse } from '@/lib/types'

export async function enrollFace(image: string): Promise<FaceEnrollResponse> {
  const response = await httpClient.post<FaceEnrollResponse>('/users/me/face/enroll', { image }, { timeout: 30000 })
  return response.data
}
