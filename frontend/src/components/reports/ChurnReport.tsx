import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { useTimeRange } from '@/hooks/useTimeRange'
import {
  useChurn,
  useChurnCustomers,
  useChurnRevenueEvents,
  useMRRWaterfall,
} from '@/hooks/useMetrics'
import { fetchChurn } from '@/api/metrics'
import { KPICard } from '@/components/charts/KPICard'
import { BarBreakdownChart } from '@/components/charts/BarBreakdownChart'
import { ChartContainer } from '@/components/charts/ChartContainer'
import { formatCurrency, formatPercent, formatPeriod } from '@/lib/formatters'
import { periodStarts, periodEnd } from '@/lib/periods'
import { COLORS } from '@/lib/colors'
import type {
  ChurnCustomerDetail,
  ChurnRevenueEvent,
  Interval,
  WaterfallEntry,
} from '@/lib/types'

// Churn rates are meaningful per-period: they need customers active at
// period start, so a wide window collapses the denominator. Pick the last
// period inside [start, end] as the rate window and report it closed-closed.
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

export function ChurnReport() {
  const { start, end, interval } = useTimeRange({ range: 'last_1y' })
  const { rateStart, rateEnd } = useMemo(
    () => rateWindow(start, end, interval),
    [start, end, interval],
  )

  const { data: logoRate, isLoading: logoRateLoading } = useChurn<number | null>({
    start: rateStart, end: rateEnd, type: 'logo',
  })
  const { data: revRate, isLoading: revRateLoading } = useChurn<number | null>({
    start: rateStart, end: rateEnd, type: 'revenue',
  })

  const { data: detail, isLoading: detailLoading } =
    useChurnCustomers<ChurnCustomerDetail[]>({ start: rateStart, end: rateEnd })
  const { data: revEvents } =
    useChurnRevenueEvents<ChurnRevenueEvent[]>({ start: rateStart, end: rateEnd })
  const { data: waterfall, isLoading: waterfallLoading } =
    useMRRWaterfall<WaterfallEntry[]>({ start, end, interval })

  // Churn timeline — one API call per period for both logo + revenue,
  // each queried closed-closed [period-start, period-end]. The interval
  // selector drives the bucket size (week/month/quarter/year).
  const periods = useMemo(() => periodStarts(start, end, interval), [start, end, interval])
  const timelineQueries = useQueries({
    queries: periods.flatMap((p) => {
      const pEnd = periodEnd(p, interval)
      return [
        {
          queryKey: ['metrics', 'churn', { start: p, end: pEnd, type: 'logo' }],
          queryFn: () => fetchChurn<number | null>({ start: p, end: pEnd, type: 'logo' }),
          staleTime: 60_000,
        },
        {
          queryKey: ['metrics', 'churn', { start: p, end: pEnd, type: 'revenue' }],
          queryFn: () => fetchChurn<number | null>({ start: p, end: pEnd, type: 'revenue' }),
          staleTime: 60_000,
        },
      ]
    }),
  })

  const timelineLoading = timelineQueries.some((q) => q.isLoading)
  const timelineData = periods.map((p, i) => ({
    date: formatPeriod(p, interval),
    logo: (timelineQueries[i * 2]?.data as number | null | undefined) ?? null,
    revenue: (timelineQueries[i * 2 + 1]?.data as number | null | undefined) ?? null,
  }))

  // Lost MRR per period — derived from waterfall churn column (cents → dollars, abs).
  const lostMrrData = (waterfall ?? []).map((row) => ({
    date: formatPeriod(String(row.period).slice(0, 10), interval),
    'Lost MRR': Math.abs(row.churn) / 100,
  }))

  // Snapshot numerator / denominator context
  const snapshot = useMemo(() => {
    if (!detail) return null
    const startingMrrCents = detail.reduce((s, r) => s + r.starting_mrr_cents, 0)
    const churnedMrrCents = detail.reduce((s, r) => s + r.churned_mrr_cents, 0)
    const churned = detail.filter((r) => r.fully_churned)
    return {
      cStart: detail.length,
      cChurned: churned.length,
      startingMrr: startingMrrCents / 100,
      churnedMrr: churnedMrrCents / 100,
    }
  }, [detail])

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Churn</h2>

      <div className="text-xs text-muted-foreground">
        Rates measured over {formatPeriod(rateStart, interval)} ({rateStart} → {rateEnd}).
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Logo Churn Rate"
          value={logoRate != null ? formatPercent(logoRate) : '—'}
          subtitle={
            snapshot && snapshot.cStart > 0
              ? `${snapshot.cChurned} / ${snapshot.cStart} customers`
              : 'no customers active at start'
          }
          loading={logoRateLoading || detailLoading}
        />
        <KPICard
          title="Revenue Churn Rate"
          value={revRate != null ? formatPercent(revRate) : '—'}
          subtitle={
            snapshot && snapshot.startingMrr > 0
              ? `${formatCurrency(snapshot.churnedMrr)} / ${formatCurrency(snapshot.startingMrr)}`
              : 'no MRR at start'
          }
          loading={revRateLoading || detailLoading}
        />
      </div>

      <ChartContainer
        title="Churn Rate"
        chartConfig={{
          name: 'Churn Rate',
          metric: 'churn',
          endpoint: '/api/metrics/churn',
          params: { start, end, interval },
          chartType: 'line',
          timeRangeMode: 'fixed',
        }}
      >
        <TimelineChurnChart data={timelineData} loading={timelineLoading} />
      </ChartContainer>

      <ChartContainer
        title="Lost MRR"
        chartConfig={{
          name: 'Lost MRR',
          metric: 'churn',
          endpoint: '/api/metrics/mrr/waterfall',
          params: { start, end, interval },
          chartType: 'bar',
          timeRangeMode: 'fixed',
        }}
      >
        <BarBreakdownChart
          data={lostMrrData}
          bars={['Lost MRR']}
          formatter={formatCurrency}
          loading={waterfallLoading}
        />
      </ChartContainer>

      <ChartContainer title="Customer Detail (active at start)">
        <CustomerDetailTable detail={detail ?? []} loading={detailLoading} />
      </ChartContainer>

      {revEvents && revEvents.length > 0 && (
        <ChartContainer title="Revenue Churn Events">
          <RevenueEventsTable events={revEvents} />
        </ChartContainer>
      )}
    </div>
  )
}

