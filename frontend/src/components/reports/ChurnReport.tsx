import { useTimeRange } from '@/hooks/useTimeRange'
import { useChurn } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { formatPercent } from '@/lib/formatters'
import type { TimeSeriesPoint } from '@/lib/types'

export function ChurnReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })

  const { data: logoSeries, isLoading: logoLoading } = useChurn<TimeSeriesPoint[]>({
    start, end, interval, type: 'logo',
  })
  const { data: revSeries, isLoading: revLoading } = useChurn<TimeSeriesPoint[]>({
    start, end, interval, type: 'revenue',
  })
  const { data: logoRate, isLoading: logoRateLoading } = useChurn<number | null>({
    start, end, type: 'logo',
  })
  const { data: revRate, isLoading: revRateLoading } = useChurn<number | null>({
    start, end, type: 'revenue',
  })

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Churn</h2>

      <TimeRangePicker
        onSelectRange={(r) => setRange({ range: r })}
        onSelectInterval={(i) => setRange({ interval: i })}
        currentInterval={interval}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Logo Churn Rate"
          value={logoRate != null ? formatPercent(logoRate) : '—'}
          loading={logoRateLoading}
        />
        <KPICard
          title="Revenue Churn Rate"
          value={revRate != null ? formatPercent(revRate) : '—'}
          loading={revRateLoading}
        />
      </div>

      <ChartContainer
        title="Logo Churn Rate"
        chartConfig={{
          name: 'Logo Churn Rate',
          metric: 'churn',
          endpoint: '/api/metrics/churn',
          params: { start, end, interval, type: 'logo' },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={logoSeries ?? []}
          dataKey="logo_churn_rate"
          formatter={formatPercent}
          color="#dc2626"
          loading={logoLoading}
        />
      </ChartContainer>

      <ChartContainer
        title="Revenue Churn Rate"
        chartConfig={{
          name: 'Revenue Churn Rate',
          metric: 'churn',
          endpoint: '/api/metrics/churn',
          params: { start, end, interval, type: 'revenue' },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={revSeries ?? []}
          dataKey="revenue_churn_rate"
          formatter={formatPercent}
          color="#d97706"
          loading={revLoading}
        />
      </ChartContainer>
    </div>
  )
}
