import { useMetric } from '@/hooks/useMetrics'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { CohortHeatmap } from '@/components/charts/CohortHeatmap'
import { KPICard } from '@/components/charts/KPICard'
import { formatCurrency, formatPercent } from '@/lib/formatters'
import { resolveRelativeRange } from '@/lib/constants'
import type { ChartConfig, WaterfallEntry, CohortEntry, TimeSeriesPoint } from '@/lib/types'

interface DynamicChartProps {
  config: ChartConfig
}

export function DynamicChart({ config }: DynamicChartProps) {
  // Resolve time range
  let start = config.params.start
  let end = config.params.end
  if (config.timeRangeMode === 'relative' && config.relativeRange) {
    const resolved = resolveRelativeRange(config.relativeRange)
    start = resolved.start
    end = resolved.end
  }

  const params = {
    ...config.params,
    start,
    end,
    dimensions: config.dimensions,
    filters: config.filters,
  }

  const { data, isLoading } = useMetric(config.endpoint, params)

  const formatter = config.metric === 'churn' || config.metric === 'retention'
    ? formatPercent
    : formatCurrency

  switch (config.chartType) {
    case 'line':
    case 'area':
      return (
        <TimeSeriesChart
          data={(data as TimeSeriesPoint[]) ?? []}
          dataKey={Object.keys((data as TimeSeriesPoint[])?.[0] ?? {}).find((k) => k !== 'date') ?? 'value'}
          formatter={formatter}
          loading={isLoading}
        />
      )
    case 'bar':
    case 'stacked_bar': {
      const bars = config.dimensions?.length
        ? config.dimensions
        : [Object.keys((data as Record<string, unknown>[])?.[0] ?? {}).find((k) => k !== 'date') ?? 'value']
      return (
        <BarBreakdownChart
          data={(data as Record<string, unknown>[]) ?? []}
          bars={bars}
          formatter={formatter}
          loading={isLoading}
          stacked={config.chartType === 'stacked_bar'}
        />
      )
    }
    case 'waterfall':
      return <WaterfallChart data={(data as WaterfallEntry[]) ?? []} loading={isLoading} />
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
