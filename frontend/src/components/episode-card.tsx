import { Link } from 'react-router-dom'
import type { RecentEpisode } from '@/lib/api'

interface Props {
  episode: RecentEpisode
  showProgress?: boolean
}

function formatRelative(iso: string): string {
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return ''
  const diffMs = Date.now() - ts
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}d ago`
  const week = Math.floor(day / 7)
  if (week < 5) return `${week}w ago`
  return new Date(ts).toLocaleDateString()
}

function formatTimeSlot(slot: string | null): string {
  if (!slot) return ''
  const m = /^(\d{2})(\d{2})_(\d{2})(\d{2})$/.exec(slot)
  if (!m) return slot
  return `${m[1]}:${m[2]}–${m[3]}:${m[4]}`
}

export function EpisodeCard({ episode, showProgress = false }: Props) {
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
      className="block min-w-[16rem] rounded-lg border bg-card p-4 transition-colors hover:bg-accent"
    >
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {episode.station}
      </div>
      <div className="mt-1 truncate font-medium">{episode.show_name}</div>
      <div className="mt-0.5 text-sm text-muted-foreground">
        {episode.aired_on}
        {timeSlot ? ` · ${timeSlot}` : ''}
      </div>
      {pct != null ? (
        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {Math.round(pct)}% played
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-muted-foreground">
          {episode.completed ? 'Completed' : 'Played'} ·{' '}
          {formatRelative(episode.last_played_at)}
        </div>
      )}
    </Link>
  )
}
