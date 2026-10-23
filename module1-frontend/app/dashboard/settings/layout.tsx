'use client'

import { StudentOnlyGuard } from '@/components/StudentOnlyGuard'

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <StudentOnlyGuard>{children}</StudentOnlyGuard>
}
