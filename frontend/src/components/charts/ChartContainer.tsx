import { type ReactNode, useState } from 'react'
import { Bookmark, LayoutDashboard } from 'lucide-react'
import { SaveChartDialog } from '@/components/charts/SaveChartDialog'
import { AddToDashboardDialog } from '@/components/charts/AddToDashboardDialog'
import type { ChartConfig } from '@/lib/types'

interface ChartContainerProps {
  title: string
  children: ReactNode
  chartConfig?: ChartConfig
}

export function ChartContainer({ title, children, chartConfig }: ChartContainerProps) {
  const [showSave, setShowSave] = useState(false)
  const [showAddDash, setShowAddDash] = useState(false)

  return (
    <div className="bg-card border border-border rounded-lg">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 className="text-sm font-medium">{title}</h3>
        {chartConfig && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowSave(true)}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
              title="Save chart"
            >
              <Bookmark className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setShowAddDash(true)}
              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
              title="Add to dashboard"
            >
              <LayoutDashboard className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
      <div className="p-4">{children}</div>
      {showSave && chartConfig && (
        <SaveChartDialog config={chartConfig} onClose={() => setShowSave(false)} />
      )}
      {showAddDash && chartConfig && (
        <AddToDashboardDialog config={chartConfig} onClose={() => setShowAddDash(false)} />
      )}
    </div>
  )
}
