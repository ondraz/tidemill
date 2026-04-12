import { get } from './client'
import type { Interval } from '@/lib/types'

export interface MetricParams {
  start?: string
  end?: string
  at?: string
  interval?: Interval
  dimensions?: string[]
  filters?: Record<string, string>
  type?: string
}

function buildQuery(params: MetricParams): string {
  const sp = new URLSearchParams()
  if (params.start) sp.set('start', params.start)
  if (params.end) sp.set('end', params.end)
  if (params.at) sp.set('at', params.at)
  if (params.interval) sp.set('interval', params.interval)
  if (params.type) sp.set('type', params.type)
  params.dimensions?.forEach((d) => sp.append('dimensions', d))
  if (params.filters) {
    for (const [k, v] of Object.entries(params.filters)) {
      sp.append('filter', `${k}:${v}`)
    }
  }
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

export function fetchMetric<T>(endpoint: string, params: MetricParams = {}): Promise<T> {
  return get<T>(`${endpoint}${buildQuery(params)}`)
}

export function fetchMRR<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/mrr', params)
}

export function fetchMRRBreakdown<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/mrr/breakdown', params)
}

export function fetchMRRWaterfall<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/mrr/waterfall', params)
}

export function fetchChurn<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/churn', params)
}

export function fetchRetention<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/retention', params)
}

export function fetchLTV<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/ltv', params)
}

export function fetchTrials<T>(params: MetricParams = {}): Promise<T> {
  return fetchMetric<T>('/api/metrics/trials', params)
}

export function fetchSummary<T>(): Promise<T> {
  return get<T>('/api/metrics/summary')
}
