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
import { formatCurrency, formatMonthYear } from '@/lib/formatters'
import type { WaterfallEntry } from '@/lib/types'

interface WaterfallChartProps {
  data: WaterfallEntry[]
  loading?: boolean
}

const COLORS = {
  new: '#2ecc71',
  expansion: '#3498db',
  reactivation: '#9b59b6',
  contraction: '#e67e22',
  churn: '#e74c3c',
  endingMrr: '#333333',
}

export function WaterfallChart({ data, loading }: WaterfallChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">No data</div>
  }

  const chartData = data.map((row) => ({
    month: formatMonthYear(row.month + '-01'),
    New: row.new / 100,
    Expansion: row.expansion / 100,
    Reactivation: row.reactivation / 100,
    Contraction: row.contraction / 100,
    Churn: row.churn / 100,
    'Ending MRR': row.ending_mrr / 100,
  }))

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 20 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="month" tick={{ fontSize: 12 }} />
        <YAxis width={80} tickFormatter={formatCurrency} tick={{ fontSize: 12 }} />
        <ReferenceLine y={0} stroke="#000" strokeWidth={0.5} />
        <Tooltip formatter={(v) => formatCurrency(Number(v))} />
        <Legend />
        <Bar dataKey="New" stackId="a" fill={COLORS.new} />
        <Bar dataKey="Expansion" stackId="a" fill={COLORS.expansion} />
        <Bar dataKey="Reactivation" stackId="a" fill={COLORS.reactivation} />
        <Bar dataKey="Contraction" stackId="a" fill={COLORS.contraction} />
        <Bar dataKey="Churn" stackId="a" fill={COLORS.churn} />
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
