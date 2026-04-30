export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
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
    throw new ApiError(response.status, detail)
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

export interface MonthBucket {
  year: number
  month: number
  episode_count: number
}
export interface MonthsResponse {
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
  episodes: Episode[]
}
