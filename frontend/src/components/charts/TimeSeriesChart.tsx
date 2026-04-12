import { LineChart } from '@tremor/react'

interface TimeSeriesChartProps {
  data: Array<Record<string, unknown>>
  dataKey: string
  xKey?: string
  formatter?: (v: number) => string
  color?: string
  loading?: boolean
}

const COLOR_MAP: Record<string, string> = {
  '#2563eb': 'blue',
  '#dc2626': 'red',
  '#d97706': 'amber',
  '#059669': 'emerald',
  '#7c3aed': 'violet',
}

export function TimeSeriesChart({
  data,
  dataKey,
  xKey = 'date',
  formatter,
  color = '#2563eb',
  loading,
}: TimeSeriesChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-tremor-content">No data</div>
  }

  const tremorColor = COLOR_MAP[color] ?? 'blue'

  return (
    <LineChart
      data={data}
      index={xKey}
      categories={[dataKey]}
      colors={[tremorColor]}
      valueFormatter={formatter}
      yAxisWidth={80}
      className="h-72"
      showAnimation
    />
  )
}
