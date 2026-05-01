export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  let detail = `HTTP ${response.status}`
  const raw = await response.text()
  if (raw) {
    try {
      const body = JSON.parse(raw) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else detail = raw
    } catch {
      detail = raw
    }
  }
  return detail
}

function redirectToLogin(): never {
  const next = window.location.pathname + window.location.search
  window.location.assign(`/login?next=${encodeURIComponent(next)}`)
  // Block the caller forever — the page is unloading.
  throw new ApiError(401, 'unauthenticated')
}

export async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (response.status === 401) redirectToLogin()
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response))
  }
  return (await response.json()) as T
}

export async function apiPostJson<T>(
  path: string,
  body: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
    body: JSON.stringify(body),
  })
  if (response.status === 401) redirectToLogin()
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response))
  }
  return (await response.json()) as T
}

export interface Station {
  id: string
  show_count: number
}
export interface StationsResponse {
  stations: Station[]
}

export interface Show {
  id: number
  name: string
  episode_count: number
}
export interface ShowsResponse {
  shows: Show[]
}

export interface ShowDetail {
  id: number
  station: string
  name: string
  episode_count: number
}

export interface MonthBucket {
  year: number
  month: number
  episode_count: number
}
export interface MonthsResponse {
  show: ShowDetail
  months: MonthBucket[]
}

export interface Chapter {
  title: string
  start: number
  end: number
}

export interface Episode {
  id: number
  aired_on: string
  time_slot: string | null
  s3_key: string
  chapters: Chapter[] | null
}
export interface EpisodesResponse {
  show: ShowDetail
  episodes: Episode[]
}

export interface EpisodeDetail extends Episode {
  show: ShowDetail
}

export interface ProgressResponse {
  position_ms: number
  duration_ms: number | null
  completed: boolean
  last_played_at?: string | null
}

export interface RecentEpisode {
  id: number
  aired_on: string
  time_slot: string | null
  show_id: number
  show_name: string
  station: string
  position_ms: number
  duration_ms: number | null
  last_played_at: string
  completed: boolean
}

export interface RecentResponse {
  episodes: RecentEpisode[]
}

export interface ClaimResponse {
  session_token: string
}

export const playerApi = {
  claim: () => apiPostJson<ClaimResponse>('/api/player/session/claim', {}),
  validate: (sessionToken: string) =>
    apiPostJson<{ status: string }>(
      '/api/player/session/validate',
      {},
      { 'X-Player-Session': sessionToken },
    ),
  progress: (
    episodeId: number,
    sessionToken: string,
    positionMs: number,
    durationMs: number | null,
  ) =>
    apiPostJson<{ status: string }>(
      `/api/player/episodes/${episodeId}/progress`,
      {
        position_ms: positionMs,
        ...(durationMs != null ? { duration_ms: durationMs } : {}),
      },
      { 'X-Player-Session': sessionToken },
    ),
  complete: (episodeId: number, sessionToken: string) =>
    apiPostJson<{ status: string }>(
      `/api/player/episodes/${episodeId}/complete`,
      {},
      { 'X-Player-Session': sessionToken },
    ),
  getProgress: (episodeId: number) =>
    apiFetch<ProgressResponse>(`/api/player/episodes/${episodeId}/progress`),
}
