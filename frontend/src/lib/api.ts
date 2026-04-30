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
    try {
      const body = (await response.json()) as { detail?: string }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      detail = (await response.text()) || detail
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

export interface Episode {
  id: number
  aired_on: string
  time_slot: string | null
  s3_key: string
}
export interface EpisodesResponse {
  episodes: Episode[]
}

export interface PresignedUrlResponse {
  url: string
  expires_in: number
}
