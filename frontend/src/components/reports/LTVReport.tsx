import { useTimeRange } from '@/hooks/useTimeRange'
import { useLTV } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { formatCurrency } from '@/lib/formatters'
import type { TimeSeriesPoint } from '@/lib/types'

interface LTVData {
  ltv?: number
  arpu?: number
  series?: TimeSeriesPoint[]
}

export function LTVReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })

  const { data, isLoading } = useLTV<LTVData>({ start, end, interval })

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Lifetime Value</h2>

      <TimeRangePicker
        onSelectRange={(r) => setRange({ range: r })}
        onSelectInterval={(i) => setRange({ interval: i })}
        currentInterval={interval}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="LTV"
          value={data?.ltv != null ? formatCurrency(data.ltv) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="ARPU"
          value={data?.arpu != null ? formatCurrency(data.arpu) : '—'}
          loading={isLoading}
        />
      </div>

      <ChartContainer
        title="LTV Over Time"
        chartConfig={{
          name: 'LTV Over Time',
          metric: 'ltv',
          endpoint: '/api/metrics/ltv',
          params: { start, end, interval },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={data?.series ?? []}
          dataKey="ltv"
          formatter={formatCurrency}
          color="#059669"
          loading={isLoading}
        />
      </ChartContainer>
    </div>
  )
}
