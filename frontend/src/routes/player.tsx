import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { BreadcrumbTrail } from '@/components/breadcrumb-trail'
import { Slider } from '@/components/ui/slider'
import type { Chapter, Episode, EpisodeDetail } from '@/lib/api'
import { playerApi } from '@/lib/api'
import { getEpisodeFileName } from '@/lib/episode-path'
import type { PlayerSessionStatus } from '@/lib/playerSession'
import { usePlayerSession } from '@/lib/playerSession'
import { useDocumentTitle } from '@/lib/use-document-title'
import { useFetch } from '@/lib/use-fetch'

const PROGRESS_SAVE_INTERVAL_MS = 10_000

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

function findChapterIndex(chapters: Chapter[], ms: number): number {
  for (let i = 0; i < chapters.length; i++) {
    const c = chapters[i]
    if (ms >= c.start && ms < c.end) return i
  }
  return -1
}

function EpisodePlayer({ episode }: { episode: Episode }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [isLoaded, setIsLoaded] = useState(false)
  const initialPositionMsRef = useRef<number | null>(null)
  const seededInitialPosRef = useRef(false)

  const session = usePlayerSession()
  const {
    status: sessionStatus,
    error: sessionError,
    transientError: sessionTransientError,
    postProgress,
    claim,
  } = session
  const [replayConfirmNeeded, setReplayConfirmNeeded] = useState(false)
  // Progress save, replay-confirm gating, and the in-progress query all assume
  // a finite duration. Block playback for any audio whose metadata reports
  // Infinity / NaN / 0.
  const hasFiniteDuration = Number.isFinite(duration) && duration > 0
  const isUnplayable = isLoaded && !hasFiniteDuration
  const isSessionBlocked = sessionStatus !== 'active'
  const isBlocked = isSessionBlocked || replayConfirmNeeded || isUnplayable
  const isTakingOver = sessionStatus === 'pending'
  const lastStableStatusRef = useRef<PlayerSessionStatus>(sessionStatus)
  useEffect(() => {
    if (sessionStatus !== 'pending') lastStableStatusRef.current = sessionStatus
  }, [sessionStatus])
  const displayStatus =
    sessionStatus === 'pending' ? lastStableStatusRef.current : sessionStatus

  const chapters = episode.chapters ?? []
  const hasChapters = chapters.length > 0
  const [seekMode, setSeekMode] = useState<'chapter' | 'timeline'>(
    hasChapters ? 'chapter' : 'timeline',
  )
  const [selectedChapterIndex, setSelectedChapterIndex] = useState(0)
  const prevChapterIndexRef = useRef<number>(-1)

  const trySeedInitialPosition = useCallback(() => {
    if (seededInitialPosRef.current) return
    const audio = audioRef.current
    if (!audio || !Number.isFinite(audio.duration)) return
    const pos = initialPositionMsRef.current
    if (pos == null) return
    if (pos > 0) {
      const target = Math.min(pos / 1000, Math.max(0, audio.duration - 1))
      audio.currentTime = target
      setCurrentTime(target)
    }
    seededInitialPosRef.current = true
  }, [])

  // Fetch saved progress once; seek either now (if audio is loaded) or when
  // onLoadedMetadata fires. Completed episodes seed at the saved end position
  // and surface a replay-confirm gate so they don't look like a fresh episode.
  useEffect(() => {
    let cancelled = false
    playerApi
      .getProgress(episode.id)
      .then((p) => {
        if (cancelled) return
        initialPositionMsRef.current = p.position_ms
        setReplayConfirmNeeded(p.completed)
        trySeedInitialPosition()
      })
      .catch(() => {
        if (cancelled) return
        initialPositionMsRef.current = 0
        setReplayConfirmNeeded(false)
        trySeedInitialPosition()
      })
    return () => {
      cancelled = true
    }
  }, [episode.id, trySeedInitialPosition])

  const finiteDurationMs = useCallback((): number | null => {
    const audio = audioRef.current
    if (!audio) return null
    const d = audio.duration
    return Number.isFinite(d) && d > 0 ? Math.round(d * 1000) : null
  }, [])

  const saveProgress = useCallback(
    async (completed = false) => {
      const audio = audioRef.current
      if (!audio) return
      const positionMs = Math.round(audio.currentTime * 1000)
      await postProgress(episode.id, positionMs, finiteDurationMs(), completed)
    },
    [episode.id, finiteDurationMs, postProgress],
  )

  const togglePlayPause = () => {
    const audio = audioRef.current
    if (!audio) return
    if (isBlocked) return
    if (audio.paused) {
      audio.play().catch(() => {})
    } else {
      audio.pause()
    }
  }

  const seekRelative = useCallback(
    (seconds: number) => {
      const audio = audioRef.current
      if (!audio || isBlocked) return
      const target = Math.max(
        0,
        Math.min(audio.duration || 0, audio.currentTime + seconds),
      )
      audio.currentTime = target
      setCurrentTime(target)
    },
    [isBlocked],
  )

  const handleSeek = (value: number[]) => {
    const audio = audioRef.current
    const next = value[0]
    if (!audio || isBlocked || !Number.isFinite(next)) return
    audio.currentTime = next
    setCurrentTime(next)
  }

  function jumpTo(chapter: Chapter) {
    const audio = audioRef.current
    if (!audio || isBlocked) return
    audio.currentTime = chapter.start / 1000
    const idx = chapters.indexOf(chapter)
    if (idx >= 0) setSelectedChapterIndex(idx)
    audio.play().catch(() => {})
  }

  // Media Session: lock screen, AirPods, CarPlay map to ±15/30s.
  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    const s = navigator.mediaSession
    s.setActionHandler('play', () => {
      if (isBlocked) return
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
  }, [seekRelative, isBlocked])

  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: getEpisodeFileName(episode),
      artist: episode.aired_on,
    })
  }, [episode])

  const currentTimeMs = currentTime * 1000

  useEffect(() => {
    if (!hasChapters || seekMode !== 'chapter') {
      prevChapterIndexRef.current = -1
      return
    }
    const playingIdx = findChapterIndex(chapters, currentTimeMs)
    if (
      prevChapterIndexRef.current === selectedChapterIndex &&
      playingIdx !== -1 &&
      playingIdx !== selectedChapterIndex
    ) {
      setSelectedChapterIndex(playingIdx)
    }
    prevChapterIndexRef.current = playingIdx
  }, [currentTimeMs, hasChapters, seekMode, selectedChapterIndex, chapters])

  // Pause and silence MediaSession whenever this page is not the active player.
  useEffect(() => {
    if (!isBlocked) return
    audioRef.current?.pause()
    if ('mediaSession' in navigator) {
      navigator.mediaSession.playbackState = 'paused'
    }
  }, [isBlocked])

  // Periodic progress save while playing.
  useEffect(() => {
    if (!isPlaying || sessionStatus !== 'active') return
    const id = window.setInterval(() => {
      void saveProgress()
    }, PROGRESS_SAVE_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [isPlaying, sessionStatus, saveProgress])

  const handleTakeOver = useCallback(async () => {
    const result = await claim()
    if (result !== 'ok') {
      console.error('Take over playback failed', {
        episodeId: episode.id,
        result,
      })
    }
  }, [episode.id, claim])

  const handleReplayConfirm = useCallback(() => {
    const audio = audioRef.current
    if (audio) {
      audio.currentTime = 0
      setCurrentTime(0)
    }
    initialPositionMsRef.current = 0
    setReplayConfirmNeeded(false)
  }, [])

  const toggleSeekMode = () => {
    setSeekMode((prev) => {
      const next = prev === 'chapter' ? 'timeline' : 'chapter'
      if (next === 'chapter' && hasChapters) {
        const idx = findChapterIndex(chapters, currentTimeMs)
        setSelectedChapterIndex(idx >= 0 ? idx : 0)
      }
      return next
    })
  }

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
          trySeedInitialPosition()
        }}
        onPlay={(e) => {
          if (isBlocked) {
            e.currentTarget.pause()
            setIsPlaying(false)
            return
          }
          setIsPlaying(true)
        }}
        onPause={() => {
          setIsPlaying(false)
          if (sessionStatus === 'active') {
            void saveProgress()
          }
        }}
        onEnded={() => {
          setIsPlaying(false)
          if (sessionStatus === 'active') {
            void saveProgress(true)
          }
          setReplayConfirmNeeded(true)
        }}
        onSeeked={(e) => setCurrentTime(e.currentTarget.currentTime)}
      >
        <track kind="captions" />
      </audio>

      {isSessionBlocked && (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-sm">
          <p className="font-medium">
            {displayStatus === 'error'
              ? 'Playback controls unavailable'
              : displayStatus === 'displaced'
                ? 'Player active elsewhere'
                : 'Browse mode'}
          </p>
          <p className="text-muted-foreground">
            {displayStatus === 'error'
              ? `Could not start playback${
                  sessionError ? `: ${sessionError}` : ''
                }.`
              : displayStatus === 'displaced'
                ? 'Playback is active in another tab or device. Take over to play here, which will interrupt the other player.'
                : 'Playback controls are disabled until you start.'}
          </p>
          <button
            type="button"
            disabled={isTakingOver}
            onClick={() => {
              void handleTakeOver()
            }}
            className="mt-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {displayStatus === 'displaced'
              ? isTakingOver
                ? 'Taking over...'
                : 'Take over playback'
              : isTakingOver
                ? 'Starting...'
                : 'Start playback'}
          </button>
        </div>
      )}

      {!isSessionBlocked && isUnplayable && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <p className="font-medium">Cannot play this episode</p>
          <p className="text-muted-foreground">
            The audio file does not report a finite duration, so progress and
            completion can't be tracked. Playback is disabled.
          </p>
        </div>
      )}

      {!isSessionBlocked && !isUnplayable && replayConfirmNeeded && (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-sm">
          <p className="font-medium">Episode already completed</p>
          <p className="text-muted-foreground">
            You've finished this episode. Replay from the beginning to listen
            again — this resets the saved position and moves it back to Continue
            listening.
          </p>
          <button
            type="button"
            onClick={handleReplayConfirm}
            className="mt-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Replay from beginning
          </button>
        </div>
      )}

      {!isBlocked && (
        <>
          {sessionTransientError && (
            <p
              role="status"
              className="text-center text-xs text-muted-foreground"
            >
              Reconnecting… progress not saved.
            </p>
          )}
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
                className="flex items-center justify-center text-primary transition-transform hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50"
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

            {hasChapters && seekMode === 'chapter' ? (
              (() => {
                const chap = chapters[selectedChapterIndex]
                const min = chap.start / 1000
                const max = chap.end / 1000
                const inRange = currentTime >= min && currentTime < max
                const sliderValue = inRange ? currentTime : min
                const isFirst = selectedChapterIndex === 0
                const isLast = selectedChapterIndex >= chapters.length - 1
                return (
                  <div className="space-y-2">
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedChapterIndex((i) => Math.max(0, i - 1))
                        }
                        disabled={isFirst}
                        aria-label="Previous chapter"
                        title="Previous chapter"
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-transparent text-xs text-foreground transition hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-foreground"
                      >
                        ◀
                      </button>
                      <Slider
                        min={min}
                        max={max}
                        step={1}
                        value={[sliderValue]}
                        onValueChange={handleSeek}
                        disabled={!isLoaded}
                        className={`w-full ${
                          inRange
                            ? ''
                            : '[&_[data-slot=slider-thumb]]:invisible'
                        }`}
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedChapterIndex((i) =>
                            Math.min(chapters.length - 1, i + 1),
                          )
                        }
                        disabled={isLast}
                        aria-label="Next chapter"
                        title="Next chapter"
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-transparent text-xs text-foreground transition hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-foreground"
                      >
                        ▶
                      </button>
                    </div>
                    <p className="truncate text-center text-xs text-muted-foreground">
                      {chap.title || formatTimestamp(chap.start)}
                    </p>
                    <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
                      <span>{formatTime(sliderValue)}</span>
                      <span>{formatTime(max)}</span>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="button"
                        onClick={toggleSeekMode}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        Show full timeline
                      </button>
                    </div>
                  </div>
                )
              })()
            ) : (
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
                {hasChapters && (
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={toggleSeekMode}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      Show chapter view
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {episode.chapters && episode.chapters.length > 0 ? (
            <div className="max-h-[28rem] overflow-y-auto rounded-md border">
              {episode.chapters.map((c) => {
                const isCurrent =
                  currentTimeMs >= c.start && currentTimeMs < c.end
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
        </>
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
      <path d="M9.5 7.5v9l7-4.5-7-4.5z" className="fill-primary-foreground" />
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
      <rect
        x="8"
        y="7"
        width="3"
        height="10"
        rx="0.5"
        className="fill-primary-foreground"
      />
      <rect
        x="13"
        y="7"
        width="3"
        height="10"
        rx="0.5"
        className="fill-primary-foreground"
      />
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
    `/api/shows/episodes/${episode_id}`,
  )

  useDocumentTitle(data ? getEpisodeFileName(data) : 'Player')

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
      <EpisodePlayer key={data.id} episode={data} />
    </div>
  )
}
