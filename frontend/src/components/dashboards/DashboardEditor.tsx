import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import {
  useDashboard,
  useCreateSection,
  useDeleteSection,
  useRemoveChartFromDashboard,
} from '@/hooks/useDashboards'
import { DynamicChart } from '@/components/dashboards/DynamicChart'

export function DashboardEditor() {
  const { id } = useParams<{ id: string }>()
  const { data: dashboard, isLoading } = useDashboard(id!)
  const createSection = useCreateSection(id!)
  const deleteSection = useDeleteSection(id!)
  const removeChart = useRemoveChartFromDashboard(id!)
  const [newSectionTitle, setNewSectionTitle] = useState('')

  if (isLoading) {
    return <div className="text-muted-foreground">Loading dashboard...</div>
  }

  if (!dashboard) {
    return <div className="text-muted-foreground">Dashboard not found</div>
  }

  const handleAddSection = () => {
    if (!newSectionTitle.trim()) return
    createSection.mutate(
      { title: newSectionTitle.trim(), position: dashboard.sections.length },
      { onSuccess: () => setNewSectionTitle('') },
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">{dashboard.name}</h2>
        {dashboard.description && (
          <p className="text-sm text-muted-foreground">{dashboard.description}</p>
        )}
      </div>

      {dashboard.sections.map((section) => (
        <div key={section.id} className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
              {section.title}
            </h3>
            <button
              onClick={() => {
                if (confirm('Delete this section and all its charts?')) {
                  deleteSection.mutate(section.id)
                }
              }}
              className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>

          {section.charts.length === 0 ? (
            <div className="border border-dashed border-border rounded-lg p-8 text-center text-sm text-muted-foreground">
              No charts in this section. Save a chart from Reports and add it here.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {section.charts.map((entry) => (
                <div key={entry.id} className="bg-card border border-border rounded-lg">
                  <div className="flex items-center justify-between px-4 py-2 border-b border-border">
                    <span className="text-sm font-medium">{entry.chart.name}</span>
                    <button
                      onClick={() => removeChart.mutate(entry.id)}
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="p-4">
                    <DynamicChart config={entry.chart.config} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={newSectionTitle}
          onChange={(e) => setNewSectionTitle(e.target.value)}
          placeholder="New section title"
          className="border border-border rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          onKeyDown={(e) => e.key === 'Enter' && handleAddSection()}
        />
        <button
          onClick={handleAddSection}
          disabled={!newSectionTitle.trim()}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" /> Add Section
        </button>
      </div>
    </div>
  )
}
