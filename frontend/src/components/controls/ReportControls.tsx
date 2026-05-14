import { useState } from 'react'
import { Filter, Plus, X } from 'lucide-react'
import { useSegments } from '@/hooks/useSegments'
import { DIMENSIONS_BY_METRIC } from '@/lib/constants'
import type { MetricName } from '@/lib/types'

interface ReportControlsProps {
  metric: MetricName
  dimensions: string[]
  onDimensionsChange: (dims: string[]) => void
  segment: string | null
  onSegmentChange: (id: string | null) => void
  compareSegments: string[]
  onCompareSegmentsChange: (ids: string[]) => void
  filters?: Record<string, string>
  onFiltersChange?: (filters: Record<string, string>) => void
  // Group by selection mode. Most charts pivot on a single dim so 'single'
  // is the default — multi-select only makes sense for raw tables.
  groupByMode?: 'single' | 'multi'
  // Hide individual sections if the metric / chart doesn't support them.
  show?: { dimensions?: boolean; segment?: boolean; compare?: boolean; filters?: boolean }
}

const MAX_COMPARE = 10

// One control bar shared across every report. Keeps the affordances
// consistent (chip toggles, segment dropdown, ad-hoc filters) so users get
// the same surface for Group by / Segment / Compare / Filters everywhere
// rather than learning a different layout per metric.
export function ReportControls({
  metric,
  dimensions,
  onDimensionsChange,
  segment,
  onSegmentChange,
  compareSegments,
  onCompareSegmentsChange,
  filters = {},
  onFiltersChange,
  groupByMode = 'single',
  show,
}: ReportControlsProps) {
  const { data: segments } = useSegments()
  const segList = segments ?? []
  const available = DIMENSIONS_BY_METRIC[metric] ?? []
  const showDimensions = show?.dimensions !== false && available.length > 0
  const showSegment = show?.segment !== false
  const showCompare = show?.compare !== false
  const showFilters = show?.filters !== false && onFiltersChange != null

  const toggleDim = (dim: string) => {
    if (dimensions.includes(dim)) {
      onDimensionsChange(dimensions.filter((d) => d !== dim))
    } else if (groupByMode === 'single') {
      onDimensionsChange([dim])
    } else {
      onDimensionsChange([...dimensions, dim])
    }
  }

  const toggleCompare = (id: string) => {
    if (compareSegments.includes(id)) {
      onCompareSegmentsChange(compareSegments.filter((s) => s !== id))
    } else if (compareSegments.length < MAX_COMPARE) {
      onCompareSegmentsChange([...compareSegments, id])
    }
  }

  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 space-y-2">
      {showDimensions && (
        <ControlRow label="Group by">
          <button
            onClick={() => onDimensionsChange([])}
            className={chipCls(dimensions.length === 0)}
          >
            None
          </button>
          {available.map((dim) => (
            <button
              key={dim}
              onClick={() => toggleDim(dim)}
              className={chipCls(dimensions.includes(dim))}
            >
              {humanize(dim)}
            </button>
          ))}
        </ControlRow>
      )}

      {(showSegment || showCompare) && (
        <ControlRow label="Segments">
          {showSegment && (
            <select
              value={segment ?? ''}
              onChange={(e) => onSegmentChange(e.target.value || null)}
              className="text-xs px-2 py-0.5 border border-border rounded bg-background"
              title="Universe filter — narrow every chart to this segment"
            >
              <option value="">All customers</option>
              {segList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
          {showCompare && segList.length > 0 && (
            <>
              <span className="text-xs text-muted-foreground ml-2">vs</span>
              {segList.map((s) => {
                const active = compareSegments.includes(s.id)
                const atCap = !active && compareSegments.length >= MAX_COMPARE
                return (
                  <button
                    key={s.id}
                    onClick={() => toggleCompare(s.id)}
                    disabled={atCap}
                    className={chipCls(active)}
                    title={
                      atCap
                        ? `Compare is capped at ${MAX_COMPARE} segments`
                        : undefined
                    }
                  >
                    {s.name}
                  </button>
                )
              })}
              {compareSegments.length > 0 && (
                <button
                  onClick={() => onCompareSegmentsChange([])}
                  className="text-xs text-muted-foreground hover:text-foreground ml-1"
                >
                  Clear
                </button>
              )}
            </>
          )}
        </ControlRow>
      )}

      {showFilters && onFiltersChange && (
        <FiltersRow filters={filters} onChange={onFiltersChange} available={available} />
      )}
    </div>
  )
}

function ControlRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-xs font-medium text-muted-foreground min-w-[64px]">
        {label}
      </span>
      {children}
    </div>
  )
}

function chipCls(active: boolean): string {
  return `px-2 py-0.5 text-xs rounded-full border transition-colors ${
    active
      ? 'bg-primary/10 border-primary text-primary'
      : 'border-border text-muted-foreground hover:border-primary/50'
  } disabled:opacity-30`
}

function humanize(s: string): string {
  return s.replace(/_/g, ' ')
}

function FiltersRow({
  filters,
  onChange,
  available,
}: {
  filters: Record<string, string>
  onChange: (next: Record<string, string>) => void
  available: string[]
}) {
  const [adding, setAdding] = useState(false)
  const [newKey, setNewKey] = useState(available[0] ?? '')
  const [newVal, setNewVal] = useState('')
  const entries = Object.entries(filters)

  const removeEntry = (k: string) => {
    const next = { ...filters }
    delete next[k]
    onChange(next)
  }

  const submitNew = () => {
    if (!newKey.trim() || !newVal.trim()) return
    onChange({ ...filters, [newKey.trim()]: newVal.trim() })
    setNewKey(available[0] ?? '')
    setNewVal('')
    setAdding(false)
  }

  return (
    <ControlRow label="Filters">
      {entries.length === 0 && !adding && (
        <span className="text-xs text-muted-foreground/70">None</span>
      )}
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-accent text-foreground"
        >
          {humanize(k)} = {v}
          <button
            onClick={() => removeEntry(k)}
            className="ml-0.5 text-muted-foreground hover:text-destructive"
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      {adding ? (
        <span className="inline-flex items-center gap-1">
          <select
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="text-xs px-1.5 py-0.5 border border-border rounded bg-background"
          >
            {available.map((d) => (
              <option key={d} value={d}>
                {humanize(d)}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted-foreground">=</span>
          <input
            value={newVal}
            autoFocus
            onChange={(e) => setNewVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitNew()
              if (e.key === 'Escape') setAdding(false)
            }}
            placeholder="value"
            className="text-xs px-1.5 py-0.5 border border-border rounded bg-background w-32"
          />
          <button
            onClick={submitNew}
            disabled={!newKey.trim() || !newVal.trim()}
            className="text-xs text-primary hover:underline disabled:opacity-30"
          >
            Add
          </button>
          <button
            onClick={() => setAdding(false)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <Plus className="w-3 h-3" /> Add filter
        </button>
      )}
      {entries.length > 0 && (
        <Filter className="w-3 h-3 text-muted-foreground ml-1 opacity-40" />
      )}
    </ControlRow>
  )
}
