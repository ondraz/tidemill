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

export type Interval = 'day' | 'week' | 'month' | 'year'

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
  month: string
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
