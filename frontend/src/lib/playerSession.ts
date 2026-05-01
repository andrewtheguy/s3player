import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, playerApi } from '@/lib/api'

export type PlayerSessionStatus =
  | 'inactive'
  | 'pending'
  | 'active'
  | 'displaced'
  | 'error'

export type SessionWriteResult = 'ok' | 'inactive' | 'displaced' | 'error'

export interface UsePlayerSessionResult {
  status: PlayerSessionStatus
  error: string | null
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
  const tokenRef = useRef<string | null>(null)
  const pausedRef = useRef<boolean>(true)
  const [status, setStatus] = useState<PlayerSessionStatus>('inactive')
  const [error, setError] = useState<string | null>(null)

  const claim = useCallback(async (): Promise<SessionWriteResult> => {
    setStatus('pending')
    try {
      const res = await playerApi.claim(episodeId)
      tokenRef.current = res.session_token
      pausedRef.current = true
      setStatus('active')
      setError(null)
      return 'ok'
    } catch (e) {
      tokenRef.current = null
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
      return 'error'
    }
  }, [episodeId])

  const handleSessionError = useCallback(
    (e: unknown): 'displaced' | 'error' => {
      if (e instanceof ApiError && e.status === 409) {
        setStatus('displaced')
        setError(null)
        return 'displaced'
      }
      tokenRef.current = null
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
      return 'error'
    },
    [],
  )

  const validate = useCallback(async (): Promise<SessionWriteResult> => {
    const token = tokenRef.current
    if (!token) return 'inactive'
    try {
      await playerApi.validate(token)
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
    reclaim: claim,
    postProgress,
    postComplete,
    validate,
  }
}
