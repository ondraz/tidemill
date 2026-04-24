import type { RelativeRange } from './types'
import { subDays, subYears, startOfYear, startOfMonth, subMonths, format } from 'date-fns'

export const RELATIVE_RANGES: { label: string; value: RelativeRange }[] = [
  { label: 'Last 7 days', value: 'last_7d' },
  { label: 'Last 30 days', value: 'last_30d' },
  { label: 'Last 90 days', value: 'last_90d' },
  { label: 'Last year', value: 'last_1y' },
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

// Dimensions here must be (a) declared on the metric's Cube and (b) backed
// by real data in the current connectors. Plan/product dims are omitted
// until the Stripe connector ingests plan.* / product.* events — today
// subscription.plan_id is always NULL so any join through `plan` returns
// empty.
export const MRR_DIMENSIONS = ['currency', 'customer_country']

// `churn_type` is excluded because the endpoint already filters on it
// (type=logo|revenue), so grouping by it is a no-op. The remaining dims
// are on ChurnEventCube via the `customer` join.
export const CHURN_DIMENSIONS = ['cancel_reason', 'customer_country']

export const RETENTION_DIMENSIONS: string[] = []

export const LTV_DIMENSIONS: string[] = []

export const TRIALS_DIMENSIONS: string[] = []
