import { RELATIVE_RANGES } from '@/lib/constants'
import type { RelativeRange, Interval } from '@/lib/types'

interface TimeRangePickerProps {
  onSelectRange: (range: RelativeRange) => void
  onSelectInterval: (interval: Interval) => void
  currentInterval: Interval
}

export function TimeRangePicker({
  onSelectRange,
  onSelectInterval,
  currentInterval,
}: TimeRangePickerProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex items-center gap-1 bg-card border border-border rounded-md p-0.5">
        {RELATIVE_RANGES.map((r) => (
          <button
            key={r.value}
            onClick={() => onSelectRange(r.value)}
            className="px-2.5 py-1 text-xs rounded hover:bg-accent text-muted-foreground hover:text-foreground"
          >
            {r.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1 bg-card border border-border rounded-md p-0.5">
        {(['day', 'week', 'month', 'year'] as Interval[]).map((i) => (
          <button
            key={i}
            onClick={() => onSelectInterval(i)}
            className={`px-2.5 py-1 text-xs rounded ${
              currentInterval === i
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground'
            }`}
          >
            {i.charAt(0).toUpperCase() + i.slice(1)}
          </button>
        ))}
      </div>
    </div>
  )
}
