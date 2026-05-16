import { useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { type PlayerSessionStatus, usePlayerSession } from '@/lib/playerSession'

const STATUS_LABEL: Record<PlayerSessionStatus, string> = {
  active: 'Active',
  pending: 'Pending',
  inactive: 'Inactive',
  displaced: 'Displaced',
  error: 'Error',
}

const STATUS_DOT: Record<PlayerSessionStatus, string> = {
  active: 'bg-green-500',
  pending: 'bg-muted-foreground',
  inactive: 'bg-muted-foreground',
  displaced: 'bg-amber-500',
  error: 'bg-destructive',
}

export function AppHeader() {
  const { status, claim } = usePlayerSession()

  // Keep the last non-pending status so the label stays stable across
  // an in-flight claim() instead of flickering.
  const lastStableStatusRef = useRef<PlayerSessionStatus>(status)
  useEffect(() => {
    if (status !== 'pending') lastStableStatusRef.current = status
  }, [status])
  const displayStatus =
    status === 'pending' ? lastStableStatusRef.current : status
  const isTakingOver = status === 'pending'
  const showTakeOver = displayStatus !== 'active'

  const handleTakeOver = useCallback(async () => {
    const result = await claim()
    if (result !== 'ok') {
      console.error('Take over session failed', { result })
    }
  }, [claim])

  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="container mx-auto flex items-center justify-between gap-3 px-6 py-3">
        <Link to="/stations" className="text-lg font-semibold tracking-tight">
          s3player
        </Link>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${STATUS_DOT[displayStatus]}`}
            />
            {STATUS_LABEL[displayStatus]}
          </span>
          {showTakeOver && (
            <button
              type="button"
              disabled={isTakingOver}
              onClick={() => {
                void handleTakeOver()
              }}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isTakingOver ? 'Taking over…' : 'Take over'}
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
