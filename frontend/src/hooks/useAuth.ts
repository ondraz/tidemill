import { useQuery } from '@tanstack/react-query'
import { fetchAuthConfig } from '@/api/auth'

export function useAuthConfig() {
  return useQuery({
    queryKey: ['auth', 'config'],
    queryFn: fetchAuthConfig,
    staleTime: Infinity,
  })
}
