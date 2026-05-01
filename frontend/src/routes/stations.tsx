import { Link } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { EpisodeCard } from '@/components/episode-card'
import type { RecentResponse, StationsResponse } from '@/lib/api'
import { useFetch } from '@/lib/use-fetch'

function HomeRow({
  title,
  episodes,
  showProgress,
}: {
  title: string
  episodes: RecentResponse['episodes']
  showProgress: boolean
}) {
  if (episodes.length === 0) return null
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold tracking-tight">{title}</h2>
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
        {episodes.map((e) => (
          <div key={e.id} className="shrink-0">
            <EpisodeCard episode={e} showProgress={showProgress} />
          </div>
        ))}
      </div>
    </section>
  )
}

export function StationsPage() {
  const { data, error, loading } = useFetch<StationsResponse>(
    '/api/shows/stations',
  )
  const { data: inProgress } = useFetch<RecentResponse>(
    '/api/player/in-progress',
  )
  const { data: recent } = useFetch<RecentResponse>('/api/player/recent')

  if (loading) return <p className="text-muted-foreground">Loading stations…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const stations = data?.stations ?? []

  return (
    <div className="space-y-8">
      <BreadcrumbTrail crumbs={[{ label: 'Stations' }]} />

      <HomeRow
        title="Continue listening"
        episodes={inProgress?.episodes ?? []}
        showProgress
      />
      <HomeRow
        title="Recently played"
        episodes={recent?.episodes ?? []}
        showProgress={false}
      />

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
