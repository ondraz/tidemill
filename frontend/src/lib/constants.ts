import type { RelativeRange } from './types'
import { subDays, subYears, startOfYear, startOfMonth, subMonths, format } from 'date-fns'

export const RELATIVE_RANGES: { label: string; value: RelativeRange }[] = [
  { label: 'Last 7 days', value: 'last_7d' },
  { label: 'Last 30 days', value: 'last_30d' },
  { label: 'Last 90 days', value: 'last_90d' },
  { label: 'Last year', value: 'last_1y' },
  { label: 'This month', value: 'this_month' },
  { label: 'Last full month', value: 'last_full_month' },
  { label: 'Last 3 full months', value: 'last_3_full_months' },
  { label: 'Last 6 full months', value: 'last_6_full_months' },
  { label: 'Last 12 full months', value: 'last_12_full_months' },
  { label: 'Quarter to date', value: 'qtd' },
  { label: 'Year to date', value: 'ytd' },
  { label: 'All time', value: 'all_time' },
]

// Date ranges are closed-closed `[start, end]` — both endpoints are
// inclusive. The backend treats `end` as the last millisecond of that
// calendar day, so passing today's date includes today's events.
export function resolveRelativeRange(range: RelativeRange): { start: string; end: string } {
  const now = new Date()
  const end = format(now, 'yyyy-MM-dd')
  // Full-months ranges end on the last day of the previous complete month
  // so the selection auto-shifts when the calendar crosses a month boundary.
  const lastFullMonthEnd = format(subDays(startOfMonth(now), 1), 'yyyy-MM-dd')
  switch (range) {
    case 'last_7d':
      return { start: format(subDays(now, 7), 'yyyy-MM-dd'), end }
    case 'last_30d':
      return { start: format(subDays(now, 30), 'yyyy-MM-dd'), end }
    case 'last_90d':
      return { start: format(subDays(now, 90), 'yyyy-MM-dd'), end }
    case 'last_1y':
      return { start: format(subYears(now, 1), 'yyyy-MM-dd'), end }
    case 'this_month':
      return { start: format(startOfMonth(now), 'yyyy-MM-dd'), end }
    case 'qtd': {
      const q = Math.floor(now.getMonth() / 3)
      const start = new Date(now.getFullYear(), q * 3, 1)
      return { start: format(start, 'yyyy-MM-dd'), end }
    }
    case 'ytd':
      return { start: format(startOfYear(now), 'yyyy-MM-dd'), end }
    case 'all_time':
      return { start: '2020-01-01', end }
    case 'last_full_month':
      return {
        start: format(startOfMonth(subMonths(now, 1)), 'yyyy-MM-dd'),
        end: lastFullMonthEnd,
      }
    case 'last_3_full_months':
      return {
        start: format(startOfMonth(subMonths(now, 3)), 'yyyy-MM-dd'),
        end: lastFullMonthEnd,
      }
    case 'last_6_full_months':
      return {
        start: format(startOfMonth(subMonths(now, 6)), 'yyyy-MM-dd'),
        end: lastFullMonthEnd,
      }
    case 'last_12_full_months':
      return {
        start: format(startOfMonth(subMonths(now, 12)), 'yyyy-MM-dd'),
        end: lastFullMonthEnd,
      }
  }
}

// Dimensions here must be (a) declared on the metric's primary Cube and
// (b) backed by real data in the current connectors. The MRR list is the
// intersection between MRRSnapshotCube and MRRMovementCube so the picker
// works on every MRR chart (overview + over-time + breakdown + waterfall).
// `churn_type` is excluded because the endpoint already filters on it
// (type=logo|revenue), so grouping by it is a no-op.
export const MRR_DIMENSIONS = [
  'currency',
  'plan_name',
  'plan_interval',
  'pricing_model',
  'usage_type',
  'product_name',
  'customer_country',
  'collection_method',
  'tenure_months',
  'cohort_month',
]

export const CHURN_DIMENSIONS = [
  'cancel_reason',
  'customer_country',
  'tenure_months',
  'cohort_month',
]

export const RETENTION_DIMENSIONS = ['customer_country', 'tenure_months']

// `customer_created_month` is omitted because the LTV cohort metric joins
// MRRMovementCube internally for the segment filter and that cube doesn't
// declare the dim — the request 500s. Use `cohort_month` instead.
export const LTV_DIMENSIONS = [
  'currency',
  'customer_country',
  'cohort_month',
  'tenure_months',
]

export const TRIALS_DIMENSIONS = ['customer_country', 'tenure_months']

export const DIMENSIONS_BY_METRIC: Record<string, string[]> = {
  mrr: MRR_DIMENSIONS,
  churn: CHURN_DIMENSIONS,
  retention: RETENTION_DIMENSIONS,
  ltv: LTV_DIMENSIONS,
  trials: TRIALS_DIMENSIONS,
}
