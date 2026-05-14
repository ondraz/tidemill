import { useState } from 'react'
import { useTimeRange } from '@/hooks/useTimeRange'
import { useTrialFunnel, useTrialSeries } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { ReportControls } from '@/components/controls/ReportControls'
import { formatPercent, formatNumber, formatPeriod } from '@/lib/formatters'
import { COLORS } from '@/lib/colors'
import { chartTimeRangeConfig } from '@/lib/chartTimeRange'
import type { TrialFunnel, TrialSeriesRow } from '@/lib/types'

export function TrialsReport() {
  const { start, end, interval, range } = useTimeRange({ range: 'last_1y' })
  const timeCfg = chartTimeRangeConfig({ start, end, interval, range })
  const [dimensions, setDimensions] = useState<string[]>([])
  const [segment, setSegment] = useState<string | null>(null)
  const [compareSegments, setCompareSegments] = useState<string[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const scopeParams = {
    segment: segment ?? undefined,
    compare_segments: compareSegments.length ? compareSegments : undefined,
    filters: Object.keys(filters).length ? filters : undefined,
  }

  const { data: funnel, isLoading: funnelLoading } = useTrialFunnel<TrialFunnel>({ start, end, ...scopeParams })
  const { data: rawSeries, isLoading: seriesLoading } = useTrialSeries<TrialSeriesRow[]>({
    start, end, interval, ...scopeParams,
  })

  const series = Array.isArray(rawSeries) ? rawSeries : []

  const conversionSeries = series.map((row) => ({
    date: formatPeriod(String(row.period ?? ''), interval),
    conversion_rate: row.conversion_rate,
  }))

  const outcomesSeries = series.map((row) => ({
    date: formatPeriod(String(row.period ?? ''), interval),
    Converted: row.converted,
    Expired: row.expired,
    Pending: Math.max(0, row.started - row.converted - row.expired),
  }))

  // Trial funnel — one row per stage, for the bar chart.
  const funnelData = funnel
    ? [
        { stage: 'Started', Count: funnel.started },
        { stage: 'Converted', Count: funnel.converted },
        { stage: 'Expired', Count: funnel.expired },
      ]
    : []

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Trials</h2>

      <ReportControls
        metric="trials"
        dimensions={dimensions}
        onDimensionsChange={setDimensions}
        segment={segment}
        onSegmentChange={setSegment}
        compareSegments={compareSegments}
        onCompareSegmentsChange={setCompareSegments}
        filters={filters}
        onFiltersChange={setFilters}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Conversion Rate"
          value={funnel?.conversion_rate != null ? formatPercent(funnel.conversion_rate) : '—'}
          loading={funnelLoading}
        />
        <KPICard
          title="Started"
          value={funnel?.started != null ? formatNumber(funnel.started) : '—'}
          loading={funnelLoading}
        />
        <KPICard
          title="Converted"
          value={funnel?.converted != null ? formatNumber(funnel.converted) : '—'}
          loading={funnelLoading}
        />
        <KPICard
          title="Expired"
          value={funnel?.expired != null ? formatNumber(funnel.expired) : '—'}
          loading={funnelLoading}
        />
      </div>

      <ChartContainer
        title="Trial Funnel"
        chartConfig={{
          name: 'Trial Funnel',
          metric: 'trials',
          endpoint: '/api/metrics/trials/funnel',
          ...timeCfg,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          dimensions: dimensions.length ? dimensions : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'trial_funnel_bars',
          chartType: 'bar',
        }}
      >
        <BarBreakdownChart
          data={funnelData}
          bars={['Count']}
          xKey="stage"
          formatter={formatNumber}
          loading={funnelLoading}
        />
      </ChartContainer>

      <ChartContainer
        title="Monthly Trial Outcomes"
        chartConfig={{
          name: 'Monthly Trial Outcomes',
          metric: 'trials',
          endpoint: '/api/metrics/trials/series',
          ...timeCfg,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          dimensions: dimensions.length ? dimensions : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'trial_outcomes_bars',
          chartType: 'stacked_bar',
        }}
      >
        <BarBreakdownChart
          data={outcomesSeries}
          bars={['Converted', 'Expired', 'Pending']}
          formatter={formatNumber}
          loading={seriesLoading}
          stacked
        />
      </ChartContainer>

      <ChartContainer
        title="Trial Conversion Rate"
        chartConfig={{
          name: 'Trial Conversion Rate',
          metric: 'trials',
          endpoint: '/api/metrics/trials/series',
          ...timeCfg,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          dimensions: dimensions.length ? dimensions : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'trial_conversion_line',
          chartType: 'line',
        }}
      >
        <TimeSeriesChart
          data={conversionSeries}
          dataKey="conversion_rate"
          formatter={formatPercent}
          color={COLORS.converted}
          loading={seriesLoading}
        />
      </ChartContainer>
    </div>
  )
}
