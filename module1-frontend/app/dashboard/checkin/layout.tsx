'use client'

import { CheckInProvider } from '@/lib/context/CheckInContext'
import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'

export default function CheckInLayout({ children }: { children: React.ReactNode }) {
  return (
    <StudentOnlyGuard>
      <CheckInProvider>{children}</CheckInProvider>
    </StudentOnlyGuard>
  )
}
