import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts'
import { formatCurrency, formatPeriod } from '@/lib/formatters'
import { COLORS } from '@/lib/colors'
import type { Interval, WaterfallEntry } from '@/lib/types'

interface WaterfallChartProps {
  data: WaterfallEntry[]
  interval?: Interval
  loading?: boolean
}

const BAR_SIZE = 40

export function WaterfallChart({ data, interval = 'month', loading }: WaterfallChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">No data</div>
  }

  const chartData = data.map((row) => ({
    period: formatPeriod(String(row.period).slice(0, 10), interval),
    'Starting MRR': row.starting_mrr / 100,
    New: row.new / 100,
    Expansion: row.expansion / 100,
    Reactivation: row.reactivation / 100,
    Contraction: row.contraction / 100,
    Churn: row.churn / 100,
    'Ending MRR': row.ending_mrr / 100,
  }))

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart
        data={chartData}
        barSize={BAR_SIZE}
        barGap={-BAR_SIZE}
        margin={{ top: 5, right: 20, bottom: 5, left: 20 }}
      >
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="period" tick={{ fontSize: 12 }} />
        <YAxis width={80} tickFormatter={formatCurrency} tick={{ fontSize: 12 }} />
        <ReferenceLine y={0} stroke="#000" strokeWidth={0.5} />
        <Tooltip formatter={(v) => formatCurrency(Number(v))} />
        <Legend />
        <Bar dataKey="Starting MRR" stackId="pos" fill={COLORS.startingMrr} />
        <Bar dataKey="New" stackId="pos" fill={COLORS.new} />
        <Bar dataKey="Expansion" stackId="pos" fill={COLORS.expansion} />
        <Bar dataKey="Reactivation" stackId="pos" fill={COLORS.reactivation} />
        <Bar dataKey="Contraction" stackId="neg" fill={COLORS.contraction} />
        <Bar dataKey="Churn" stackId="neg" fill={COLORS.churn} />
        <Line
          type="monotone"
          dataKey="Ending MRR"
          stroke={COLORS.endingMrr}
          strokeWidth={2}
          dot={{ r: 5, fill: COLORS.endingMrr }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
