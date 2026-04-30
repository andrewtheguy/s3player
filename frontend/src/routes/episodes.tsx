import { Play } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
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
import type { EpisodesResponse } from '@/lib/api'
import { parseTwoDigitPathSegment } from '@/lib/episode-path'
import { useFetch } from '@/lib/use-fetch'

function formatTimeSlot(slot: string | null): string {
  if (!slot) return ''
  const m = /^(\d{2})(\d{2})_(\d{2})(\d{2})$/.exec(slot)
  if (!m) return slot
  return `${m[1]}:${m[2]}–${m[3]}:${m[4]}`
}

export function EpisodesPage() {
  const { show_id, year, month } = useParams<{
    show_id: string
    year: string
    month: string
  }>()
  const monthSegment = parseTwoDigitPathSegment(month, 1, 12)
  const url =
    monthSegment === null
      ? null
      : `/api/shows/${show_id}/months/${year}/${monthSegment}/episodes`
  const { data, error, loading } = useFetch<EpisodesResponse>(url)

  if (monthSegment === null) {
    return <p className="text-muted-foreground">Invalid month.</p>
  }

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
        { label: show.name, href: `/shows/${show.id}` },
        { label: year ?? '', href: `/shows/${show.id}/${year}` },
        { label: monthSegment },
      ]
    : []

  return (
    <div className="space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      {episodes.length === 0 ? (
        <p className="text-muted-foreground">No episodes in this month.</p>
      ) : (
        <div>
          <h1 className="mb-6 text-2xl font-semibold tracking-tight">
            {show?.name} — {year}-{monthSegment}
          </h1>
          <div className="rounded-lg border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead className="hidden sm:table-cell">
                    Chapters
                  </TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {episodes.map((ep) => (
                  <TableRow key={ep.id}>
                    <TableCell className="font-medium">{ep.aired_on}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatTimeSlot(ep.time_slot)}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">
                      {ep.chapters?.length ?? 0}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" asChild>
                        <Link to={`/player/${ep.id}`}>
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
