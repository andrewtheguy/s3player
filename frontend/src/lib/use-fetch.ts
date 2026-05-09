import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'

interface State<T> {
  data: T | null
  error: string | null
  loading: boolean
}

interface Options {
  refreshInterval?: number
}

export function useFetch<T>(
  path: string | null,
  options: Options = {},
): State<T> {
  const { refreshInterval } = options
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    loading: path !== null,
  })

  useEffect(() => {
    let cancelled = false
    if (path === null) {
      setState({ data: null, error: null, loading: false })
      return () => {
        cancelled = true
      }
    }
    setState({ data: null, error: null, loading: true })

    const load = (isRefresh: boolean) => {
      apiFetch<T>(path)
        .then((data) => {
          if (!cancelled) setState({ data, error: null, loading: false })
        })
        .catch((e: unknown) => {
          if (cancelled) return
          const msg = e instanceof Error ? e.message : String(e)
          if (isRefresh) {
            setState((prev) => ({ ...prev, error: msg, loading: false }))
          } else {
            setState({ data: null, error: msg, loading: false })
          }
        })
    }

    load(false)

    if (refreshInterval && refreshInterval > 0) {
      const id = setInterval(() => load(true), refreshInterval)
      return () => {
        cancelled = true
        clearInterval(id)
      }
    }

    return () => {
      cancelled = true
    }
  }, [path, refreshInterval])

  return state
}
