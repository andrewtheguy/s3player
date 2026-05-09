import { X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { RecentEpisode } from '@/lib/api'
import {
  formatAbsolute,
  formatPosition,
  formatRelative,
  formatTimeSlot,
} from '@/lib/format'

interface Props {
  episode: RecentEpisode
  showProgress?: boolean
  onRemove?: () => void
}

export function EpisodeCard({
  episode,
  showProgress = false,
  onRemove,
}: Props) {
  const pct =
    showProgress && episode.duration_ms != null && episode.duration_ms > 0
      ? Math.min(
          100,
          Math.max(0, (episode.position_ms / episode.duration_ms) * 100),
        )
      : null
  const timeSlot = formatTimeSlot(episode.time_slot)
  return (
    <Link
      to={`/player/${episode.id}`}
      className="relative block min-w-[16rem] rounded-lg border bg-card p-4 transition-colors hover:bg-accent"
    >
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove ${episode.show_name} from Continue listening`}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onRemove()
          }}
          className="absolute top-1.5 right-1.5 grid size-6 place-items-center rounded-full text-muted-foreground opacity-70 transition hover:bg-background hover:text-foreground hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="size-3.5" />
        </button>
      ) : null}
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {episode.station}
      </div>
      <div className="mt-1 truncate font-medium">{episode.show_name}</div>
      <div className="mt-0.5 text-sm text-muted-foreground">
        {episode.aired_on}
        {timeSlot ? ` · ${timeSlot}` : ''}
      </div>
      {pct != null && episode.duration_ms != null ? (
        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {formatPosition(episode.position_ms)} /{' '}
            {formatPosition(episode.duration_ms)}
          </div>
        </div>
      ) : (
        <div
          className="mt-3 text-xs text-muted-foreground"
          title={formatAbsolute(episode.last_played_at)}
        >
          Completed · {formatRelative(episode.last_played_at)}
        </div>
      )}
    </Link>
  )
}
