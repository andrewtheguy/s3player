import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, playerApi } from '@/lib/api'

// Global per tab — the backend session row is single-row, not scoped per episode.
const STORAGE_KEY = 's3player.session_token'

function readStoredToken(): string | null {
  try {
    const v = sessionStorage.getItem(STORAGE_KEY)
    return v && v.length > 0 ? v : null
  } catch {
    return null
  }
}

function writeStoredToken(token: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, token)
  } catch {}
}

function clearStoredToken(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {}
}

export type PlayerSessionStatus =
  | 'inactive'
  | 'pending'
  | 'active'
  | 'displaced'
  | 'error'

export type SessionWriteResult =
  | 'ok'
  | 'inactive'
  | 'displaced'
  | 'transient'
  | 'error'

export interface UsePlayerSessionResult {
  status: PlayerSessionStatus
  error: string | null
  transientError: string | null
  reclaim: () => Promise<SessionWriteResult>
  postProgress: (
    positionMs: number,
    durationMs: number | null,
    options?: { paused?: boolean },
  ) => Promise<SessionWriteResult>
  postComplete: () => Promise<SessionWriteResult>
  validate: () => Promise<SessionWriteResult>
}

const PAUSED_PING_MS = 30_000

export function usePlayerSession(episodeId: number): UsePlayerSessionResult {
  const initialToken = readStoredToken()
  const tokenRef = useRef<string | null>(initialToken)
  const pausedRef = useRef<boolean>(true)
  const [status, setStatus] = useState<PlayerSessionStatus>(
    initialToken ? 'active' : 'inactive',
  )
  const [error, setError] = useState<string | null>(null)
  const [transientError, setTransientError] = useState<string | null>(null)

  const claim = useCallback(async (): Promise<SessionWriteResult> => {
    setStatus('pending')
    try {
      const res = await playerApi.claim()
      tokenRef.current = res.session_token
      writeStoredToken(res.session_token)
      pausedRef.current = true
      setStatus('active')
      setError(null)
      setTransientError(null)
      return 'ok'
    } catch (e) {
      tokenRef.current = null
      clearStoredToken()
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
      return 'error'
    }
  }, [])

  // 409 is the only authoritative "session gone" signal; everything else is transient.
  const handleSessionError = useCallback(
    (e: unknown): 'displaced' | 'transient' | 'error' => {
      if (e instanceof ApiError && e.status === 409) {
        tokenRef.current = null
        clearStoredToken()
        setStatus('displaced')
        setError(null)
        setTransientError(null)
        return 'displaced'
      }
      const message = e instanceof Error ? e.message : String(e)
      if (tokenRef.current != null) {
        setTransientError(message)
        return 'transient'
      }
      setStatus('error')
      setError(message)
      return 'error'
    },
    [],
  )

  const validate = useCallback(async (): Promise<SessionWriteResult> => {
    const token = tokenRef.current
    if (!token) return 'inactive'
    try {
      await playerApi.validate(token)
      setTransientError(null)
      return 'ok'
    } catch (e) {
      return handleSessionError(e)
    }
  }, [handleSessionError])

  const postProgress = useCallback(
    async (
      positionMs: number,
      durationMs: number | null,
      options?: { paused?: boolean },
    ): Promise<SessionWriteResult> => {
      const token = tokenRef.current
      if (!token) return 'inactive'
      pausedRef.current = options?.paused ?? false
      try {
        await playerApi.progress(episodeId, token, positionMs, durationMs)
        setTransientError(null)
        return 'ok'
      } catch (e) {
        return handleSessionError(e)
      }
    },
    [episodeId, handleSessionError],
  )

  const postComplete = useCallback(async (): Promise<SessionWriteResult> => {
    const token = tokenRef.current
    if (!token) return 'inactive'
    try {
      await playerApi.complete(episodeId, token)
      setTransientError(null)
      return 'ok'
    } catch (e) {
      return handleSessionError(e)
    }
  }, [episodeId, handleSessionError])

  // Ping while paused; the active stream of progress writes covers the playing case.
  useEffect(() => {
    if (status !== 'active') return
    const id = window.setInterval(() => {
      if (!pausedRef.current) return
      void validate()
    }, PAUSED_PING_MS)
    return () => window.clearInterval(id)
  }, [status, validate])

  return {
    status,
    error,
    transientError,
    reclaim: claim,
    postProgress,
    postComplete,
    validate,
  }
}
