import { BarChart } from '@tremor/react'
import { formatCurrency, formatMonthYear } from '@/lib/formatters'
import type { WaterfallEntry } from '@/lib/types'

interface WaterfallChartProps {
  data: WaterfallEntry[]
  loading?: boolean
}

export function WaterfallChart({ data, loading }: WaterfallChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">No data</div>
  }

  // Transform waterfall data into stacked bar format
  const chartData = data.map((row) => ({
    month: formatMonthYear(row.month),
    New: row.new,
    Expansion: row.expansion,
    Contraction: Math.abs(row.contraction),
    Churn: Math.abs(row.churn),
    Reactivation: row.reactivation,
  }))

  return (
    <BarChart
      data={chartData}
      index="month"
      categories={['New', 'Expansion', 'Reactivation', 'Contraction', 'Churn']}
      colors={['emerald', 'blue', 'violet', 'amber', 'red']}
      valueFormatter={formatCurrency}
      yAxisWidth={80}
      stack
      className="h-80"
      showAnimation
    />
  )
}
