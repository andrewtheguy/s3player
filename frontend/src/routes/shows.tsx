import { Link, useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import type { ShowsResponse } from '@/lib/api'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

export function ShowsPage() {
  const { station } = useParams<{ station: string }>()
  const { data, error, loading } = useFetch<ShowsResponse>(
    `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows`,
  )

  const crumbs = [
    { label: 'Stations', href: '/stations' },
    { label: station ?? '' },
  ]

  useDocumentTitle(station ?? 'Shows')

  if (loading) return <p className="text-muted-foreground">Loading shows…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const shows = data?.shows ?? []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      {shows.length === 0 ? (
        <p className="text-muted-foreground">No shows for this station.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            {station}
          </h1>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {shows.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/shows/${s.id}`}
                  className="block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
                >
                  <div className="font-medium">{s.name}</div>
                  <div className="text-sm text-muted-foreground">
                    {s.episode_count}{' '}
                    {s.episode_count === 1 ? 'episode' : 'episodes'}
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
