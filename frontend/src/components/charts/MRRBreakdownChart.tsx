import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
} from 'recharts'
import { formatCurrency } from '@/lib/formatters'

const COLOR_MAP: Record<string, string> = {
  New: '#2ecc71',
  Expansion: '#3498db',
  Reactivation: '#9b59b6',
  Contraction: '#e67e22',
  Churn: '#e74c3c',
}

interface MRRBreakdownChartProps {
  data: Array<{ type: string; Amount: number }>
  loading?: boolean
}

export function MRRBreakdownChart({ data, loading }: MRRBreakdownChartProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">No data</div>
  }

  return (
    <ResponsiveContainer width="100%" height={288}>
      <BarChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 20 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
        <XAxis dataKey="type" tick={{ fontSize: 12 }} />
        <YAxis width={80} tickFormatter={formatCurrency} tick={{ fontSize: 12 }} />
        <ReferenceLine y={0} stroke="#000" strokeWidth={0.5} />
        <Tooltip formatter={(v) => formatCurrency(Number(v))} />
        <Bar dataKey="Amount">
          {data.map((entry) => (
            <Cell key={entry.type} fill={COLOR_MAP[entry.type] ?? '#94a3b8'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
