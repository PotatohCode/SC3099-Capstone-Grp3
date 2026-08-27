/**
 * Shared TypeScript types mirroring docs/API-SPECIFICATION.md response/request shapes.
 * Kept centralized so services/hooks/pages share one contract (no `any`).
 */

export type UserRole = 'student' | 'instructor' | 'ta' | 'admin'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active?: boolean
  camera_consent?: boolean
  geolocation_consent?: boolean
  face_enrolled?: boolean
  created_at?: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export interface RefreshResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name: string
  role: UserRole
}

export interface LoginRequest {
  email: string
  password: string
}

export type SessionStatus = 'scheduled' | 'active' | 'closed' | 'cancelled'

export interface SessionSummary {
  id: string
  course_id: string
  course_code?: string
  course_name?: string
  instructor_id?: string
  name: string
  session_type?: string
  status: SessionStatus
  scheduled_start: string
  scheduled_end: string
  checkin_opens_at?: string
  checkin_closes_at?: string
  venue_name?: string
  venue_latitude?: number
  venue_longitude?: number
  geofence_radius_meters?: number
  require_liveness_check?: boolean
  require_face_match?: boolean
  total_enrolled?: number
  checked_in_count?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type CheckInStatus = 'pending' | 'approved' | 'flagged' | 'rejected' | 'appealed'

export interface RiskFactor {
  type: string
  weight: number
  severity?: string
}

export interface CheckInRequest {
  session_id: string
  latitude: number
  longitude: number
  location_accuracy_meters: number
  device_fingerprint: string
  liveness_challenge_response?: string
  qr_code?: string
}

export interface CheckInResponse {
  id: string
  session_id: string
  student_id: string
  status: CheckInStatus
  checked_in_at: string
  latitude?: number
  longitude?: number
  distance_from_venue_meters?: number
  liveness_passed?: boolean | null
  liveness_score?: number | null
  risk_score?: number
  risk_factors?: RiskFactor[]
}

export interface CheckInHistoryItem {
  id: string
  session_id: string
  session_name: string
  course_code?: string
  status: CheckInStatus
  checked_in_at: string
  risk_score?: number
  appeal_reason?: string | null
  appealed_at?: string | null
}

export interface AppealRequest {
  appeal_reason: string
}

export interface AppealResponse {
  id: string
  status: CheckInStatus
  appeal_reason: string
  appealed_at: string
}

export type DevicePlatform = 'ios' | 'android' | 'web' | 'desktop'

export interface DeviceRegisterRequest {
  device_fingerprint: string
  device_name: string
  platform: DevicePlatform
  public_key?: string
}

export interface DeviceRegisterResponse {
  id: string
  device_fingerprint: string
  device_name: string
  platform: DevicePlatform
  is_trusted: boolean
  trust_score: string
  is_active: boolean
  first_seen_at: string
}

export interface ApiErrorBody {
  detail?: string | { loc: (string | number)[]; msg: string; type: string }[]
}
