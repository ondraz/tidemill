import { useSummary } from '@/hooks/useMetrics'
import { KPICard } from '@/components/charts/KPICard'
import { formatCurrency, formatPercent, formatNumber } from '@/lib/formatters'

interface SummaryData {
  mrr?: number
  arr?: number
  active_customers?: number
  logo_churn_rate?: number
  revenue_churn_rate?: number
  nrr?: number
  trial_conversion_rate?: number
  ltv?: number
  arpu?: number
  quick_ratio?: number
}

export function SummaryReport() {
  const { data, isLoading } = useSummary<SummaryData>()

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Overview</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <KPICard
          title="MRR"
          value={data?.mrr != null ? formatCurrency(data.mrr / 100) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="ARR"
          value={data?.arr != null ? formatCurrency(data.arr / 100) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Active Customers"
          value={data?.active_customers != null ? formatNumber(data.active_customers) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Logo Churn"
          value={data?.logo_churn_rate != null ? formatPercent(data.logo_churn_rate) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Revenue Churn"
          value={data?.revenue_churn_rate != null ? formatPercent(data.revenue_churn_rate) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="NRR"
          value={data?.nrr != null ? formatPercent(data.nrr) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="LTV"
          value={data?.ltv != null ? formatCurrency(data.ltv / 100) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="ARPU"
          value={data?.arpu != null ? formatCurrency(data.arpu / 100) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Quick Ratio"
          value={data?.quick_ratio != null ? data.quick_ratio.toFixed(1) : '—'}
          loading={isLoading}
        />
        <KPICard
          title="Trial Conversion"
          value={data?.trial_conversion_rate != null ? formatPercent(data.trial_conversion_rate) : '—'}
          loading={isLoading}
        />
      </div>
    </div>
  )
}
