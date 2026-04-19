import type { Interval } from './types'

// Period iteration for timeline charts. Every helper here preserves the
// closed-closed `[start, end]` convention documented in
// docs/definitions.md: `periodStarts` is inclusive of the period covering
// `end`, and `periodEnd` returns the last calendar day of the period.

function parseIso(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

function formatIso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addInterval(d: Date, interval: Interval): Date {
  const next = new Date(d)
  switch (interval) {
    case 'day':
      next.setDate(next.getDate() + 1)
      break
    case 'week':
      next.setDate(next.getDate() + 7)
      break
    case 'month':
      next.setMonth(next.getMonth() + 1)
      break
    case 'quarter':
      next.setMonth(next.getMonth() + 3)
      break
    case 'year':
      next.setFullYear(next.getFullYear() + 1)
      break
  }
  return next
}

// Align a date to the start of the containing period. Weekly periods use
// ISO weeks (Monday start) so they match PostgreSQL's DATE_TRUNC('week').
function alignStart(d: Date, interval: Interval): Date {
  const x = new Date(d)
  switch (interval) {
    case 'day':
      break
    case 'week': {
      const day = x.getDay() || 7
      x.setDate(x.getDate() - (day - 1))
      break
    }
    case 'month':
      x.setDate(1)
      break
    case 'quarter': {
      const q = Math.floor(x.getMonth() / 3)
      x.setMonth(q * 3, 1)
      break
    }
    case 'year':
      x.setMonth(0, 1)
      break
  }
  return x
}

export function periodStarts(start: string, end: string, interval: Interval): string[] {
  const out: string[] = []
  const s = parseIso(start)
  const e = parseIso(end)
  let cur = alignStart(s, interval)
  while (cur <= e) {
    out.push(formatIso(cur))
    cur = addInterval(cur, interval)
  }
  return out
}

export function periodEnd(periodStart: string, interval: Interval): string {
  const s = parseIso(periodStart)
  const next = addInterval(s, interval)
  next.setDate(next.getDate() - 1)
  return formatIso(next)
}

