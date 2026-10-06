import { useEffect, useRef, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/**
 * Run `load` when `deps` change; a response from a superseded run is ignored, so a fast click
 * through several memories can never show one memory's data under another's header.
 */
export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[], options: { keepData?: boolean } = {}): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true })
  // deps are ids and plain scope objects, so a serialized key is a faithful change signal and
  // gives the effect a literal dependency array
  const key = JSON.stringify(deps)
  // the effect runs on `key`, but must call the newest closure
  const loadRef = useRef(load)
  loadRef.current = load
  const keepData = useRef(options.keepData ?? false)
  useEffect(() => {
    let live = true
    // keepData: show the last good result while the next one loads (used by the review queue)
    setState((prev) => ({ data: keepData.current ? prev.data : null, error: null, loading: true }))
    loadRef.current()
      .then((data) => {
        if (live) setState({ data, error: null, loading: false })
      })
      .catch((e: unknown) => {
        if (live) setState({ data: null, error: e instanceof Error ? e.message : String(e), loading: false })
      })
    return () => {
      live = false
    }
    // `load` closes over `deps`; callers pass exactly the values it reads, which `key` encodes.
  }, [key])
  return state
}
