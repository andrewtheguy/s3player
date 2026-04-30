import { Link, useParams } from 'react-router-dom'
import type { MonthsResponse } from '@/lib/api'
import { formatTwoDigit } from '@/lib/episode-path'
import { useFetch } from '@/lib/use-fetch'

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

export function MonthsPage() {
  const { station, show, year } = useParams<{
    station: string
    show: string
    year: string
  }>()
  const { data, error, loading } = useFetch<MonthsResponse>(
    `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows/${encodeURIComponent(show ?? '')}/months`,
  )

  if (loading) return <p className="text-muted-foreground">Loading months…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const yearNum = Number(year)
  const months = (data?.months ?? [])
    .filter((m) => m.year === yearNum)
    .sort((a, b) => b.month - a.month)
  if (months.length === 0)
    return <p className="text-muted-foreground">No episodes for {year} yet.</p>

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {decodeURIComponent(show ?? '')} — {year}
      </h1>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {months.map((m) => (
          <li key={`${m.year}-${m.month}`}>
            <Link
              to={`/shows/${encodeURIComponent(station ?? '')}/${encodeURIComponent(show ?? '')}/${m.year}/${formatTwoDigit(m.month)}`}
              className="block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
            >
              <div className="font-medium">
                {formatTwoDigit(m.month)}-{MONTH_NAMES[m.month - 1]}
              </div>
              <div className="text-sm text-muted-foreground">
                {m.episode_count}{' '}
                {m.episode_count === 1 ? 'episode' : 'episodes'}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
