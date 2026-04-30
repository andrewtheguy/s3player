import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'

interface State<T> {
  data: T | null
  error: string | null
  loading: boolean
}

export function useFetch<T>(path: string | null): State<T> {
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
    apiFetch<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : String(e)
        setState({ data: null, error: msg, loading: false })
      })
    return () => {
      cancelled = true
    }
  }, [path])

  return state
}
