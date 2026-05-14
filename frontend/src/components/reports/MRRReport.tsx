import { useTimeRange } from '@/hooks/useTimeRange'
import { useMRR, useMRRBreakdown, useMRRWaterfall, useARR } from '@/hooks/useMetrics'
import { useSegments } from '@/hooks/useSegments'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { MRRBreakdownChart } from '@/components/charts/MRRBreakdownChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { ReportControls } from '@/components/controls/ReportControls'
import { formatCurrency } from '@/lib/formatters'
import { chartTimeRangeConfig } from '@/lib/chartTimeRange'
import {
  cumulativeMrrSeries,
  type CumulativeMrrGroupBy,
  type MrrMovementRow,
} from '@/lib/mrrSeries'
import { useMemo, useState } from 'react'
import type { WaterfallEntry } from '@/lib/types'

type MRRSeriesRow = MrrMovementRow

export function MRRReport() {
  const { start, end, interval, range } = useTimeRange({ range: 'last_1y' })
  const timeCfg = chartTimeRangeConfig({ start, end, interval, range })
  const [dimensions, setDimensions] = useState<string[]>([])
  const [segment, setSegment] = useState<string | null>(null)
  const [compareSegments, setCompareSegments] = useState<string[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  // Segment + filter params are piped into every hook below so MRR cards +
  // charts all narrow consistently.
  const scopeParams = {
    segment: segment ?? undefined,
    compare_segments: compareSegments.length ? compareSegments : undefined,
    filters: Object.keys(filters).length ? filters : undefined,
  }

  const { data: breakdown, isLoading: breakdownLoading } = useMRRBreakdown<Record<string, unknown>[]>({ start, end, dimensions, ...scopeParams })
  const { data: waterfall, isLoading: waterfallLoading } = useMRRWaterfall<WaterfallEntry[]>({ start, end, interval, ...scopeParams })
  const { data: currentMrr, isLoading: mrrLoading } = useMRR<number>({ ...scopeParams })
  const { data: currentArr, isLoading: arrLoading } = useARR<number>({ ...scopeParams })

  // Fetch MRR movements from beginning of time so cumulative sum = MRR level.
  // Pass the picked dimension so the API returns one row per (period, value)
  // and the over-time chart can render a line per dimension value.
  const { data: mrrSeries, isLoading: seriesLoading } = useMRR<MRRSeriesRow[]>({
    start: '2000-01-01',
    end,
    interval,
    dimensions,
    ...scopeParams,
  })

  const { data: segmentDefs } = useSegments()
  const segmentNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const s of segmentDefs ?? []) m.set(s.id, s.name)
    return m
  }, [segmentDefs])

  // Compute cumulative MRR levels from movements, then sample at every
  // visible period. Sampling (rather than filtering on movement dates) keeps
  // the line drawn even when the active segment has no movements inside the
  // visible window — the level just carries forward from the last movement.
  const { mrrOverTime, overTimeSeries } = useMemo(() => {
    const rows = mrrSeries ?? []
    let groupBy: CumulativeMrrGroupBy | undefined
    if (compareSegments.length > 0) {
      groupBy = {
        kind: 'segment',
        orderedIds: compareSegments,
        label: (id) => segmentNameById.get(id) ?? id,
      }
    } else if (dimensions[0]) {
      groupBy = { kind: 'dimension', key: dimensions[0] }
    }
    const result = cumulativeMrrSeries(rows, start, end, interval, { groupBy })
    return { mrrOverTime: result.data, overTimeSeries: result.series }
  }, [mrrSeries, start, end, interval, compareSegments, segmentNameById, dimensions])

  // Transform breakdown: API returns {movement_type, amount_base} in cents.
  // When `dimensions` is set, each movement_type has one row per segment
  // value (e.g. {movement_type, currency, amount_base}). We pivot to
  // {type, <segA>: amount, <segB>: amount, ...} so the chart renders
  // stacked bars per segment; without a dimension we collapse to a single
  // Amount series so the chart looks the same as before.
  const MOVEMENT_TYPES = ['new', 'expansion', 'reactivation', 'contraction', 'churn'] as const
  const dimKey = dimensions[0]
  const { breakdownData, breakdownSegments, totalsByType } = useMemo(() => {
    const typeLabel = (t: string) => t.replace(/^./, (c) => c.toUpperCase())
    const totals = new Map<string, number>()

    if (!dimKey) {
      for (const row of breakdown ?? []) {
        const t = String(row.movement_type ?? '').toLowerCase()
        const amt = (Number(row.amount_base) || 0) / 100
        totals.set(t, (totals.get(t) ?? 0) + amt)
      }
      const data = MOVEMENT_TYPES.map((type) => ({
        type: typeLabel(type),
        Amount: totals.get(type) ?? 0,
      }))
      return { breakdownData: data, breakdownSegments: [] as string[], totalsByType: totals }
    }

    // Segment mode: pivot rows into one entry per movement_type with
    // columns keyed by segment value (null → "Unknown").
    const perType = new Map<string, Map<string, number>>()
    const segments = new Set<string>()
    for (const row of breakdown ?? []) {
      const t = String(row.movement_type ?? '').toLowerCase()
      const seg = row[dimKey] == null ? 'Unknown' : String(row[dimKey])
      const amt = (Number(row.amount_base) || 0) / 100
      segments.add(seg)
      totals.set(t, (totals.get(t) ?? 0) + amt)
      if (!perType.has(t)) perType.set(t, new Map())
      perType.get(t)!.set(seg, (perType.get(t)!.get(seg) ?? 0) + amt)
    }
    const segmentKeys = [...segments].sort()
    const data = MOVEMENT_TYPES.map((type) => {
      const row: Record<string, unknown> = { type: typeLabel(type) }
      for (const seg of segmentKeys) {
        row[seg] = perType.get(type)?.get(seg) ?? 0
      }
      return row
    })
    return { breakdownData: data, breakdownSegments: segmentKeys, totalsByType: totals }
  }, [breakdown, dimKey])

  // Quick Ratio = (new + expansion + reactivation) / |churn + contraction|.
  // Uses aggregated totals so it matches the headline MRR regardless of
  // whether segmentation is active.
  const gains =
    (totalsByType.get('new') ?? 0) +
    (totalsByType.get('expansion') ?? 0) +
    (totalsByType.get('reactivation') ?? 0)
  const losses =
    Math.abs(totalsByType.get('churn') ?? 0) +
    Math.abs(totalsByType.get('contraction') ?? 0)
  const quickRatio = losses > 0 ? gains / losses : null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Monthly Recurring Revenue</h2>
      </div>

      <ReportControls
        metric="mrr"
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
          title="Current MRR"
          value={currentMrr != null ? formatCurrency(currentMrr / 100) : '—'}
          loading={mrrLoading}
        />
        <KPICard
          title="ARR"
          value={currentArr != null ? formatCurrency(currentArr / 100) : '—'}
          loading={arrLoading}
        />
        <KPICard
          title="Quick Ratio"
          value={quickRatio != null ? quickRatio.toFixed(2) : '—'}
          subtitle="(new+exp+react) ÷ |churn+contraction|"
          loading={breakdownLoading}
        />
      </div>

      <ChartContainer
        title="MRR Over Time"
        chartConfig={{
          name: 'MRR Over Time',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr',
          ...timeCfg,
          dimensions: dimensions.length ? dimensions : undefined,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'mrr_cumulative_series',
          chartType: 'line',
        }}
      >
        <TimeSeriesChart
          data={mrrOverTime}
          dataKey="mrr"
          series={overTimeSeries}
          formatter={formatCurrency}
          loading={seriesLoading}
        />
      </ChartContainer>

      <ChartContainer
        title={dimKey ? `MRR Breakdown by ${dimKey}` : 'MRR Breakdown'}
        chartConfig={{
          name: dimKey ? `MRR Breakdown by ${dimKey}` : 'MRR Breakdown',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/breakdown',
          ...timeCfg,
          dimensions: dimKey ? [dimKey] : undefined,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'mrr_breakdown_bars',
          chartType: 'bar',
        }}
      >
        {dimKey ? (
          <BarBreakdownChart
            data={breakdownData}
            bars={breakdownSegments}
            xKey="type"
            formatter={formatCurrency}
            loading={breakdownLoading}
            stacked
          />
        ) : (
          <MRRBreakdownChart
            data={breakdownData as Array<{ type: string; Amount: number }>}
            loading={breakdownLoading}
          />
        )}
      </ChartContainer>

      <ChartContainer
        title="MRR Waterfall"
        chartConfig={{
          name: 'MRR Waterfall',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/waterfall',
          ...timeCfg,
          segment: segment ?? undefined,
          compareSegments: compareSegments.length ? compareSegments : undefined,
          filters: Object.keys(filters).length ? filters : undefined,
          transform: 'waterfall',
          chartType: 'waterfall',
        }}
      >
        <WaterfallChart data={waterfall ?? []} interval={interval} loading={waterfallLoading} />
      </ChartContainer>
    </div>
  )
}
