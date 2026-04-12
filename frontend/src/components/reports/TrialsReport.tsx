import { useTimeRange } from '@/hooks/useTimeRange'
import { useTrials } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { formatPercent, formatNumber } from '@/lib/formatters'
import type { TimeSeriesPoint } from '@/lib/types'

interface TrialsData {
  conversion_rate?: number
  started?: number
  converted?: number
  expired?: number
  series?: TimeSeriesPoint[]
}

export function TrialsReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })

  const { data, isLoading } = useTrials<TrialsData>({ start, end, interval })

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Trials</h2>

      <TimeRangePicker
        onSelectRange={(r) => setRange({ range: r })}
        onSelectInterval={(i) => setRange({ interval: i })}
        currentInterval={interval}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Conversion Rate"
          value={data?.conversion_rate != null ? formatPercent(data.conversion_rate) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Started"
          value={data?.started != null ? formatNumber(data.started) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Converted"
          value={data?.converted != null ? formatNumber(data.converted) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Expired"
          value={data?.expired != null ? formatNumber(data.expired) : '—'}
          loading={isLoading}
        />
      </div>

      <ChartContainer
        title="Trial Conversion Rate"
        chartConfig={{
          name: 'Trial Conversion Rate',
          metric: 'trials',
          endpoint: '/api/metrics/trials',
          params: { start, end, interval },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimeSeriesChart
          data={data?.series ?? []}
          dataKey="conversion_rate"
          formatter={formatPercent}
          color="#7c3aed"
          loading={isLoading}
        />
      </ChartContainer>
    </div>
  )
}
