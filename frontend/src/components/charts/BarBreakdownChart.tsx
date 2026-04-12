import { BarChart } from '@tremor/react'

const TREMOR_COLORS = ['blue', 'violet', 'emerald', 'amber', 'red', 'cyan', 'pink']

interface BarBreakdownChartProps {
  data: Array<Record<string, unknown>>
  bars: string[]
  xKey?: string
  formatter?: (v: number) => string
  loading?: boolean
  stacked?: boolean
}

export function BarBreakdownChart({
  data,
  bars,
  xKey = 'date',
  formatter,
  loading,
  stacked,
}: BarBreakdownChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">No data</div>
  }

  return (
    <BarChart
      data={data}
      index={xKey}
      categories={bars}
      colors={bars.map((_, i) => TREMOR_COLORS[i % TREMOR_COLORS.length])}
      valueFormatter={formatter}
      yAxisWidth={80}
      stack={stacked}
      className="h-72"
      showAnimation
    />
  )
}
