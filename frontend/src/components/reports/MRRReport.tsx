import { useTimeRange } from '@/hooks/useTimeRange'
import { useMRR, useMRRBreakdown, useMRRWaterfall, useARR } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { MRRBreakdownChart } from '@/components/charts/MRRBreakdownChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { DimensionPicker } from '@/components/controls/DimensionPicker'
import { formatCurrency, formatPeriod } from '@/lib/formatters'
import { MRR_DIMENSIONS } from '@/lib/constants'
import { useMemo, useState } from 'react'
import type { WaterfallEntry } from '@/lib/types'

interface MRRSeriesRow {
  period: string
  amount_base: number
}

export function MRRReport() {
  const { start, end, interval } = useTimeRange({ range: 'last_1y' })
  const [dimensions, setDimensions] = useState<string[]>([])

  const { data: breakdown, isLoading: breakdownLoading } = useMRRBreakdown<Record<string, unknown>[]>({ start, end, dimensions })
  const { data: waterfall, isLoading: waterfallLoading } = useMRRWaterfall<WaterfallEntry[]>({ start, end, interval })
  const { data: currentMrr, isLoading: mrrLoading } = useMRR<number>({})
  const { data: currentArr, isLoading: arrLoading } = useARR<number>()

  // Fetch MRR movements from beginning of time so cumulative sum = MRR level
  const { data: mrrSeries, isLoading: seriesLoading } = useMRR<MRRSeriesRow[]>({
    start: '2000-01-01',
    end,
    interval,
  })

  // Compute cumulative MRR levels from movements, filter to visible range
  const mrrOverTime = useMemo(() => {
    if (!mrrSeries || mrrSeries.length === 0) return []
    // Sort by period ascending and compute running sum
    const sorted = [...mrrSeries].sort((a, b) => a.period.localeCompare(b.period))
    let level = 0
    const all = sorted.map((row) => {
      level += row.amount_base / 100
      return { iso: row.period.slice(0, 10), mrr: level }
    })
    return all
      .filter((pt) => pt.iso >= start)
      .map((pt) => ({ date: formatPeriod(pt.iso, interval), mrr: pt.mrr }))
  }, [mrrSeries, start, interval])

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

      <DimensionPicker
        available={MRR_DIMENSIONS}
        selected={dimensions}
        onChange={setDimensions}
        single
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
          params: { start, end, interval },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={mrrOverTime}
          dataKey="mrr"
          formatter={formatCurrency}
          loading={seriesLoading}
        />
      </ChartContainer>

      <ChartContainer
        title={dimKey ? `MRR Breakdown by ${dimKey}` : 'MRR Breakdown'}
        chartConfig={{
          name: 'MRR Breakdown',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/breakdown',
          params: { start, end, ...(dimKey ? { dimensions: [dimKey] } : {}) },
          chartType: 'bar',
          timeRangeMode: 'fixed',
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
          params: { start, end, interval },
          chartType: 'waterfall',
          timeRangeMode: 'fixed',
        }}
      >
        <WaterfallChart data={waterfall ?? []} interval={interval} loading={waterfallLoading} />
      </ChartContainer>
    </div>
  )
}
