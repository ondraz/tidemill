export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatCurrencyPrecise(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatDate(date: string): string {
  return new Date(date).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatMonthYear(date: string): string {
  return new Date(date).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

export function formatWeek(date: string): string {
  // ISO 8601 week number: the week containing Thursday belongs to that year.
  const d = new Date(date)
  const utc = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()))
  const dayNum = utc.getUTCDay() || 7
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((utc.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7)
  return `${utc.getUTCFullYear()}-W${String(week).padStart(2, '0')}`
}

export function formatQuarter(date: string): string {
  const d = new Date(date)
  const q = Math.floor(d.getUTCMonth() / 3) + 1
  return `${d.getUTCFullYear()}-Q${q}`
}

export function formatYear(date: string): string {
  return String(new Date(date).getUTCFullYear())
}

export type Granularity = 'day' | 'week' | 'month' | 'quarter' | 'year'

export function formatPeriod(date: string, granularity: Granularity = 'month'): string {
  switch (granularity) {
    case 'week':
      return formatWeek(date)
    case 'month':
      return formatMonthYear(date)
    case 'quarter':
      return formatQuarter(date)
    case 'year':
      return formatYear(date)
    case 'day':
    default:
      return formatDate(date)
  }
}
