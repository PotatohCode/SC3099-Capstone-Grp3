/**
 * Central runtime configuration for the SAIV frontend.
 *
 * Per docs/recommended_design/INTEGRATION-GUIDE.md "Environment Variables Summary":
 *   NEXT_PUBLIC_API_URL=http://localhost:8000
 *   NEXT_PUBLIC_FACE_SERVICE_URL=http://localhost:8001 (reference only - never called directly)
 *
 * IMPLEMENTATION_PLAN.html Risk Analysis: "Critical: No Direct Access to Module 3" -
 * the face service URL is intentionally NOT used anywhere in this codebase. All face
 * processing must be proxied through Module 2 (Backend API).
 */

const rawApiUrl =
  process.env.NEXT_PUBLIC_API_URL && process.env.NEXT_PUBLIC_API_URL.length > 0
    ? process.env.NEXT_PUBLIC_API_URL
    : 'http://localhost:8000'

// Strip any trailing slash so we can safely concatenate paths.
export const API_ROOT_URL = rawApiUrl.replace(/\/+$/, '')

// Base URL used for the Backend API's versioned REST endpoints (API-SPECIFICATION.md).
export const API_BASE_URL = `${API_ROOT_URL}/api/v1`

// Public endpoints that must NOT receive an Authorization header and must never be
// intercepted for silent token refresh (Task 1.6 / Section 2.2 request interceptor rule).
export const PUBLIC_AUTH_PATHS = ['/auth/login', '/auth/register', '/auth/refresh']
