import { Card } from '@tremor/react'

interface KPICardProps {
  title: string
  value: string
  subtitle?: string
  loading?: boolean
}

export function KPICard({ title, value, subtitle, loading }: KPICardProps) {
  return (
    <Card className="p-4">
      <p className="text-tremor-default text-tremor-content">{title}</p>
      <p className="mt-1 text-tremor-metric text-tremor-content-strong">
        {loading ? '—' : value}
      </p>
      {subtitle && (
        <p className="mt-0.5 text-tremor-default text-tremor-content">{subtitle}</p>
      )}
    </Card>
  )
}
