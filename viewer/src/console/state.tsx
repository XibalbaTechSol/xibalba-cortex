// Shared console state: workspace scope, loaded data, and the UI state that must survive a lens
// switch -- the selection, the facets, and the time window. Keeping these above the lenses is what
// makes Graph and Timeline two views of one workspace rather than two tabs.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react'
import type { Session, Stats, StoreStatus } from '../api'
import { loadConsoleData } from './data'
import {
  buildModel,
  defaultFacets,
  mergeFacets,
  presetWindow,
  type Facets,
  type GraphModel,
  type MemoryTimeInfo,
  type RangePreset,
  type TimeWindow,
} from './model'
import { useWorkspace, type Workspace } from './workspace'

export type Lens = 'graph' | 'timeline'
export type Overlay = 'recall' | null
export type Preset = RangePreset | 'custom'

export interface ConsoleValue {
  workspace: Workspace
  // data
  model: GraphModel | null
  memoryInfo: ReadonlyMap<string, MemoryTimeInfo>
  /** external_session_id -> ended_at, from /api/sessions. */
  sessionEnds: ReadonlyMap<string, string | null>
  sessions: Session[]
  stats: Stats | null
  status: StoreStatus | null
  loading: boolean
  error: string | null
  /** Set when timing had to fall back to exchange timestamps only. */
  timingNote: string | null
  reload: () => void
  /** Bumps on every reload; per-item fetches key on it so they refresh after a write. */
  revision: number
  // ui
  lens: Lens
  setLens: (lens: Lens) => void
  selectedId: string | null
  select: (id: string | null) => void
  /** Select a node AND ask the graph to centre on it (used by Recall and the timeline). */
  reveal: (id: string) => void
  focus: { id: string; nonce: number } | null
  facets: Facets | null
  setFacets: Dispatch<SetStateAction<Facets | null>>
  window: TimeWindow | null
  preset: Preset
  setWindow: (window: TimeWindow | null, preset?: Preset) => void
  applyPreset: (preset: RangePreset) => void
  similarity: number
  setSimilarity: (value: number) => void
  overlay: Overlay
  setOverlay: (overlay: Overlay) => void
  /** Outcome of the last write, kept across selection changes (a supersede selects a new memory). */
  notice: string | null
  setNotice: (notice: string | null) => void
  signOut: () => void
}

const ConsoleContext = createContext<ConsoleValue | null>(null)

export function useConsole(): ConsoleValue {
  const value = useContext(ConsoleContext)
  if (!value) throw new Error('useConsole must be used inside <ConsoleProvider>')
  return value
}

function lensFromHash(): Lens {
  return window.location.hash === '#timeline' ? 'timeline' : 'graph'
}

export function ConsoleProvider({ children, onSignOut }: { children: ReactNode; onSignOut: () => void }) {
  const workspace = useWorkspace()
  const { scope, loaded } = workspace

  const [model, setModel] = useState<GraphModel | null>(null)
  const [memoryInfo, setMemoryInfo] = useState<ReadonlyMap<string, MemoryTimeInfo>>(new Map())
  const [sessionEnds, setSessionEnds] = useState<ReadonlyMap<string, string | null>>(new Map())
  const [sessions, setSessions] = useState<Session[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [status, setStatus] = useState<StoreStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [timingNote, setTimingNote] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  const [lens, setLensState] = useState<Lens>(lensFromHash)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState<{ id: string; nonce: number } | null>(null)
  const [facets, setFacets] = useState<Facets | null>(null)
  const [window_, setWindowState] = useState<TimeWindow | null>(null)
  const [preset, setPreset] = useState<Preset>('all')
  const [similarity, setSimilarity] = useState(0.75)
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Responses can arrive out of order when the scope or threshold changes quickly; only the
  // newest request may write state.
  const requestId = useRef(0)

  useEffect(() => {
    if (!loaded) return
    const mine = ++requestId.current
    setLoading(true)
    loadConsoleData(scope, similarity)
      .then((data) => {
        if (mine !== requestId.current) return
        const next = buildModel(data.graph, data.memories.info)
        setModel(next)
        setMemoryInfo(data.memories.info)
        setSessionEnds(new Map(data.sessions.map((s) => [s.external_session_id, s.ended_at])))
        setSessions(data.sessions)
        setStats(data.stats)
        setStatus(data.status)
        setError(null)
        setTimingNote(
          data.memoriesError
            ? `Memory timestamps unavailable (${data.memoriesError}); only exchanges and sessions are placed in time.`
            : data.memories.complete
              ? null
              : 'More memories than the console indexes for timing; some are shown untimed.',
        )
        const fresh = defaultFacets(next)
        setFacets((prev) => (prev ? mergeFacets(prev, fresh) : fresh))
      })
      .catch((e: unknown) => {
        if (mine !== requestId.current) return
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (mine === requestId.current) setLoading(false)
      })
  }, [loaded, scope, similarity, nonce])

  // a different workspace is a different graph: nothing selected or windowed carries over
  useEffect(() => {
    setSelectedId(null)
    setFocus(null)
    setWindowState(null)
    setPreset('all')
  }, [scope])

  useEffect(() => {
    const onHash = () => setLensState(lensFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setLens = useCallback((next: Lens) => {
    window.location.hash = next === 'graph' ? '' : `#${next}`
    setLensState(next)
  }, [])

  const select = useCallback((id: string | null) => setSelectedId(id), [])
  const reveal = useCallback((id: string) => {
    setSelectedId(id)
    setFocus((prev) => ({ id, nonce: (prev?.nonce ?? 0) + 1 }))
  }, [])

  const setWindow = useCallback((next: TimeWindow | null, nextPreset?: Preset) => {
    setWindowState(next)
    setPreset(nextPreset ?? (next ? 'custom' : 'all'))
  }, [])
  const applyPreset = useCallback((p: RangePreset) => {
    setWindowState(presetWindow(p, Date.now()))
    setPreset(p)
  }, [])

  const refreshWorkspace = workspace.refresh
  const reload = useCallback(() => {
    setNonce((n) => n + 1)
    refreshWorkspace()
  }, [refreshWorkspace])

  const value = useMemo<ConsoleValue>(
    () => ({
      workspace, model, memoryInfo, sessionEnds, sessions, stats, status, loading, error, timingNote, reload,
      lens, setLens, selectedId, select, reveal, focus, facets, setFacets,
      window: window_, preset, setWindow, applyPreset, similarity, setSimilarity, overlay, setOverlay,
      revision: nonce, notice, setNotice,
      signOut: onSignOut,
    }),
    [workspace, model, memoryInfo, sessionEnds, sessions, stats, status, loading, error, timingNote, reload,
      lens, setLens, selectedId, select, reveal, focus, facets, window_, preset, setWindow, applyPreset,
      similarity, overlay, onSignOut, nonce, notice],
  )

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>
}
