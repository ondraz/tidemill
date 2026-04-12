import { useState } from 'react'
import { useDashboards, useSaveChart } from '@/hooks/useDashboards'
import type { ChartConfig } from '@/lib/types'

interface AddToDashboardDialogProps {
  config: ChartConfig
  onClose: () => void
}

export function AddToDashboardDialog({ config, onClose }: AddToDashboardDialogProps) {
  const { data: dashboards, isLoading } = useDashboards()
  const [selectedDash, setSelectedDash] = useState('')
  const saveChart = useSaveChart()

  // First save the chart, then add to dashboard
  const handleAdd = async () => {
    if (!selectedDash) return
    const saved = await saveChart.mutateAsync({
      name: config.name || 'Untitled Chart',
      config,
    })
    // We need the dashboard detail to get a section id — use the first section
    // For simplicity, the add-to-dashboard flow creates a default section if needed
    const dashApi = await import('@/api/dashboards')
    const detail = await dashApi.getDashboard(selectedDash)
    let sectionId: string
    if (detail.sections.length > 0) {
      sectionId = detail.sections[0].id
    } else {
      const section = await dashApi.createSection(selectedDash, 'Charts', 0)
      sectionId = section.id
    }
    await dashApi.addChartToDashboard(selectedDash, saved.id, sectionId, 0)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-card rounded-lg shadow-lg p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-medium mb-3">Add to Dashboard</h3>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading dashboards...</p>
        ) : !dashboards || dashboards.length === 0 ? (
          <p className="text-sm text-muted-foreground">No dashboards yet. Create one first.</p>
        ) : (
          <select
            value={selectedDash}
            onChange={(e) => setSelectedDash(e.target.value)}
            className="w-full border border-border rounded-md px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Select a dashboard</option>
            {dashboards.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        )}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={!selectedDash || saveChart.isPending}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  )
}
