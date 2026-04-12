import { useSearchParams } from 'react-router-dom'
import { useMemo, useCallback } from 'react'
import type { Interval, RelativeRange } from '@/lib/types'
import { resolveRelativeRange } from '@/lib/constants'

export interface TimeRange {
  start: string
  end: string
  interval: Interval
}

export function useTimeRange(defaults?: {
  range?: RelativeRange
  interval?: Interval
}) {
  const [searchParams, setSearchParams] = useSearchParams()

  const range = useMemo((): TimeRange => {
    const relRange = searchParams.get('range') as RelativeRange | null
    const interval = (searchParams.get('interval') as Interval) || defaults?.interval || 'month'

    if (relRange) {
      const { start, end } = resolveRelativeRange(relRange)
      return { start, end, interval }
    }

    const start = searchParams.get('start')
    const end = searchParams.get('end')
    if (start && end) {
      return { start, end, interval }
    }

    // Default: last 90 days
    const defaultRange = defaults?.range || 'last_90d'
    const { start: ds, end: de } = resolveRelativeRange(defaultRange)
    return { start: ds, end: de, interval }
  }, [searchParams, defaults?.range, defaults?.interval])

  const setRange = useCallback(
    (update: Partial<{ start: string; end: string; interval: Interval; range: RelativeRange }>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (update.range) {
          next.set('range', update.range)
          next.delete('start')
          next.delete('end')
        } else {
          if (update.start) next.set('start', update.start)
          if (update.end) next.set('end', update.end)
          next.delete('range')
        }
        if (update.interval) next.set('interval', update.interval)
        return next
      })
    },
    [setSearchParams],
  )

  return { ...range, setRange }
}
