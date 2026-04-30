import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { Slider } from '@/components/ui/slider'
import type { Chapter, Episode, EpisodeDetail } from '@/lib/api'
import { getEpisodeFileName } from '@/lib/episode-path'
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

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return '00:00:00'
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function EpisodePlayer({ episode }: { episode: Episode }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [isLoaded, setIsLoaded] = useState(false)

  const togglePlayPause = () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      audio.play().catch(() => {})
    } else {
      audio.pause()
    }
  }

  const seekRelative = useCallback((seconds: number) => {
    const audio = audioRef.current
    if (!audio) return
    const target = Math.max(
      0,
      Math.min(audio.duration || 0, audio.currentTime + seconds),
    )
    audio.currentTime = target
    setCurrentTime(target)
  }, [])

  const handleSeek = (value: number[]) => {
    const audio = audioRef.current
    const next = value[0]
    if (!audio || !Number.isFinite(next)) return
    audio.currentTime = next
    setCurrentTime(next)
  }

  function jumpTo(chapter: Chapter) {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = chapter.start / 1000
    audio.play().catch(() => {})
  }

  // Media Session: lock screen, AirPods, CarPlay map to ±15/30s.
  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    const s = navigator.mediaSession
    s.setActionHandler('play', () => {
      audioRef.current?.play().catch(() => {})
    })
    s.setActionHandler('pause', () => {
      audioRef.current?.pause()
    })
    s.setActionHandler('seekbackward', () => seekRelative(-15))
    s.setActionHandler('seekforward', () => seekRelative(30))
    s.setActionHandler('previoustrack', () => seekRelative(-15))
    s.setActionHandler('nexttrack', () => seekRelative(30))
    return () => {
      s.setActionHandler('play', null)
      s.setActionHandler('pause', null)
      s.setActionHandler('seekbackward', null)
      s.setActionHandler('seekforward', null)
      s.setActionHandler('previoustrack', null)
      s.setActionHandler('nexttrack', null)
    }
  }, [seekRelative])

  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: getEpisodeFileName(episode),
      artist: episode.aired_on,
    })
  }, [episode])

  const currentTimeMs = currentTime * 1000

  return (
    <div className="space-y-6">
      <audio
        key={episode.id}
        ref={audioRef}
        src={`/api/shows/episodes/${episode.id}/audio`}
        preload="metadata"
        playsInline
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDuration(e.currentTarget.duration)
          setIsLoaded(true)
        }}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        onSeeked={(e) => setCurrentTime(e.currentTarget.currentTime)}
      >
        <track kind="captions" />
      </audio>

      <div className="space-y-4">
        <div className="flex items-center justify-center gap-4">
          <button
            type="button"
            onClick={() => seekRelative(-15)}
            disabled={!isLoaded}
            title="Back 15 seconds"
            className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:border-dashed disabled:bg-muted/40 disabled:text-muted-foreground/70"
          >
            <Skip15BackIcon className="h-10 w-10" />
          </button>
          <button
            type="button"
            onClick={togglePlayPause}
            disabled={!isLoaded}
            aria-label={isPlaying ? 'Pause' : 'Play'}
            className="flex items-center justify-center transition-transform hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPlaying ? (
              <PauseCircleIcon className="h-16 w-16" />
            ) : (
              <PlayCircleIcon className="h-16 w-16" />
            )}
          </button>
          <button
            type="button"
            onClick={() => seekRelative(30)}
            disabled={!isLoaded}
            title="Forward 30 seconds"
            className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:border-dashed disabled:bg-muted/40 disabled:text-muted-foreground/70"
          >
            <Skip30ForwardIcon className="h-10 w-10" />
          </button>
        </div>

        <div className="space-y-2">
          <Slider
            value={[currentTime]}
            max={duration || 100}
            step={1}
            onValueChange={handleSeek}
            disabled={!isLoaded || !Number.isFinite(duration)}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>
      </div>

      {episode.chapters && episode.chapters.length > 0 ? (
        <div className="max-h-[28rem] overflow-y-auto rounded-md border">
          {episode.chapters.map((c) => {
            const isCurrent = currentTimeMs >= c.start && currentTimeMs < c.end
            const rightLabel = isCurrent
              ? `-${formatTimestamp(c.end - currentTimeMs)}`
              : formatTimestamp(c.end - c.start)
            return (
              <button
                key={`${episode.id}-${c.start}-${c.end}-${c.title}`}
                type="button"
                onClick={() => jumpTo(c)}
                aria-current={isCurrent || undefined}
                className={`flex w-full items-center justify-between gap-3 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-accent ${
                  isCurrent ? 'bg-accent font-medium' : ''
                }`}
              >
                <span className="truncate">
                  {c.title || formatTimestamp(c.start)}
                </span>
                <span
                  className={`shrink-0 font-mono text-xs ${
                    isCurrent
                      ? 'tabular-nums text-foreground'
                      : 'text-muted-foreground'
                  }`}
                >
                  {rightLabel}
                </span>
              </button>
            )
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No chapters.</p>
      )}
    </div>
  )
}

function PlayCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <title>Play</title>
      <circle cx="12" cy="12" r="11" fill="currentColor" />
      <path d="M9.5 7.5v9l7-4.5-7-4.5z" fill="white" />
    </svg>
  )
}

function PauseCircleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <title>Pause</title>
      <circle cx="12" cy="12" r="11" fill="currentColor" />
      <rect x="8" y="7" width="3" height="10" rx="0.5" fill="white" />
      <rect x="13" y="7" width="3" height="10" rx="0.5" fill="white" />
    </svg>
  )
}

function Skip15BackIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <title>Back 15 seconds</title>
      <path
        fill="currentColor"
        d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"
      />
      <text
        x="12"
        y="14"
        fontSize="8"
        fontWeight="700"
        textAnchor="middle"
        fill="currentColor"
        dominantBaseline="middle"
      >
        15
      </text>
    </svg>
  )
}

function Skip30ForwardIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <title>Forward 30 seconds</title>
      <path
        fill="currentColor"
        d="M12 5V1l5 5-5 5V7c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6h2c0 4.42-3.58 8-8 8s-8-3.58-8-8 3.58-8 8-8z"
      />
      <text
        x="12"
        y="14"
        fontSize="7"
        fontWeight="700"
        textAnchor="middle"
        fill="currentColor"
        dominantBaseline="middle"
      >
        30
      </text>
    </svg>
  )
}

export function PlayerPage() {
  const { episode_id } = useParams<{ episode_id: string }>()
  const { data, error, loading } = useFetch<EpisodeDetail>(
    episode_id ? `/api/shows/episodes/${episode_id}` : null,
  )

  if (loading) return <p className="text-muted-foreground">Loading player…</p>
  if (error) return <p className="text-destructive">Error: {error}</p>
  if (!data) {
    return <p className="text-muted-foreground">Episode not found.</p>
  }

  const { show } = data
  const [year, month] = data.aired_on.split('-')
  const filename = getEpisodeFileName(data)
  const crumbs = [
    { label: 'Stations', href: '/stations' },
    {
      label: show.station,
      href: `/stations/${encodeURIComponent(show.station)}`,
    },
    { label: show.name, href: `/shows/${show.id}` },
    { label: year, href: `/shows/${show.id}/${year}` },
    { label: month, href: `/shows/${show.id}/${year}/${month}` },
    { label: filename },
  ]

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <BreadcrumbTrail crumbs={crumbs} />
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold tracking-tight">
          {filename}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {show.name} — {data.aired_on}
        </p>
      </div>
      <EpisodePlayer episode={data} />
    </div>
  )
}
