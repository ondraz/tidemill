import { useState } from 'react'
import { useSaveChart } from '@/hooks/useDashboards'
import type { ChartConfig } from '@/lib/types'

interface SaveChartDialogProps {
  config: ChartConfig
  onClose: () => void
}

export function SaveChartDialog({ config, onClose }: SaveChartDialogProps) {
  const [name, setName] = useState(config.name || '')
  const save = useSaveChart()

  const handleSave = () => {
    if (!name.trim()) return
    save.mutate(
      { name: name.trim(), config },
      { onSuccess: () => onClose() },
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-card rounded-lg shadow-lg p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-medium mb-3">Save Chart</h3>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Chart name"
          className="w-full border border-border rounded-md px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ring"
          autoFocus
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim() || save.isPending}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {save.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
