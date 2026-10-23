'use client'

import { CheckInProvider } from '@/lib/context/CheckInContext'
import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'
import { FaceEnrolledGuard } from '@/components/FaceEnrolledGuard'

export default function CheckInLayout({ children }: { children: React.ReactNode }) {
  return (
    <StudentOnlyGuard>
      <FaceEnrolledGuard>
        <CheckInProvider>{children}</CheckInProvider>
      </FaceEnrolledGuard>
    </StudentOnlyGuard>
  )
}
