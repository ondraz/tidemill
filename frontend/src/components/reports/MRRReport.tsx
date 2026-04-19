import { useTimeRange } from '@/hooks/useTimeRange'
import { useMRR, useMRRBreakdown, useMRRWaterfall, useARR } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { MRRBreakdownChart } from '@/components/charts/MRRBreakdownChart'
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

  // Transform breakdown: API returns {movement_type, amount_base} in cents
  // Ensure all 5 movement types are present (including reactivation)
  const MOVEMENT_TYPES = ['new', 'expansion', 'reactivation', 'contraction', 'churn'] as const
  const breakdownMap = new Map(
    (breakdown ?? []).map((row) => [
      String(row.movement_type ?? '').toLowerCase(),
      (Number(row.amount_base) || 0) / 100,
    ])
  )
  const breakdownData = MOVEMENT_TYPES.map((type) => ({
    type: type.replace(/^./, (c) => c.toUpperCase()),
    Amount: breakdownMap.get(type) ?? 0,
  }))

  // Quick Ratio = (new + expansion + reactivation) / |churn + contraction|.
  const gains =
    (breakdownMap.get('new') ?? 0) +
    (breakdownMap.get('expansion') ?? 0) +
    (breakdownMap.get('reactivation') ?? 0)
  const losses =
    Math.abs(breakdownMap.get('churn') ?? 0) +
    Math.abs(breakdownMap.get('contraction') ?? 0)
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
        title="MRR Breakdown"
        chartConfig={{
          name: 'MRR Breakdown',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/breakdown',
          params: { start, end },
          chartType: 'bar',
          timeRangeMode: 'fixed',
        }}
      >
        <MRRBreakdownChart
          data={breakdownData}
          loading={breakdownLoading}
        />
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
