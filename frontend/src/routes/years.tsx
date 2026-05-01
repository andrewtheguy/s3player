import { Link, useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import type { MonthsResponse } from '@/lib/api'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

interface YearBucket {
  year: number
  episode_count: number
  month_count: number
}

function aggregateYears(months: MonthsResponse['months']): YearBucket[] {
  const map = new Map<number, YearBucket>()
  for (const m of months) {
    const existing = map.get(m.year)
    if (existing) {
      existing.episode_count += m.episode_count
      existing.month_count += 1
    } else {
      map.set(m.year, {
        year: m.year,
        episode_count: m.episode_count,
        month_count: 1,
      })
    }
  }
  return [...map.values()].sort((a, b) => b.year - a.year)
}

export function YearsPage() {
  const { show_id } = useParams<{ show_id: string }>()
  const { data, error, loading } = useFetch<MonthsResponse>(
    `/api/shows/${show_id}/months`,
  )

  useDocumentTitle(data?.show?.name ?? 'Show')

  if (loading) return <p className="text-muted-foreground">Loading years…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const show = data?.show
  const years = aggregateYears(data?.months ?? [])

  const crumbs = show
    ? [
        { label: 'Stations', href: '/stations' },
        {
          label: show.station,
          href: `/stations/${encodeURIComponent(show.station)}`,
        },
        { label: show.name },
      ]
    : []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      {years.length === 0 ? (
        <p className="text-muted-foreground">No episodes for this show yet.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            {show?.name}
          </h1>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {years.map((y) => (
              <li key={y.year}>
                <Link
                  to={`/shows/${show_id}/${y.year}`}
                  className="block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
                >
                  <div className="font-medium">{y.year}</div>
                  <div className="text-sm text-muted-foreground">
                    {y.episode_count}{' '}
                    {y.episode_count === 1 ? 'episode' : 'episodes'}
                    {' · '}
                    {y.month_count} {y.month_count === 1 ? 'month' : 'months'}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
