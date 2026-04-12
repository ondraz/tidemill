import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ClerkProvider } from '@clerk/react'
import { router } from './routes'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined

function Root() {
  if (clerkKey) {
    // ClerkProvider reads VITE_CLERK_PUBLISHABLE_KEY from the environment.
    return (
      // @ts-expect-error – publishableKey is read from env by the SDK at runtime
      <ClerkProvider afterSignOutUrl="/login">
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ClerkProvider>
    )
  }

  // No Clerk key configured — auth disabled, render without ClerkProvider
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
