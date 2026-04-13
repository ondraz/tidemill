import { useTimeRange } from '@/hooks/useTimeRange'
import { useMRR, useMRRBreakdown, useMRRWaterfall } from '@/hooks/useMetrics'
import { useMetric } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { MRRBreakdownChart } from '@/components/charts/MRRBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { DimensionPicker } from '@/components/controls/DimensionPicker'
import { formatCurrency } from '@/lib/formatters'
import { MRR_DIMENSIONS } from '@/lib/constants'
import { useState } from 'react'
import type { WaterfallEntry } from '@/lib/types'

export function MRRReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })
  const [dimensions, setDimensions] = useState<string[]>([])

  const seriesParams = { start, end, interval, dimensions }
  const { data: breakdown, isLoading: breakdownLoading } = useMRRBreakdown<Record<string, unknown>[]>(seriesParams)
  const { data: waterfall, isLoading: waterfallLoading } = useMRRWaterfall<WaterfallEntry[]>({ start, end })
  const { data: currentMrr, isLoading: mrrLoading } = useMRR<number>({})
  const { data: currentArr, isLoading: arrLoading } = useMetric<number>('/api/metrics/arr', {})

  // Derive MRR Over Time from waterfall ending_mrr (cents → dollars)
  const mrrOverTime = (waterfall ?? []).map((row) => ({
    date: row.month + '-01',
    mrr: row.ending_mrr / 100,
  }))

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Monthly Recurring Revenue</h2>
      </div>

      <TimeRangePicker
        onSelectRange={(r) => setRange({ range: r })}
        onSelectInterval={(i) => setRange({ interval: i })}
        currentInterval={interval}
      />

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
      </div>

      <ChartContainer
        title="MRR Over Time"
        chartConfig={{
          name: 'MRR Over Time',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/waterfall',
          params: { start, end },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={mrrOverTime}
          dataKey="mrr"
          formatter={formatCurrency}
          loading={waterfallLoading}
        />
      </ChartContainer>

      <ChartContainer
        title="MRR Breakdown"
        chartConfig={{
          name: 'MRR Breakdown',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr/breakdown',
          params: { start, end, interval },
          dimensions,
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
          params: { start, end },
          chartType: 'waterfall',
          timeRangeMode: 'fixed',
        }}
      >
        <WaterfallChart data={waterfall ?? []} loading={waterfallLoading} />
      </ChartContainer>
    </div>
  )
}
