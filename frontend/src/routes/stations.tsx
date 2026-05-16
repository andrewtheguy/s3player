import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { EpisodeCard } from '@/components/episode-card'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  type FavoritesResponse,
  playerApi,
  type RecentEpisode,
  type RecentResponse,
  type StationsResponse,
} from '@/lib/api'
import { readStoredToken } from '@/lib/playerSession'
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

const refreshOptions = { refreshInterval: 15000 }

export function StationsPage() {
  const { data, error, loading } = useFetch<StationsResponse>(
    '/api/shows/stations',
    refreshOptions,
  )
  const { data: favorites } = useFetch<FavoritesResponse>(
    '/api/shows/favorites',
    refreshOptions,
  )
  const { data: inProgress } = useFetch<RecentResponse>(
    '/api/player/in-progress',
    refreshOptions,
  )
  const { data: recent } = useFetch<RecentResponse>(
    '/api/player/recent-completed',
    refreshOptions,
  )

  const [inProgressEpisodes, setInProgressEpisodes] = useState<
    RecentResponse['episodes']
  >([])
  // Tombstones for episodes the user has removed locally. We hide them from
  // any refresh response that still contains them (DELETE may not have landed
  // server-side yet, or a refresh started before the click is in flight).
  // Tombstones are dropped once the server stops returning the id.
  const pendingRemovalsRef = useRef<Set<number>>(new Set())
  useEffect(() => {
    if (!inProgress) return
    const serverIds = new Set(inProgress.episodes.map((e) => e.id))
    for (const id of pendingRemovalsRef.current) {
      if (!serverIds.has(id)) pendingRemovalsRef.current.delete(id)
    }
    setInProgressEpisodes(
      inProgress.episodes.filter((e) => !pendingRemovalsRef.current.has(e.id)),
    )
  }, [inProgress])

  const [dismissTarget, setDismissTarget] = useState<RecentEpisode | null>(null)
  const [dismissBusy, setDismissBusy] = useState(false)
  const dismissSessionToken = dismissTarget ? readStoredToken() : null

  const handleRemoveInProgress = (episode: RecentEpisode) => {
    setDismissTarget(episode)
  }

  const closeDismissDialog = () => {
    if (dismissBusy) return
    setDismissTarget(null)
  }

  const runDismiss = async (
    episode: RecentEpisode,
    token: string,
    action: 'delete' | 'complete',
  ) => {
    setDismissBusy(true)
    pendingRemovalsRef.current.add(episode.id)
    setInProgressEpisodes((prev) => prev.filter((e) => e.id !== episode.id))
    try {
      if (action === 'delete') {
        await playerApi.deleteProgress(episode.id, token)
      } else {
        await playerApi.progress(
          episode.id,
          token,
          episode.position_ms,
          episode.duration_ms,
          true,
        )
      }
      setDismissTarget(null)
    } catch (err) {
      console.error('Failed to dismiss Continue listening entry', err)
      pendingRemovalsRef.current.delete(episode.id)
      setInProgressEpisodes((prev) =>
        [...prev, episode].sort(
          (a, b) => Date.parse(b.last_played_at) - Date.parse(a.last_played_at),
        ),
      )
    } finally {
      setDismissBusy(false)
    }
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

      <Dialog
        open={dismissTarget !== null}
        onOpenChange={(open) => {
          if (!open) closeDismissDialog()
        }}
      >
        <DialogContent>
          {dismissTarget ? (
            dismissSessionToken ? (
              <>
                <DialogHeader>
                  <DialogTitle>Dismiss from Continue listening</DialogTitle>
                  <DialogDescription>
                    {dismissTarget.show_name} · {dismissTarget.aired_on}
                  </DialogDescription>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  Mark this episode as completed, or delete your saved progress
                  entirely.
                </p>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={closeDismissDialog}
                    disabled={dismissBusy}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => {
                      void runDismiss(
                        dismissTarget,
                        dismissSessionToken,
                        'delete',
                      )
                    }}
                    disabled={dismissBusy}
                  >
                    Delete progress
                  </Button>
                  <Button
                    onClick={() => {
                      void runDismiss(
                        dismissTarget,
                        dismissSessionToken,
                        'complete',
                      )
                    }}
                    disabled={dismissBusy}
                  >
                    Mark as completed
                  </Button>
                </DialogFooter>
              </>
            ) : (
              <>
                <DialogHeader>
                  <DialogTitle>No active player session</DialogTitle>
                  <DialogDescription>
                    Only the currently-active player can change playback state.
                  </DialogDescription>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  Open this episode and click{' '}
                  <span className="font-medium">Take over playback</span> to
                  claim the session, then come back to dismiss it.
                </p>
                <DialogFooter>
                  <Button variant="outline" onClick={closeDismissDialog}>
                    Close
                  </Button>
                </DialogFooter>
              </>
            )
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
