import { ChevronLeft } from 'lucide-react'
import { useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import type { Chapter, Episode, EpisodesResponse } from '@/lib/api'
import {
  getEpisodeFileName,
  parseTwoDigitPathSegment,
} from '@/lib/episode-path'
import { useFetch } from '@/lib/use-fetch'

function formatTimestamp(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

function EpisodePlayer({ episode }: { episode: Episode }) {
  const audioRef = useRef<HTMLAudioElement>(null)

  function jumpTo(chapter: Chapter) {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = chapter.start / 1000
    audio.play().catch(() => {})
  }

  return (
    <div className="space-y-4">
      <audio
        key={episode.id}
        ref={audioRef}
        src={`/api/shows/episodes/${episode.id}/audio`}
        controls
        preload="metadata"
        className="w-full"
      >
        <track kind="captions" />
      </audio>
      {episode.chapters && episode.chapters.length > 0 ? (
        <div className="max-h-[28rem] overflow-y-auto rounded-md border">
          {episode.chapters.map((c) => (
            <button
              key={`${c.start}-${c.end}-${c.title}`}
              type="button"
              onClick={() => jumpTo(c)}
              className="flex w-full items-center justify-between gap-3 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-accent"
            >
              <span className="truncate">
                {c.title || formatTimestamp(c.start)}
              </span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {formatTimestamp(c.start)}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No chapters.</p>
      )}
    </div>
  )
}

export function PlayerPage() {
  const { station, show, year, month, day, episodeFile } = useParams<{
    station: string
    show: string
    year: string
    month: string
    day: string
    episodeFile: string
  }>()
  const monthSegment = parseTwoDigitPathSegment(month, 1, 12)
  const daySegment = parseTwoDigitPathSegment(day, 1, 31)
  const hasInvalidDateSegment = monthSegment === null || daySegment === null
  const listUrl = hasInvalidDateSegment
    ? null
    : `/api/shows/stations/${encodeURIComponent(station ?? '')}/shows/${encodeURIComponent(show ?? '')}/months/${year}/${monthSegment}/episodes`
  const { data, error, loading } = useFetch<EpisodesResponse>(listUrl)
  const backUrl = `/shows/${encodeURIComponent(station ?? '')}/${encodeURIComponent(show ?? '')}/${year}/${monthSegment ?? ''}`

  if (hasInvalidDateSegment) {
    return <p className="text-muted-foreground">Episode not found.</p>
  }

  if (loading) return <p className="text-muted-foreground">Loading player…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>

  const episodes = data?.episodes ?? []
  const episode = episodes.find(
    (ep) =>
      ep.aired_on === `${year}-${monthSegment}-${daySegment}` &&
      getEpisodeFileName(ep) === episodeFile,
  )

  if (!episode) {
    return <p className="text-muted-foreground">Episode not found.</p>
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">
            {episodeFile}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {decodeURIComponent(show ?? '')} — {episode.aired_on}
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link to={backUrl}>
            <ChevronLeft aria-hidden />
            Episodes
          </Link>
        </Button>
      </div>
      <EpisodePlayer episode={episode} />
    </div>
  )
}
