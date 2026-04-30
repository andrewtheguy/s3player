import { Play } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router-dom'
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
import {
  buildEpisodePagePath,
  normalizeTwoDigitPathSegment,
} from '@/lib/episode-path'
import { useFetch } from '@/lib/use-fetch'

function formatTimeSlot(slot: string | null): string {
  if (!slot) return ''
  const m = /^(\d{2})(\d{2})_(\d{2})(\d{2})$/.exec(slot)
  if (!m) return slot
  return `${m[1]}:${m[2]}–${m[3]}:${m[4]}`
}

export function EpisodesPage() {
  const { station, show, year, month } = useParams<{
    station: string
    show: string
    year: string
    month: string
  }>()
  const normalizedMonth = normalizeTwoDigitPathSegment(month, 1, 12)
  const effectiveMonth = normalizedMonth ?? month ?? ''
  const url = `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows/${encodeURIComponent(show ?? '')}/months/${year}/${effectiveMonth}/episodes`
  const { data, error, loading } = useFetch<EpisodesResponse>(url)

  if (normalizedMonth) {
    return (
      <Navigate
        replace
        to={`/shows/${encodeURIComponent(station ?? '')}/${encodeURIComponent(show ?? '')}/${year}/${normalizedMonth}`}
      />
    )
  }

  if (loading) return <p className="text-muted-foreground">Loading episodes…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const episodes = data?.episodes ?? []
  if (episodes.length === 0)
    return <p className="text-muted-foreground">No episodes in this month.</p>

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {decodeURIComponent(show ?? '')} — {year}-{effectiveMonth}
      </h1>
      <div className="rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Time</TableHead>
              <TableHead className="hidden sm:table-cell">Chapters</TableHead>
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
                    <Link
                      to={buildEpisodePagePath(ep, station ?? '', show ?? '')}
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
  )
}
