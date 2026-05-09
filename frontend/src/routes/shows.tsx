import { Star } from 'lucide-react'
import { type MouseEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { type Show, type ShowsResponse, showsApi } from '@/lib/api'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

export function ShowsPage() {
  const { station } = useParams<{ station: string }>()
  const { data, error, loading } = useFetch<ShowsResponse>(
    `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows`,
  )

  const [shows, setShows] = useState<Show[]>([])
  useEffect(() => {
    setShows(data?.shows ?? [])
  }, [data])

  const crumbs = [
    { label: 'Stations', href: '/stations' },
    { label: station ?? '' },
  ]

  useDocumentTitle(station ?? 'Shows')

  const toggleFavorite = (show: Show) => (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault()
    e.stopPropagation()
    const wasFavorite = show.is_favorite
    setShows((prev) =>
      prev.map((s) =>
        s.id === show.id ? { ...s, is_favorite: !wasFavorite } : s,
      ),
    )
    const request = wasFavorite
      ? showsApi.removeFavorite(show.id)
      : showsApi.addFavorite(show.id)
    request.catch((err: unknown) => {
      console.error('Failed to toggle favorite', err)
      setShows((prev) =>
        prev.map((s) =>
          s.id === show.id ? { ...s, is_favorite: wasFavorite } : s,
        ),
      )
    })
  }

  if (loading) return <p className="text-muted-foreground">Loading shows…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>

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
                  className="relative block rounded-lg border bg-card p-5 transition-colors hover:bg-accent"
                >
                  <button
                    type="button"
                    aria-label={
                      s.is_favorite
                        ? `Unfavorite ${s.name}`
                        : `Favorite ${s.name}`
                    }
                    aria-pressed={s.is_favorite}
                    onClick={toggleFavorite(s)}
                    className="absolute top-2 right-2 grid size-7 place-items-center rounded-full text-muted-foreground transition hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Star
                      className={`size-4 ${
                        s.is_favorite
                          ? 'fill-primary text-primary'
                          : 'fill-none'
                      }`}
                    />
                  </button>
                  <div className="pr-8 font-medium">{s.name}</div>
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