function TimelineChurnChart({
  data,
  loading,
}: {
  data: Array<{ date: string; logo: number | null; revenue: number | null }>
  loading: boolean
}) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">No data</div>
  }
  return (
    <BarBreakdownChart
      data={data.map((r) => ({
        date: r.date,
        Logo: r.logo != null ? r.logo * 100 : 0,
        Revenue: r.revenue != null ? r.revenue * 100 : 0,
      }))}
      bars={['Logo', 'Revenue']}
      formatter={(v) => `${v.toFixed(1)}%`}
    />
  )
}

function CustomerDetailTable({
  detail,
  loading,
}: {
  detail: ChurnCustomerDetail[]
  loading: boolean
}) {
  if (loading) {
    return <div className="h-32 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (detail.length === 0) {
    return <div className="h-32 flex items-center justify-center text-muted-foreground">No data</div>
  }
  const sorted = [...detail].sort(
    (a, b) => b.starting_mrr_cents - a.starting_mrr_cents,
  )
  const totalStart = detail.reduce((s, r) => s + r.starting_mrr_cents, 0)
  const totalChurned = detail.reduce((s, r) => s + r.churned_mrr_cents, 0)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border">
            <th className="py-1 pr-4 font-medium">Customer</th>
            <th className="py-1 pr-4 font-medium text-right">Starting MRR</th>
            <th className="py-1 pr-4 font-medium text-right">Churned MRR</th>
            <th className="py-1 pr-4 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.customer_id}
              className="border-b border-border/50"
              style={
                r.churned_mrr_cents > 0
                  ? { backgroundColor: 'rgba(234, 179, 8, 0.08)' }
                  : undefined
              }
            >
              <td className="py-1 pr-4">
                {r.customer_name || r.customer_id}
              </td>
              <td className="py-1 pr-4 text-right">
                {formatCurrency(r.starting_mrr_cents / 100)}
              </td>
              <td className="py-1 pr-4 text-right">
                {r.churned_mrr_cents > 0
                  ? formatCurrency(r.churned_mrr_cents / 100)
                  : '—'}
              </td>
              <td className="py-1 pr-4" style={r.fully_churned ? { color: COLORS.churn } : undefined}>
                {r.fully_churned ? 'Fully churned' : 'Active'}
              </td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="py-1 pr-4">TOTAL ({detail.length})</td>
            <td className="py-1 pr-4 text-right">{formatCurrency(totalStart / 100)}</td>
            <td className="py-1 pr-4 text-right">{formatCurrency(totalChurned / 100)}</td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function RevenueEventsTable({ events }: { events: ChurnRevenueEvent[] }) {
  const sorted = [...events].sort((a, b) => b.mrr_cents - a.mrr_cents)
  const total = events.reduce((s, r) => s + r.mrr_cents, 0)
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border">
            <th className="py-1 pr-4 font-medium">Customer</th>
            <th className="py-1 pr-4 font-medium text-right">Lost MRR</th>
            <th className="py-1 pr-4 font-medium text-right">Events</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.customer_id} className="border-b border-border/50">
              <td className="py-1 pr-4">{r.customer_name || r.customer_id}</td>
              <td className="py-1 pr-4 text-right">{formatCurrency(r.mrr_cents / 100)}</td>
              <td className="py-1 pr-4 text-right">{r.events}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="py-1 pr-4">TOTAL</td>
            <td className="py-1 pr-4 text-right">{formatCurrency(total / 100)}</td>
            <td className="py-1 pr-4 text-right">
              {events.reduce((s, r) => s + r.events, 0)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
