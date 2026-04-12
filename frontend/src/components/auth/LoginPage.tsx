import { Show, SignInButton, SignUpButton } from '@clerk/react'
import { Navigate } from 'react-router-dom'
import { useAuthConfig } from '@/hooks/useAuth'

export function LoginPage() {
  const { data: config } = useAuthConfig()

  // Auth disabled — go straight to app
  if (config && !config.auth_enabled) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-tremor-background-muted">
      <Show when="signed-in">
        <Navigate to="/" replace />
      </Show>
      <Show when="signed-out">
        <div className="bg-tremor-background rounded-lg shadow-md p-8 w-full max-w-sm text-center">
          <h1 className="text-2xl font-semibold mb-2">Tidemill</h1>
          <p className="text-tremor-content text-sm mb-6">Subscription Analytics</p>
          <div className="flex flex-col gap-3">
            <SignInButton>
              <button className="w-full rounded-md bg-tremor-brand text-tremor-brand-inverted px-4 py-2.5 text-sm font-medium hover:bg-tremor-brand-emphasis">
                Sign in
              </button>
            </SignInButton>
            <SignUpButton>
              <button className="w-full rounded-md border border-tremor-border text-tremor-content-strong px-4 py-2.5 text-sm font-medium hover:bg-tremor-background-subtle">
                Sign up
              </button>
            </SignUpButton>
          </div>
        </div>
      </Show>
    </div>
  )
}
