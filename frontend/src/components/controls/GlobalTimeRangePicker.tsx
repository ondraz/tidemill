import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Calendar, X } from 'lucide-react'
import { useTimeRange } from '@/hooks/useTimeRange'
import { RELATIVE_RANGES } from '@/lib/constants'
import type { Interval, RelativeRange } from '@/lib/types'

// ── helpers ─────────────────────────────────────────────────────────

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function fmt(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function parseIso(s: string): Date {
  // Parse as local date (not UTC) so month math lines up with the picker.
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d)
  out.setDate(out.getDate() + n)
  return out
}

function monthLabel(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short' })
}

function monthYearLabel(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

function yearsBetween(firstYear: number, lastYear: number): number[] {
  const out: number[] = []
  for (let y = firstYear; y <= lastYear; y += 1) out.push(y)
  return out
}

type Grain = 'week' | 'month' | 'quarter' | 'year'

// Cells carry the *inclusive* last day of the period — matching Tidemill's
// closed-closed `[start, end]` convention (see docs/definitions.md). The
// backend treats `end` as the last millisecond of that calendar day.
interface Cell {
  label: string
  start: Date
  end: Date // inclusive last day
}

function monthCells(year: number): Cell[] {
  return Array.from({ length: 12 }, (_, m) => {
    const start = new Date(year, m, 1)
    const end = new Date(year, m + 1, 0) // last day of month m
    return { label: monthLabel(start), start, end }
  })
}

function quarterCells(year: number): Cell[] {
  return Array.from({ length: 4 }, (_, q) => {
    const start = new Date(year, q * 3, 1)
    const end = new Date(year, q * 3 + 3, 0) // last day of quarter
    return { label: `Q${q + 1}`, start, end }
  })
}

function yearCells(years: number[]): Cell[] {
  return years.map((y) => ({
    label: String(y),
    start: new Date(y, 0, 1),
    end: new Date(y, 11, 31),
  }))
}

function weekCells(year: number): Cell[] {
  // Monday-start weeks. Generate every Monday whose week overlaps the year.
  const out: Cell[] = []
  const first = new Date(year, 0, 1)
  const day = first.getDay() || 7
  first.setDate(first.getDate() - (day - 1))
  while (first.getFullYear() <= year) {
    const start = new Date(first)
    const end = addDays(start, 6) // inclusive Sunday
    if (start.getFullYear() === year || end.getFullYear() === year) {
      out.push({
        label: `${pad(start.getDate())}/${pad(start.getMonth() + 1)}`,
        start,
        end,
      })
    }
    first.setDate(first.getDate() + 7)
    if (start.getFullYear() > year) break
  }
  return out
}

function grainToInterval(g: Grain): Interval {
  return g
}

// ── presets ─────────────────────────────────────────────────────────

// A preset may resolve to either explicit dates (fixed when selected) or a
// RelativeRange key (re-resolved on every read so the selection auto-shifts
// across day/month boundaries).
interface Preset {
  label: string
  resolve: () =>
    | { start: string; end: string; interval?: Interval }
    | { range: RelativeRange; interval?: Interval }
}

// Every preset persists as a RelativeRange key so the selection re-resolves
// on each read and auto-shifts when the calendar crosses a day/month/quarter
// boundary (e.g. on May 1 "Last 12 full months" silently updates from
// Apr→Mar 2025 to May→Apr 2026 without user action).
const PRESETS: Preset[] = [
  { label: 'This month', resolve: () => ({ range: 'this_month', interval: 'month' }) },
  { label: 'Last full month', resolve: () => ({ range: 'last_full_month', interval: 'month' }) },
  { label: 'Last 3 full months', resolve: () => ({ range: 'last_3_full_months', interval: 'month' }) },
  { label: 'Last 6 full months', resolve: () => ({ range: 'last_6_full_months', interval: 'month' }) },
  { label: 'Last 12 full months', resolve: () => ({ range: 'last_12_full_months', interval: 'month' }) },
  { label: 'Quarter to date', resolve: () => ({ range: 'qtd', interval: 'month' }) },
  { label: 'Year to date', resolve: () => ({ range: 'ytd', interval: 'month' }) },
  { label: 'All time', resolve: () => ({ range: 'all_time', interval: 'month' }) },
]

// ── component ───────────────────────────────────────────────────────

export function GlobalTimeRangePicker() {
  const { start, end, interval, range, setRange } = useTimeRange({ range: 'last_90d' })
  const [open, setOpen] = useState(false)
  const grain: Grain = interval === 'day' ? 'month' : (interval as Grain)
  const [pending, setPending] = useState<Cell | null>(null)
  const [hovered, setHovered] = useState<Cell | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  // Position the popover next to the trigger imperatively (DOM measurement
  // is not render-worthy state, so we style the ref directly instead of
  // round-tripping through setState). Clamp to the viewport so it never
  // overflows and always remains fully visible.
  useLayoutEffect(() => {
    if (!open) return
    const POPOVER_W = 640
    const POPOVER_H = 480
    const MARGIN = 12
    const compute = () => {
      if (!rootRef.current || !popoverRef.current) return
      const rect = rootRef.current.getBoundingClientRect()
      const el = popoverRef.current
      const vw = window.innerWidth
      const vh = window.innerHeight
      let left = rect.right + 8
      if (left + POPOVER_W + MARGIN > vw) {
        left = Math.max(MARGIN, rect.left - POPOVER_W - 8)
      }
      const preferredTop = rect.top - POPOVER_H + rect.height
      const top = Math.max(MARGIN, Math.min(preferredTop, vh - POPOVER_H - MARGIN))
      el.style.left = `${left}px`
      el.style.top = `${top}px`
      el.style.maxHeight = `${vh - top - MARGIN}px`
    }
    compute()
    window.addEventListener('resize', compute)
    return () => window.removeEventListener('resize', compute)
  }, [open])

  // Close on outside click / Escape. Portaled popover: check both the
  // trigger root and the popover itself before treating a click as outside.
  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      const t = e.target as Node
      if (rootRef.current?.contains(t)) return
      if (popoverRef.current?.contains(t)) return
      setOpen(false)
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const selectedStart = useMemo(() => parseIso(start), [start])
  const selectedEnd = useMemo(() => parseIso(end), [end])

  const gridYears = useMemo(() => {
    const now = new Date()
    const first = Math.min(selectedStart.getFullYear(), now.getFullYear() - 2)
    const last = Math.max(selectedEnd.getFullYear(), now.getFullYear())
    return yearsBetween(first, last)
  }, [selectedStart, selectedEnd])

  function isCellInSelection(cell: Cell): 'start' | 'end' | 'inside' | null {
    if (pending) {
      const first = pending
      const second = hovered ?? pending
      const loStart = first.start < second.start ? first.start : second.start
      const hiEnd = first.end > second.end ? first.end : second.end
      if (cell.end < loStart || cell.start > hiEnd) return null
      if (cell.start.getTime() === loStart.getTime()) return 'start'
      if (cell.end.getTime() === hiEnd.getTime()) return 'end'
      return 'inside'
    }
    if (cell.end < selectedStart || cell.start > selectedEnd) return null
    if (cell.start.getTime() === selectedStart.getTime()) return 'start'
    if (cell.end.getTime() === selectedEnd.getTime()) return 'end'
    return 'inside'
  }

  function handleCellClick(cell: Cell) {
    if (!pending) {
      setPending(cell)
      setHovered(cell)
      return
    }
    const first = pending.start < cell.start ? pending : cell
    const second = pending.start < cell.start ? cell : pending
    setRange({
      start: fmt(first.start),
      end: fmt(second.end),
      interval: grainToInterval(grain),
    })
    setPending(null)
    setHovered(null)
    setOpen(false)
  }

  function applyPreset(p: Preset) {
    setRange(p.resolve())
    setPending(null)
    setHovered(null)
    setOpen(false)
  }

  function changeGrain(g: Grain) {
    setRange({ interval: grainToInterval(g) })
  }

  const triggerLabel = useMemo(() => {
    if (range) {
      const named = RELATIVE_RANGES.find((r) => r.value === range)
      if (named) return named.label
    }
    const s = selectedStart
    const e = selectedEnd
    const sameMonth =
      s.getFullYear() === e.getFullYear() &&
      s.getMonth() === e.getMonth() &&
      s.getDate() === 1 &&
      e.getDate() === new Date(e.getFullYear(), e.getMonth() + 1, 0).getDate()
    if (sameMonth) return monthYearLabel(s)
    const sameYear = s.getFullYear() === e.getFullYear()
    const sLabel = s.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: sameYear ? undefined : 'numeric',
    })
    const eLabel = e.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
    return `${sLabel} – ${eLabel}`
  }, [range, selectedStart, selectedEnd])

  const intervalLabel =
    interval === 'day'
      ? 'Daily'
      : interval === 'week'
        ? 'Weekly'
        : interval === 'month'
          ? 'Monthly'
          : interval === 'quarter'
            ? 'Quarterly'
            : 'Yearly'

  return (
    <div ref={rootRef} className="relative px-3 py-3 border-t border-border">
      <div className="flex items-center gap-2 mb-2">
        <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Time range
        </span>
      </div>

      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left bg-background border border-border rounded-md px-2.5 py-1.5 text-xs hover:border-primary/50"
        title="Applies to all reports and dashboards"
      >
        <div className="font-medium truncate">{triggerLabel}</div>
        <div className="text-muted-foreground">{intervalLabel}</div>
      </button>

      {open && createPortal(
        <div
          ref={popoverRef}
          className="fixed flex flex-col bg-white border border-border rounded-lg shadow-xl overflow-hidden"
          style={{
            width: 640,
            backgroundColor: '#ffffff',
            color: '#0a0a0a',
            zIndex: 9999,
            isolation: 'isolate',
          }}
        >
          <div
            className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0"
            style={{ backgroundColor: '#ffffff' }}
          >
            <div className="flex items-center gap-1 bg-background rounded-md p-0.5 border border-border">
              {(['week', 'month', 'quarter', 'year'] as Grain[]).map((g) => (
                <button
                  key={g}
                  onClick={() => changeGrain(g)}
                  className={`px-2.5 py-1 text-xs rounded capitalize ${
                    grain === g
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1 rounded hover:bg-accent text-muted-foreground"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div
            className="flex flex-1 min-h-0"
            style={{ backgroundColor: '#ffffff' }}
          >
            <div className="w-40 shrink-0 border-r border-border p-2 space-y-0.5 overflow-y-auto">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => applyPreset(p)}
                  className="w-full text-left px-2 py-1 text-xs rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                >
                  {p.label}
                </button>
              ))}
            </div>

            <div className="flex-1 p-3 overflow-y-auto min-h-0">
              {grain === 'year' ? (
                <div className="grid grid-cols-5 gap-1">
                  {yearCells(gridYears).map((cell) => (
                    <GridCell
                      key={String(cell.start)}
                      cell={cell}
                      state={isCellInSelection(cell)}
                      onClick={() => handleCellClick(cell)}
                      onHover={() => pending && setHovered(cell)}
                    />
                  ))}
                </div>
              ) : grain === 'week' ? (
                <div className="space-y-4">
                  {gridYears.map((y) => (
                    <div key={y}>
                      <div className="text-[11px] font-medium text-muted-foreground mb-1">{y}</div>
                      <div className="grid grid-cols-6 gap-1">
                        {weekCells(y).map((cell) => (
                          <GridCell
                            key={String(cell.start)}
                            cell={cell}
                            state={isCellInSelection(cell)}
                            onClick={() => handleCellClick(cell)}
                            onHover={() => pending && setHovered(cell)}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : grain === 'quarter' ? (
                <div className="space-y-3">
                  {gridYears.map((y) => (
                    <div key={y}>
                      <div className="text-[11px] font-medium text-muted-foreground mb-1">{y}</div>
                      <div className="grid grid-cols-4 gap-1">
                        {quarterCells(y).map((cell) => (
                          <GridCell
                            key={String(cell.start)}
                            cell={cell}
                            state={isCellInSelection(cell)}
                            onClick={() => handleCellClick(cell)}
                            onHover={() => pending && setHovered(cell)}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  {gridYears.map((y) => (
                    <div key={y}>
                      <div className="text-[11px] font-medium text-muted-foreground mb-1">{y}</div>
                      <div className="grid grid-cols-6 gap-1">
                        {monthCells(y).map((cell) => (
                          <GridCell
                            key={String(cell.start)}
                            cell={cell}
                            state={isCellInSelection(cell)}
                            onClick={() => handleCellClick(cell)}
                            onHover={() => pending && setHovered(cell)}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div
            className="flex items-center gap-2 px-3 py-2 border-t border-border text-xs shrink-0"
            style={{ backgroundColor: '#ffffff' }}
          >
            <label className="flex items-center gap-1 text-muted-foreground">
              From
              <input
                type="date"
                value={start}
                onChange={(e) => {
                  if (e.target.value) setRange({ start: e.target.value, end })
                }}
                className="bg-background border border-border rounded px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-1 text-muted-foreground">
              To
              <input
                type="date"
                value={end}
                onChange={(e) => {
                  if (e.target.value) setRange({ start, end: e.target.value })
                }}
                className="bg-background border border-border rounded px-2 py-1"
              />
            </label>
            {pending && (
              <span className="ml-auto text-muted-foreground">
                Click another {grain} to set the end
              </span>
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

function GridCell({
  cell,
  state,
  onClick,
  onHover,
}: {
  cell: Cell
  state: 'start' | 'end' | 'inside' | null
  onClick: () => void
  onHover: () => void
}) {
  const base = 'px-2 py-1.5 text-xs rounded cursor-pointer transition-colors text-center'
  let cls = `${base} hover:bg-accent text-foreground`
  if (state === 'start' || state === 'end') {
    cls = `${base} bg-primary text-primary-foreground font-medium`
  } else if (state === 'inside') {
    cls = `${base} bg-primary/20 text-foreground`
  }
  return (
    <button onClick={onClick} onMouseEnter={onHover} className={cls}>
      {cell.label}
    </button>
  )
}
