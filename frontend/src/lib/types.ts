export interface User {
  id: string
  email: string
  name: string | null
  avatar_url: string | null
}

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface Dashboard {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string | null
}

export interface DashboardDetail extends Dashboard {
  sections: DashboardSection[]
}

export interface DashboardSection {
  id: string
  title: string
  position: number
  charts: DashboardChartEntry[]
}

export interface DashboardChartEntry {
  id: string
  saved_chart_id: string
  position: number
  chart: { name: string; config: ChartConfig }
}

export interface SavedChart {
  id: string
  name: string
  config: ChartConfig
  created_at: string
  updated_at: string | null
}

export type MetricName = 'mrr' | 'churn' | 'retention' | 'ltv' | 'trials'

export type ChartType =
  | 'line'
  | 'area'
  | 'bar'
  | 'stacked_bar'
  | 'waterfall'
  | 'cohort_heatmap'
  | 'funnel'
  | 'kpi'

export type TimeRangeMode = 'fixed' | 'relative' | 'inherit'

export type RelativeRange =
  | 'last_7d'
  | 'last_30d'
  | 'last_90d'
  | 'last_1y'
  | 'ytd'
  | 'all_time'
  | 'last_full_month'
  | 'last_3_full_months'
  | 'last_6_full_months'
  | 'last_12_full_months'

export type Interval = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface ChartConfig {
  name: string
  metric: MetricName
  endpoint: string
  params: {
    start?: string
    end?: string
    at?: string
    interval?: Interval
    type?: string
  }
  dimensions?: string[]
  filters?: Record<string, string>
  chartType: ChartType
  timeRangeMode: TimeRangeMode
  relativeRange?: RelativeRange
}

export interface TimeSeriesPoint {
  date: string
  [key: string]: string | number
}

export interface WaterfallEntry {
  period: string
  starting_mrr: number
  new: number
  expansion: number
  contraction: number
  churn: number
  reactivation: number
  net_change: number
  ending_mrr: number
}

export interface CohortEntry {
  cohort_month: string
  active_month: string
  retention_rate: number
  months_since: number
}

export interface ChurnCustomerDetail {
  customer_id: string
  customer_name: string | null
  active_at_start: boolean
  fully_churned: boolean
  churned_mrr_cents: number
  starting_mrr_cents: number
}

export interface ChurnRevenueEvent {
  customer_id: string
  customer_name: string | null
  mrr_cents: number
  events: number
}

export interface CohortLTVEntry {
  cohort_month: string
  customer_count: number
  total_revenue: number
  avg_revenue_per_customer: number
}

export interface TrialFunnel {
  started: number
  converted: number
  expired: number
  conversion_rate: number | null
}

export interface TrialSeriesRow {
  period: string
  started: number
  converted: number
  expired: number
  conversion_rate: number | null
}
