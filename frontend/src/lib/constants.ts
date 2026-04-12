import type { RelativeRange } from './types'
import { subDays, subYears, startOfYear, format } from 'date-fns'

export const RELATIVE_RANGES: { label: string; value: RelativeRange }[] = [
  { label: 'Last 7 days', value: 'last_7d' },
  { label: 'Last 30 days', value: 'last_30d' },
  { label: 'Last 90 days', value: 'last_90d' },
  { label: 'Last year', value: 'last_1y' },
  { label: 'Year to date', value: 'ytd' },
  { label: 'All time', value: 'all_time' },
]

export function resolveRelativeRange(range: RelativeRange): { start: string; end: string } {
  const now = new Date()
  const end = format(now, 'yyyy-MM-dd')
  switch (range) {
    case 'last_7d':
      return { start: format(subDays(now, 7), 'yyyy-MM-dd'), end }
    case 'last_30d':
      return { start: format(subDays(now, 30), 'yyyy-MM-dd'), end }
    case 'last_90d':
      return { start: format(subDays(now, 90), 'yyyy-MM-dd'), end }
    case 'last_1y':
      return { start: format(subYears(now, 1), 'yyyy-MM-dd'), end }
    case 'ytd':
      return { start: format(startOfYear(now), 'yyyy-MM-dd'), end }
    case 'all_time':
      return { start: '2020-01-01', end }
  }
}

export const MRR_DIMENSIONS = [
  'plan_id',
  'plan_interval',
  'plan_name',
  'product_name',
  'customer_country',
  'currency',
  'billing_scheme',
  'collection_method',
]

export const CHURN_DIMENSIONS = [
  'plan_interval',
  'customer_country',
  'currency',
]

export const RETENTION_DIMENSIONS = ['plan_interval', 'customer_country']

export const LTV_DIMENSIONS = ['plan_interval', 'customer_country']

export const TRIALS_DIMENSIONS = ['plan_interval']
