import { useTimeRange } from '@/hooks/useTimeRange'
import { useRetention } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { CohortHeatmap } from '@/components/charts/CohortHeatmap'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { TimeRangePicker } from '@/components/controls/TimeRangePicker'
import { formatPercent } from '@/lib/formatters'
import type { CohortEntry } from '@/lib/types'

interface RetentionSummary {
  nrr?: number
  grr?: number
  cohorts?: CohortEntry[]
}

export function RetentionReport() {
  const { start, end, interval, setRange } = useTimeRange({ range: 'last_1y' })

  const { data, isLoading } = useRetention<RetentionSummary>({ start, end, interval })

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Retention</h2>

      <TimeRangePicker
        onSelectRange={(r) => setRange({ range: r })}
        onSelectInterval={(i) => setRange({ interval: i })}
        currentInterval={interval}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Net Revenue Retention"
          value={data?.nrr != null ? formatPercent(data.nrr) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Gross Revenue Retention"
          value={data?.grr != null ? formatPercent(data.grr) : '—'}
          loading={isLoading}
        />
      </div>

      <ChartContainer
        title="Cohort Retention"
        chartConfig={{
          name: 'Cohort Retention',
          metric: 'retention',
          endpoint: '/api/metrics/retention',
          params: { start, end, interval },
          chartType: 'cohort_heatmap',
          timeRangeMode: 'fixed',
        }}
      >
        <CohortHeatmap data={data?.cohorts ?? []} loading={isLoading} />
      </ChartContainer>
    </div>
  )
}
