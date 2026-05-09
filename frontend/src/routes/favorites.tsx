import { Play } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { RecentShowEpisodesResponse, ShowEpisode } from '@/lib/api'
import { formatPosition, formatRelative, formatTimeSlot } from '@/lib/format'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

function StatusCell({ episode }: { episode: ShowEpisode }) {
  if (
    episode.duration_ms != null &&
    !episode.completed &&
    episode.position_ms > 0
  ) {
    const pct = Math.min(
      100,
      Math.max(0, (episode.position_ms / episode.duration_ms) * 100),
    )
    return (
      <div className="flex flex-col gap-1">
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
        </div>
        <div className="text-xs text-muted-foreground tabular-nums">
          {formatPosition(episode.position_ms)} /{' '}
          {formatPosition(episode.duration_ms)}
        </div>
      </div>
    )
  }
  if (episode.completed) {
    return (
      <span className="text-xs text-muted-foreground">
        Completed
        {episode.last_played_at
          ? ` · ${formatRelative(episode.last_played_at)}`
          : ''}
      </span>
    )
  }
  return null
}

export function FavoritesPage() {
  const navigate = useNavigate()
  const { show_id } = useParams<{ show_id: string }>()
  const { data, error, loading } = useFetch<RecentShowEpisodesResponse>(
    `/api/shows/${show_id}/recent-episodes?limit=20`,
  )

  useDocumentTitle(data?.show ? `${data.show.name} — Recent` : 'Favorite show')

  if (loading) return <p className="text-muted-foreground">Loading episodes…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const show = data?.show
  const episodes = data?.episodes ?? []

  const crumbs = show
    ? [
        { label: 'Stations', href: '/stations' },
        {
          label: show.station,
          href: `/stations/${encodeURIComponent(show.station)}`,
        },
        { label: `${show.name} — Recent` },
      ]
    : []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      {episodes.length === 0 ? (
        <p className="text-muted-foreground">No episodes for this show yet.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            {show?.name} — Recent
          </h1>
          <div className="rounded-lg border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {episodes.map((ep) => (
                  <TableRow
                    key={ep.id}
                    onClick={() => navigate(`/player/${ep.id}`)}
                    className="cursor-pointer"
                  >
                    <TableCell className="font-medium">{ep.aired_on}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatTimeSlot(ep.time_slot)}
                    </TableCell>
                    <TableCell>
                      <StatusCell episode={ep} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" asChild>
                        <Link
                          to={`/player/${ep.id}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Play aria-hidden />
                          Play
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  )
}
