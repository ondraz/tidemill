import type { ChartConfig, Interval, RelativeRange } from './types'

interface TimeRangeInput {
  start: string
  end: string
  interval?: Interval
  range: RelativeRange | null
}

// Build the time-range slice of a ChartConfig from the report's active time
// range. When the user picked a named range we save the tag so the chart re-
// resolves on every read (e.g. "Last 3 full months" auto-shifts month to
// month). When they picked explicit dates we save those literally.
export function chartTimeRangeConfig(
  t: TimeRangeInput,
): Pick<ChartConfig, 'params' | 'timeRangeMode' | 'relativeRange'> {
  if (t.range) {
    return {
      params: { interval: t.interval },
      timeRangeMode: 'relative',
      relativeRange: t.range,
    }
  }
  return {
    params: { start: t.start, end: t.end, interval: t.interval },
    timeRangeMode: 'fixed',
  }
}
