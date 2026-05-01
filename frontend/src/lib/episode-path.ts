import type { Episode } from '@/lib/api'

const EPISODE_BASENAME_RE = /^\d{8}_\d{4}_\d{4}_(.+\.m4a)$/

export function formatTwoDigit(value: number): string {
  return String(value).padStart(2, '0')
}

export function validateTwoDigitPathSegment(
  value: string | undefined,
  min: number,
  max: number,
): string | null {
  if (!value) return null
  if (!/^\d{2}$/.test(value)) return null
  const n = Number(value)
  if (!Number.isInteger(n) || n < min || n > max) return null
  return value
}

export function getEpisodeFileName(episode: Pick<Episode, 's3_key'>): string {
  const basename = episode.s3_key.split('/').pop() ?? episode.s3_key
  const match = EPISODE_BASENAME_RE.exec(basename)
  return match?.[1] ?? basename
}
