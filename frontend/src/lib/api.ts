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

export async function apiDelete<T>(
  path: string,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: headers ?? {},
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
  is_favorite: boolean
}
export interface ShowsResponse {
  shows: Show[]
}

export interface FavoriteShow {
  id: number
  station: string
  name: string
  episode_count: number
  favorited_at: string
  latest_aired_on: string | null
}
export interface FavoritesResponse {
  favorites: FavoriteShow[]
}

export interface ShowEpisode {
  id: number
  aired_on: string
  time_slot: string | null
  show_id: number
  show_name: string
  station: string
  position_ms: number
  duration_ms: number | null
  completed: boolean
  last_played_at: string | null
}
export interface RecentShowEpisodesResponse {
  show: ShowDetail
  episodes: ShowEpisode[]
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

export interface ChapterSummary {
  // Parsed from the source filename `chapter_NN.md` — 1-based under the
  // canonical naming (the first chapter is `chapter_01.md`).
  index: number
  content: string
}
export interface ChapterSummariesResponse {
  summaries: ChapterSummary[]
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
}

export interface RecentResponse {
  episodes: RecentEpisode[]
}

export interface ClaimResponse {
  session_token: string
}

export const showsApi = {
  listFavorites: () => apiFetch<FavoritesResponse>('/api/shows/favorites'),
  addFavorite: (id: number) =>
    apiPostJson<{ status: string }>(`/api/shows/${id}/favorite`, {}),
  removeFavorite: (id: number) =>
    apiDelete<{ status: string }>(`/api/shows/${id}/favorite`),
  recentEpisodes: (id: number, limit = 20) =>
    apiFetch<RecentShowEpisodesResponse>(
      `/api/shows/${id}/recent-episodes?limit=${limit}`,
    ),
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
    completed: boolean,
  ) =>
    apiPostJson<{ status: string }>(
      `/api/player/episodes/${episodeId}/progress`,
      {
        position_ms: positionMs,
        ...(durationMs != null ? { duration_ms: durationMs } : {}),
        completed,
      },
      { 'X-Player-Session': sessionToken },
    ),
  getProgress: (episodeId: number) =>
    apiFetch<ProgressResponse>(`/api/player/episodes/${episodeId}/progress`),
  deleteProgress: (episodeId: number, sessionToken: string) =>
    apiDelete<{ status: string }>(
      `/api/player/episodes/${episodeId}/progress`,
      { 'X-Player-Session': sessionToken },
    ),
}
