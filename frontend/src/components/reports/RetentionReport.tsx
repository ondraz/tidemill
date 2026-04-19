import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { useTimeRange } from '@/hooks/useTimeRange'
import { useRetention } from '@/hooks/useMetrics'
import { fetchRetention } from '@/api/metrics'
import { KPICard } from '@/components/charts/KPICard'
import { CohortHeatmap } from '@/components/charts/CohortHeatmap'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { formatPercent, formatPeriod } from '@/lib/formatters'
import { periodStarts, periodEnd } from '@/lib/periods'
import type { CohortEntry, Interval } from '@/lib/types'

interface RawCohortRow {
  cohort_month: string
  active_month: string
  cohort_size: number
  active_count: number
}

function monthDiff(from: string, to: string): number {
  const a = new Date(from)
  const b = new Date(to)
  return (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth())
}

// NRR / GRR divide by "MRR at period start". A wide selection that reaches
// before the first customer existed collapses the denominator to zero and
// the KPI becomes unavailable. Fall back to the most recent full period so
// the KPIs stay meaningful as the user widens the timeline.
function rateWindow(
  start: string,
  end: string,
  interval: Interval,
): { rateStart: string; rateEnd: string } {
  const periods = periodStarts(start, end, interval)
  if (periods.length === 0) return { rateStart: start, rateEnd: end }
  const rateStart = periods[periods.length - 1]
  return { rateStart, rateEnd: periodEnd(rateStart, interval) }
}

export function RetentionReport() {
  const { start, end, interval } = useTimeRange({ range: 'last_1y' })
  const { rateStart, rateEnd } = useMemo(
    () => rateWindow(start, end, interval),
    [start, end, interval],
  )

  const { data: cohortRaw, isLoading: cohortLoading } = useRetention<RawCohortRow[]>({ start, end })
  const { data: nrr, isLoading: nrrLoading } = useRetention<number | null>({
    start: rateStart, end: rateEnd, query_type: 'nrr',
  })
  const { data: grr, isLoading: grrLoading } = useRetention<number | null>({
    start: rateStart, end: rateEnd, query_type: 'grr',
  })

  const cohortEntries: CohortEntry[] = Array.isArray(cohortRaw)
    ? cohortRaw.map((row) => ({
        cohort_month: row.cohort_month,
        active_month: row.active_month,
        retention_rate: row.cohort_size > 0 ? row.active_count / row.cohort_size : 0,
        months_since: monthDiff(row.cohort_month, row.active_month),
      }))
    : []

  // NRR/GRR timeline — one closed-closed [period-start, period-end] query
  // per period. The interval selector drives the bucket size
  // (week/month/quarter/year).
  const periods = useMemo(() => periodStarts(start, end, interval), [start, end, interval])
  const retQueries = useQueries({
    queries: periods.flatMap((p) => {
      const pEnd = periodEnd(p, interval)
      return [
        {
          queryKey: ['metrics', 'retention', { start: p, end: pEnd, query_type: 'nrr' }],
          queryFn: () => fetchRetention<number | null>({ start: p, end: pEnd, query_type: 'nrr' }),
          staleTime: 60_000,
        },
        {
          queryKey: ['metrics', 'retention', { start: p, end: pEnd, query_type: 'grr' }],
          queryFn: () => fetchRetention<number | null>({ start: p, end: pEnd, query_type: 'grr' }),
          staleTime: 60_000,
        },
      ]
    }),
  })

  const timelineLoading = retQueries.some((q) => q.isLoading)
  const timelineData = periods.map((p, i) => ({
    date: formatPeriod(p, interval),
    NRR: ((retQueries[i * 2]?.data as number | null | undefined) ?? 0) * 100,
    GRR: ((retQueries[i * 2 + 1]?.data as number | null | undefined) ?? 0) * 100,
  }))

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Retention</h2>

      <div className="text-xs text-muted-foreground">
        Rates measured over {formatPeriod(rateStart, interval)} ({rateStart} → {rateEnd}).
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Net Revenue Retention"
          value={nrr != null ? formatPercent(nrr) : '—'}
          subtitle={nrr == null ? 'no MRR at period start' : undefined}
          loading={nrrLoading}
        />
        <KPICard
          title="Gross Revenue Retention"
          value={grr != null ? formatPercent(grr) : '—'}
          subtitle={grr == null ? 'no MRR at period start' : undefined}
          loading={grrLoading}
        />
      </div>

      <ChartContainer
        title="Revenue Retention"
        chartConfig={{
          name: 'Revenue Retention',
          metric: 'retention',
          endpoint: '/api/metrics/retention',
          params: { start, end, interval },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <BarBreakdownChart
          data={timelineData}
          bars={['NRR', 'GRR']}
          formatter={(v) => `${v.toFixed(0)}%`}
          loading={timelineLoading}
        />
      </ChartContainer>

      <ChartContainer
        title="Cohort Retention"
        chartConfig={{
          name: 'Cohort Retention',
          metric: 'retention',
          endpoint: '/api/metrics/retention',
          params: { start, end },
          chartType: 'cohort_heatmap',
          timeRangeMode: 'fixed',
        }}
      >
        <CohortHeatmap data={cohortEntries} loading={cohortLoading} />
      </ChartContainer>
    </div>
  )
}
