import type { CohortEntry } from '@/lib/types'
import { formatMonthYear, formatPercent } from '@/lib/formatters'

interface CohortHeatmapProps {
  data: CohortEntry[]
  loading?: boolean
}

function getColor(rate: number): string {
  if (rate >= 0.9) return '#dcfce7'
  if (rate >= 0.7) return '#bbf7d0'
  if (rate >= 0.5) return '#fef08a'
  if (rate >= 0.3) return '#fed7aa'
  return '#fecaca'
}

export function CohortHeatmap({ data, loading }: CohortHeatmapProps) {
  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Loading...</div>
  }
  if (!data || data.length === 0) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">No data</div>
  }

  // Group by cohort_month
  const cohorts = new Map<string, CohortEntry[]>()
  for (const entry of data) {
    const list = cohorts.get(entry.cohort_month) ?? []
    list.push(entry)
    cohorts.set(entry.cohort_month, list)
  }

  const maxMonths = Math.max(...data.map((d) => d.months_since))
  const cohortKeys = [...cohorts.keys()].sort()

  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left font-medium text-muted-foreground">Cohort</th>
            {Array.from({ length: maxMonths + 1 }, (_, i) => (
              <th key={i} className="px-2 py-1 text-center font-medium text-muted-foreground">
                M{i}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohortKeys.map((cohort) => {
            const entries = cohorts.get(cohort) ?? []
            const byMonth = new Map(entries.map((e) => [e.months_since, e]))
            return (
              <tr key={cohort}>
                <td className="px-2 py-1 font-medium whitespace-nowrap">
                  {formatMonthYear(cohort)}
                </td>
                {Array.from({ length: maxMonths + 1 }, (_, i) => {
                  const entry = byMonth.get(i)
                  if (!entry) {
                    return <td key={i} className="px-2 py-1" />
                  }
                  return (
                    <td
                      key={i}
                      className="px-2 py-1 text-center"
                      style={{ backgroundColor: getColor(entry.retention_rate) }}
                    >
                      {formatPercent(entry.retention_rate)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
