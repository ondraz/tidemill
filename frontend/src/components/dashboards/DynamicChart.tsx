import { useMetric } from '@/hooks/useMetrics'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { CohortHeatmap } from '@/components/charts/CohortHeatmap'
import { KPICard } from '@/components/charts/KPICard'
import { formatCurrency, formatPercent, formatPeriod } from '@/lib/formatters'
import { resolveRelativeRange } from '@/lib/constants'
import type { ChartConfig, Interval, WaterfallEntry, CohortEntry, TimeSeriesPoint } from '@/lib/types'

interface DynamicChartProps {
  config: ChartConfig
  inherited?: { start: string; end: string; interval?: Interval }
}

export function DynamicChart({ config, inherited }: DynamicChartProps) {
  // Resolve time range
  let start = config.params.start
  let end = config.params.end
  let interval = config.params.interval
  if (config.timeRangeMode === 'relative' && config.relativeRange) {
    const resolved = resolveRelativeRange(config.relativeRange)
    start = resolved.start
    end = resolved.end
  } else if (config.timeRangeMode === 'inherit' && inherited) {
    start = inherited.start
    end = inherited.end
    if (inherited.interval) interval = inherited.interval
  }

  const params = {
    ...config.params,
    start,
    end,
    interval,
    dimensions: config.dimensions,
    filters: config.filters,
  }

  const { data, isLoading } = useMetric(config.endpoint, params)

  const formatter = config.metric === 'churn' || config.metric === 'retention'
    ? formatPercent
    : formatCurrency

  // Re-label the x-axis in the canonical per-granularity format
  // (Sep 2025, 2025-W34, 2025-Q3).  Data rows use ``date``/``period``
  // as their raw ISO timestamp.
  const withPeriodLabels = <T extends Record<string, unknown>>(rows: T[] | undefined): T[] => {
    if (!rows || !interval) return rows ?? []
    const key = 'date' in (rows[0] ?? {}) ? 'date' : 'period'
    return rows.map((r) => {
      const raw = r[key]
      if (typeof raw !== 'string') return r
      return { ...r, [key]: formatPeriod(raw, interval) }
    })
  }

  switch (config.chartType) {
    case 'line':
    case 'area': {
      const rows = withPeriodLabels((data as TimeSeriesPoint[]) ?? [])
      return (
        <TimeSeriesChart
          data={rows}
          dataKey={Object.keys(rows[0] ?? {}).find((k) => k !== 'date') ?? 'value'}
          formatter={formatter}
          loading={isLoading}
        />
      )
    }
    case 'bar':
    case 'stacked_bar': {
      const rows = withPeriodLabels((data as Record<string, unknown>[]) ?? [])
      const bars = config.dimensions?.length
        ? config.dimensions
        : [Object.keys(rows[0] ?? {}).find((k) => k !== 'date') ?? 'value']
      return (
        <BarBreakdownChart
          data={rows}
          bars={bars}
          formatter={formatter}
          loading={isLoading}
          stacked={config.chartType === 'stacked_bar'}
        />
      )
    }
    case 'waterfall':
      return (
        <WaterfallChart
          data={(data as WaterfallEntry[]) ?? []}
          interval={interval}
          loading={isLoading}
        />
      )
    case 'cohort_heatmap':
      return <CohortHeatmap data={(data as CohortEntry[]) ?? []} loading={isLoading} />
    case 'kpi':
      return (
        <KPICard
          title={config.name}
          value={data != null ? String(data) : '—'}
          loading={isLoading}
        />
      )
    default:
      return <div className="text-sm text-muted-foreground">Unsupported chart type: {config.chartType}</div>
  }
}
