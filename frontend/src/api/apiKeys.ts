import { get, post, del } from './client'
import type { ApiKey } from '@/lib/types'

export const listApiKeys = () => get<ApiKey[]>('/api/keys')

export const createApiKey = (name: string) =>
  post<ApiKey & { key: string }>('/api/keys', { name })

export const revokeApiKey = (id: string) => del<{ status: string }>(`/api/keys/${id}`)
