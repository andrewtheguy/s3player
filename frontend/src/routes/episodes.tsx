import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { UrlDialog } from '@/components/url-dialog'
import {
  apiFetch,
  type EpisodesResponse,
  type PresignedUrlResponse,
} from '@/lib/api'
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
  const url = `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows/${encodeURIComponent(show ?? '')}/months/${year}/${month}/episodes`
  const { data, error, loading } = useFetch<EpisodesResponse>(url)

  const [dialogUrl, setDialogUrl] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<number | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  async function fetchUrl(episodeId: number) {
    setPendingId(episodeId)
    setRequestError(null)
    try {
      const res = await apiFetch<PresignedUrlResponse>(
        `/api/shows/episodes/${episodeId}/url`,
      )
      setDialogUrl(res.url)
    } catch (e: unknown) {
      setRequestError(e instanceof Error ? e.message : String(e))
    } finally {
      setPendingId(null)
    }
  }

  if (loading) return <p className="text-muted-foreground">Loading episodes…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  const episodes = data?.episodes ?? []
  if (episodes.length === 0)
    return <p className="text-muted-foreground">No episodes in this month.</p>

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {decodeURIComponent(show ?? '')} — {year}-
        {String(month).padStart(2, '0')}
      </h1>
      {requestError && (
        <p className="mb-4 text-destructive">URL error: {requestError}</p>
      )}
      <div className="rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Time</TableHead>
              <TableHead className="hidden sm:table-cell">S3 key</TableHead>
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
                <TableCell className="hidden sm:table-cell">
                  <code className="text-xs text-muted-foreground">
                    {ep.s3_key}
                  </code>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    onClick={() => fetchUrl(ep.id)}
                    disabled={pendingId === ep.id}
                  >
                    {pendingId === ep.id ? 'Fetching…' : 'Get URL'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <UrlDialog url={dialogUrl} onClose={() => setDialogUrl(null)} />
    </div>
  )
}
