import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { EpisodeCard } from '@/components/episode-card'
import {
  type FavoritesResponse,
  playerApi,
  type RecentEpisode,
  type RecentResponse,
  type StationsResponse,
} from '@/lib/api'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

function HomeRow({
  title,
  episodes,
  showProgress,
  onRemove,
}: {
  title: string
  episodes: RecentResponse['episodes']
  showProgress: boolean
  onRemove?: (episode: RecentEpisode) => void
}) {
  if (episodes.length === 0) return null
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold tracking-tight">{title}</h2>
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
        {episodes.map((e) => (
          <div key={e.id} className="shrink-0">
            <EpisodeCard
              episode={e}
              showProgress={showProgress}
              onRemove={onRemove ? () => onRemove(e) : undefined}
            />
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
  const { data: favorites } = useFetch<FavoritesResponse>(
    '/api/shows/favorites',
  )
  const { data: inProgress } = useFetch<RecentResponse>(
    '/api/player/in-progress',
  )
  const { data: recent } = useFetch<RecentResponse>(
    '/api/player/recent-completed',
  )

  const [inProgressEpisodes, setInProgressEpisodes] = useState<
    RecentResponse['episodes']
  >([])
  useEffect(() => {
    setInProgressEpisodes(inProgress?.episodes ?? [])
  }, [inProgress])

  const handleRemoveInProgress = (episode: RecentEpisode) => {
    setInProgressEpisodes((prev) => prev.filter((e) => e.id !== episode.id))
    playerApi.deleteProgress(episode.id).catch((err: unknown) => {
      console.error('Failed to remove from Continue listening', err)
      setInProgressEpisodes((prev) =>
        [...prev, episode].sort(
          (a, b) => Date.parse(b.last_played_at) - Date.parse(a.last_played_at),
        ),
      )
    })
  }

  useDocumentTitle('Stations')

  if (loading) return <p className="text-muted-foreground">Loading stations…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const stations = data?.stations ?? []

  const favoriteShows = favorites?.favorites ?? []

  return (
    <div className="space-y-8">
      <BreadcrumbTrail crumbs={[{ label: 'Stations' }]} />

      {favoriteShows.length > 0 ? (
        <section>
          <h2 className="mb-3 text-lg font-semibold tracking-tight">
            Favorites
          </h2>
          <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2">
            {favoriteShows.map((f) => (
              <Link
                key={f.id}
                to={`/favorites/${f.id}`}
                className="block min-w-[16rem] shrink-0 rounded-lg border bg-card p-4 transition-colors hover:bg-accent"
              >
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  {f.station}
                </div>
                <div className="mt-1 truncate font-medium">{f.name}</div>
                <div className="mt-0.5 text-sm text-muted-foreground">
                  {f.episode_count}{' '}
                  {f.episode_count === 1 ? 'episode' : 'episodes'}
                </div>
                {f.latest_aired_on ? (
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    Latest: {f.latest_aired_on}
                  </div>
                ) : null}
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <HomeRow
        title="Continue listening"
        episodes={inProgressEpisodes}
        showProgress
        onRemove={handleRemoveInProgress}
      />
      <HomeRow
        title="Recently Completed"
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
