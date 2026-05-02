import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
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

export interface PlayerSessionContextValue {
  status: PlayerSessionStatus
  error: string | null
  transientError: string | null
  claim: () => Promise<SessionWriteResult>
  validate: () => Promise<SessionWriteResult>
  postProgress: (
    episodeId: number,
    positionMs: number,
    durationMs: number | null,
  ) => Promise<SessionWriteResult>
  postComplete: (episodeId: number) => Promise<SessionWriteResult>
}

const HEARTBEAT_MS = 30_000

const PlayerSessionContext = createContext<PlayerSessionContextValue | null>(
  null,
)

export function PlayerSessionProvider({ children }: { children: ReactNode }) {
  const [initialToken] = useState<string | null>(readStoredToken)
  const tokenRef = useRef<string | null>(initialToken)
  const [status, setStatus] = useState<PlayerSessionStatus>(
    initialToken ? 'active' : 'inactive',
  )
  const [error, setError] = useState<string | null>(null)
  const [transientError, setTransientError] = useState<string | null>(null)

  // Re-entry guard: a duplicate call (double-tap, assistive tech) within the
  // render-commit window where the takeover button is still clickable returns
  // the same in-flight promise instead of issuing a second POST whose response
  // could land out of order and leave us holding a token the server already
  // displaced.
  const inflightClaimRef = useRef<Promise<SessionWriteResult> | null>(null)
  const claim = useCallback((): Promise<SessionWriteResult> => {
    if (inflightClaimRef.current) return inflightClaimRef.current
    setStatus('pending')
    const p = (async (): Promise<SessionWriteResult> => {
      try {
        const res = await playerApi.claim()
        tokenRef.current = res.session_token
        writeStoredToken(res.session_token)
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
      } finally {
        inflightClaimRef.current = null
      }
    })()
    inflightClaimRef.current = p
    return p
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
      episodeId: number,
      positionMs: number,
      durationMs: number | null,
    ): Promise<SessionWriteResult> => {
      const token = tokenRef.current
      if (!token) return 'inactive'
      try {
        await playerApi.progress(episodeId, token, positionMs, durationMs)
        setTransientError(null)
        return 'ok'
      } catch (e) {
        return handleSessionError(e)
      }
    },
    [handleSessionError],
  )

  const postComplete = useCallback(
    async (episodeId: number): Promise<SessionWriteResult> => {
      const token = tokenRef.current
      if (!token) return 'inactive'
      try {
        await playerApi.complete(episodeId, token)
        setTransientError(null)
        return 'ok'
      } catch (e) {
        return handleSessionError(e)
      }
    },
    [handleSessionError],
  )

  // Verify a rehydrated token once on mount so a stale one flips to 'displaced'
  // immediately instead of waiting for the first heartbeat. initialToken is
  // captured at mount via lazy useState, so it's stable across renders.
  useEffect(() => {
    if (initialToken) void validate()
  }, [initialToken, validate])

  // Periodic heartbeat on every screen while we hold a session. Skip ticks while
  // the tab is hidden, and re-validate immediately on hidden→visible to catch
  // displacement that happened in the background.
  useEffect(() => {
    if (status !== 'active') return
    const tick = () => {
      if (!document.hidden) void validate()
    }
    const id = window.setInterval(tick, HEARTBEAT_MS)
    const onVisibility = () => {
      if (!document.hidden) void validate()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [status, validate])

  const value: PlayerSessionContextValue = {
    status,
    error,
    transientError,
    claim,
    validate,
    postProgress,
    postComplete,
  }

  return (
    <PlayerSessionContext.Provider value={value}>
      {children}
    </PlayerSessionContext.Provider>
  )
}

export function usePlayerSession(): PlayerSessionContextValue {
  const ctx = useContext(PlayerSessionContext)
  if (ctx === null) {
    throw new Error(
      'usePlayerSession must be used within PlayerSessionProvider',
    )
  }
  return ctx
}
