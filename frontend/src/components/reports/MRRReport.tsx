import { useState } from 'react'
import { useTimeRange } from '@/hooks/useTimeRange'
import { useMRR, useMRRBreakdown, useMRRWaterfall } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { DimensionPicker } from '@/components/controls/DimensionPicker'
import { formatCurrency } from '@/lib/formatters'
import { MRR_DIMENSIONS } from '@/lib/constants'
import type { TimeSeriesPoint, WaterfallEntry } from '@/lib/types'

export function MRRReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })
  const [dimensions, setDimensions] = useState<string[]>([])

  const seriesParams = { start, end, interval, dimensions }
  const { data: series, isLoading: seriesLoading } = useMRR<TimeSeriesPoint[]>(seriesParams)
  const { data: breakdown, isLoading: breakdownLoading } = useMRRBreakdown<TimeSeriesPoint[]>(seriesParams)
  const { data: waterfall, isLoading: waterfallLoading } = useMRRWaterfall<WaterfallEntry[]>({ start, end })
  const { data: current, isLoading: currentLoading } = useMRR<{ mrr?: number; arr?: number }>({})

  const breakdownBars = dimensions.length > 0 ? dimensions : ['mrr']

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
          value={current?.mrr != null ? formatCurrency(current.mrr) : '—'}
          loading={currentLoading}
        />
        <KPICard
          title="ARR"
          value={current?.arr != null ? formatCurrency(current.arr) : '—'}
          loading={currentLoading}
        />
      </div>

      <ChartContainer
        title="MRR Over Time"
        chartConfig={{
          name: 'MRR Over Time',
          metric: 'mrr',
          endpoint: '/api/metrics/mrr',
          params: { start, end, interval },
          dimensions,
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={series ?? []}
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
          params: { start, end, interval },
          dimensions,
          chartType: 'bar',
          timeRangeMode: 'fixed',
        }}
      >
        <BarBreakdownChart
          data={breakdown ?? []}
          bars={breakdownBars}
          formatter={formatCurrency}
          loading={breakdownLoading}
          stacked={dimensions.length > 0}
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
