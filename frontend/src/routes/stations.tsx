import { Link } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import type { StationsResponse } from '@/lib/api'
import { useFetch } from '@/lib/use-fetch'

export function StationsPage() {
  const { data, error, loading } = useFetch<StationsResponse>(
    '/api/shows/stations',
  )

  if (loading) return <p className="text-muted-foreground">Loading stations…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const stations = data?.stations ?? []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={[{ label: 'Stations' }]} />
      {stations.length === 0 ? (
        <p className="text-muted-foreground">No stations indexed yet.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            Stations
          </h1>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {stations.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/stations/${encodeURIComponent(s.id)}`}
                  className="block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
                >
                  <div className="font-medium">{s.id}</div>
                  <div className="text-sm text-muted-foreground">
                    {s.show_count} {s.show_count === 1 ? 'show' : 'shows'}
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
