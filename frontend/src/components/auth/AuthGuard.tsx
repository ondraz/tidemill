import { type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { Show } from '@clerk/react'
import { useAuthConfig } from '@/hooks/useAuth'

export function AuthGuard({ children }: { children: ReactNode }) {
  const { data: config, isLoading: configLoading } = useAuthConfig()

  // Auth disabled — allow through
  if (!configLoading && config && !config.auth_enabled) {
    return <>{children}</>
  }

  if (configLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-tremor-content">Loading...</div>
      </div>
    )
  }

  return (
    <>
      <Show when="signed-in">{children}</Show>
      <Show when="signed-out">
        <Navigate to="/login" replace />
      </Show>
    </>
  )
}
