import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { useAuth } from '@clerk/react'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { AuthGuard } from '@/components/auth/AuthGuard'
import { setTokenProvider } from '@/api/client'

export function App() {
  const { getToken } = useAuth()

  // Wire Clerk session token into the API client for all fetch calls
  useEffect(() => {
    setTokenProvider(getToken)
  }, [getToken])

  return (
    <AuthGuard>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          <main className="flex-1 p-6 overflow-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </AuthGuard>
  )
}
