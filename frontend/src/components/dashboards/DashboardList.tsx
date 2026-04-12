import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { useDashboards, useCreateDashboard, useDeleteDashboard } from '@/hooks/useDashboards'

export function DashboardList() {
  const { data: dashboards, isLoading } = useDashboards()
  const create = useCreateDashboard()
  const remove = useDeleteDashboard()
  const [newName, setNewName] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const handleCreate = () => {
    if (!newName.trim()) return
    create.mutate({ name: newName.trim() }, {
      onSuccess: () => {
        setNewName('')
        setShowCreate(false)
      },
    })
  }

  if (isLoading) {
    return <div className="text-muted-foreground">Loading dashboards...</div>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Dashboards</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="w-3.5 h-3.5" /> New Dashboard
        </button>
      </div>

      {showCreate && (
        <div className="bg-card border border-border rounded-lg p-4 mb-4">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Dashboard name"
            className="w-full border border-border rounded-md px-3 py-2 text-sm mb-2 focus:outline-none focus:ring-2 focus:ring-ring"
            autoFocus
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          />
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!newName.trim() || create.isPending}
              className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Create
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!dashboards || dashboards.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <p>No dashboards yet.</p>
          <p className="text-sm mt-1">Create one to start organizing your charts.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {dashboards.map((d) => (
            <div key={d.id} className="bg-card border border-border rounded-lg p-4 hover:border-primary/50 transition-colors">
              <div className="flex items-start justify-between">
                <Link to={`/dashboards/${d.id}`} className="flex-1">
                  <h3 className="text-sm font-medium hover:text-primary">{d.name}</h3>
                  {d.description && (
                    <p className="text-xs text-muted-foreground mt-0.5">{d.description}</p>
                  )}
                </Link>
                <button
                  onClick={() => {
                    if (confirm('Delete this dashboard?')) {
                      remove.mutate(d.id)
                    }
                  }}
                  className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
