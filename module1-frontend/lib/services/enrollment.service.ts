/**
 * Used by the History filter dropdown (Task 1.9: "Add filter dropdown by course").
 * Endpoint: GET /enrollments/my-enrollments
 */

import httpClient from '@/lib/utils/http-client'

export interface MyEnrollment {
  id: string
  course_id: string
  course_code: string
  course_name: string
  semester?: string
  instructor_name?: string
  enrolled_at?: string
  is_active?: boolean
}

export async function getMyEnrollments(): Promise<MyEnrollment[]> {
  const response = await httpClient.get<MyEnrollment[]>('/enrollments/my-enrollments')
  return response.data
}
