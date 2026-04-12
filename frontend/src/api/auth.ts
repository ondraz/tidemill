import { get } from './client'

export function fetchAuthConfig(): Promise<{
  auth_enabled: boolean
  clerk_publishable_key: string | null
}> {
  return get('/auth/config')
}
