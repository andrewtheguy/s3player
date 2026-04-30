import { type SyntheticEvent, useEffect, useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Chapter, Episode } from '@/lib/api'

interface Props {
  episode: Episode | null
  onClose: () => void
}

function formatTimestamp(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

export function PlayerDialog({ episode, onClose }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [currentTimeMs, setCurrentTimeMs] = useState(0)

  useEffect(() => {
    if (!episode) return
    setCurrentTimeMs(0)
    audioRef.current?.load()
  }, [episode])

  function jumpTo(chapter: Chapter) {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = chapter.start / 1000
    audio.play().catch(() => {})
  }

  function syncTime(e: SyntheticEvent<HTMLAudioElement>) {
    setCurrentTimeMs(e.currentTarget.currentTime * 1000)
  }

  return (
    <Dialog open={episode !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {episode ? `${episode.aired_on}` : 'Player'}
          </DialogTitle>
        </DialogHeader>
        {episode && (
          <div className="space-y-4">
            <audio
              ref={audioRef}
              src={`/api/shows/episodes/${episode.id}/audio`}
              controls
              preload="metadata"
              className="w-full"
              onTimeUpdate={syncTime}
              onSeeked={syncTime}
              onLoadedMetadata={syncTime}
            >
              {/* TODO: Add a captions src when caption assets are available from the API. */}
              <track kind="captions" />
            </audio>
            {episode.chapters && episode.chapters.length > 0 ? (
              <div className="max-h-72 overflow-y-auto rounded-md border">
                {episode.chapters.map((c) => {
                  const isCurrent =
                    currentTimeMs >= c.start && currentTimeMs < c.end
                  const rightLabel = isCurrent
                    ? formatTimestamp(c.end - currentTimeMs)
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
        )}
      </DialogContent>
    </Dialog>
  )
}
