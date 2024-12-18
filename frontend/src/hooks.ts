import { useCallback, useEffect, useState } from 'react'
import { ApiError } from './api/client'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * Small data-fetching hook with loading/error state and manual reload.
 * Deliberately minimal — no external data library needed.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fn()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, loading, error, reload }
}

/** Mutation helper: tracks in-flight state + error, exposes run(). */
export function useMutation<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (...args: A): Promise<R | null> => {
      setLoading(true)
      setError(null)
      try {
        return await fn(...args)
      } catch (err: unknown) {
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err))
        return null
      } finally {
        setLoading(false)
      }
    },
    [fn],
  )

  return { run, loading, error, clearError: () => setError(null) }
}

export function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Evaluator Calibration`
  }, [title])
}
