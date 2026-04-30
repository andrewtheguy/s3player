import type { Episode } from '@/lib/api'

const EPISODE_BASENAME_RE = /^\d{8}_\d{4}_\d{4}_(.+\.m4a)$/

export function formatTwoDigit(value: number): string {
  return String(value).padStart(2, '0')
}

export function normalizeTwoDigitPathSegment(
  value: string | undefined,
  min: number,
  max: number,
): string | null {
  if (!value) return null
  const n = Number(value)
  if (!Number.isInteger(n) || n < min || n > max) return null
  const normalized = formatTwoDigit(n)
  return value === normalized ? null : normalized
}

export function getEpisodeFileName(episode: Pick<Episode, 's3_key'>): string {
  const basename = episode.s3_key.split('/').pop() ?? episode.s3_key
  const match = EPISODE_BASENAME_RE.exec(basename)
  return match?.[1] ?? basename
}

export function getEpisodeDateParts(episode: Pick<Episode, 'aired_on'>): {
  year: string
  month: string
  day: string
} {
  const [year = '', month = '', day = ''] = episode.aired_on.split('-')
  return { year, month, day }
}

export function buildEpisodePagePath(
  episode: Episode,
  station: string,
  show: string,
): string {
  const { year, month, day } = getEpisodeDateParts(episode)
  const filename = getEpisodeFileName(episode)
  return `/shows/${encodeURIComponent(station)}/${encodeURIComponent(show)}/${year}/${month}/${day}/${encodeURIComponent(filename)}`
}
