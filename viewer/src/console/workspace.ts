// Agent workspace scope for the console.
//
// Same contract as the legacy viewer, deliberately: a workspace is identified by the PAIR
// {store_id, agent_id} (an agent id alone is ambiguous across stores), a row without a verified
// store scope is never selectable (fail closed), and the selection is shared with Shield through
// the `agent_id` / `store_id` URL parameters because the two UIs run on different origins.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type AgentWorkspace, type WorkspaceScope } from '../api'

const AGENT_KEY = 'xibalba-cortex.selected-agent'
const STORE_KEY = 'xibalba-cortex.selected-store'

export const hasVerifiedStoreScope = (w: AgentWorkspace): boolean =>
  Boolean(w.store_id && w.profile_id && w.store_access && typeof w.writable === 'boolean')

/** One row per {store, agent}. When the API describes a namespace twice, prefer the writable / exactly-counted row. */
export function canonicalWorkspaces(workspaces: AgentWorkspace[]): AgentWorkspace[] {
  const canonical = new Map<string, AgentWorkspace>()
  for (const w of workspaces) {
    if (!hasVerifiedStoreScope(w)) continue
    const key = `${w.store_id}\0${w.agent_id}`
    const current = canonical.get(key)
    if (!current || (w.writable === true && current.writable !== true) || (w.memories_counted === true && current.memories_counted !== true)) {
      canonical.set(key, w)
    }
  }
  return [...canonical.values()]
}

export interface AgentOption {
  agentId: string
  storeId: string
  profileId: string
  label: string
  writable: boolean
}

export function toOptions(workspaces: AgentWorkspace[]): AgentOption[] {
  return canonicalWorkspaces(workspaces).map((w) => ({
    agentId: w.agent_id,
    storeId: w.store_id!,
    profileId: w.profile_id!,
    label: w.agent_name || w.agent_id,
    writable: w.writable === true,
  }))
}

function readInitial(): { agentId: string; storeId: string } {
  try {
    const params = new URLSearchParams(window.location.search)
    const agentId = params.get('agent_id') || ''
    const storeId = params.get('store_id') || ''
    if (agentId && storeId) return { agentId, storeId }
  } catch { /* fall through to storage */ }
  try {
    return { agentId: sessionStorage.getItem(AGENT_KEY) ?? '', storeId: sessionStorage.getItem(STORE_KEY) ?? '' }
  } catch {
    return { agentId: '', storeId: '' }
  }
}

function persist(agentId: string, storeId: string): void {
  try {
    const url = new URL(window.location.href)
    if (agentId) url.searchParams.set('agent_id', agentId); else url.searchParams.delete('agent_id')
    if (storeId) url.searchParams.set('store_id', storeId); else url.searchParams.delete('store_id')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  } catch { /* history is a convenience */ }
  try { sessionStorage.setItem(AGENT_KEY, agentId) } catch { /* storage may be blocked */ }
  try { sessionStorage.setItem(STORE_KEY, storeId) } catch { /* storage may be blocked */ }
}

export interface Workspace {
  options: AgentOption[]
  /** Passed to every scoped API call. Empty = the primary profile, read-only. */
  scope: WorkspaceScope
  selected: AgentOption | null
  /** True only for a verified, writable {store, agent} namespace. */
  canWrite: boolean
  loaded: boolean
  error: string | null
  choose: (agentId: string, storeId: string) => void
  refresh: () => void
}

export function useWorkspace(): Workspace {
  const [workspaces, setWorkspaces] = useState<AgentWorkspace[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const [chosen, setChosen] = useState(readInitial)

  useEffect(() => {
    let live = true
    api
      .agents(200)
      .then((res) => {
        if (!live) return
        setWorkspaces(res.agents)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!live) return
        setWorkspaces([])
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (live) setLoaded(true)
      })
    return () => {
      live = false
    }
  }, [nonce])

  const options = useMemo(() => toOptions(workspaces), [workspaces])

  const selected = useMemo(
    () => options.find((o) => o.agentId === chosen.agentId && o.storeId === chosen.storeId) ?? null,
    [options, chosen],
  )

  // Nothing valid selected but namespaces exist: take the first rather than leave the user in a
  // scope the server does not recognise. Nothing exists: stay unscoped (primary profile, read-only).
  useEffect(() => {
    if (!loaded || selected || options.length === 0) return
    const first = options[0]
    persist(first.agentId, first.storeId)
    setChosen({ agentId: first.agentId, storeId: first.storeId })
  }, [loaded, selected, options])

  const choose = useCallback((agentId: string, storeId: string) => {
    persist(agentId, storeId)
    setChosen({ agentId, storeId })
  }, [])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  // Keyed on the two ids, not on `selected`: a refresh re-fetches the agent list and yields a new
  // `selected` object for the SAME namespace, and a new scope identity would reset the selection
  // and re-fetch the graph for nothing.
  const selectedAgent = selected?.agentId
  const selectedStore = selected?.storeId
  const scope = useMemo<WorkspaceScope>(
    () => (selectedAgent && selectedStore ? { agentId: selectedAgent, storeId: selectedStore } : {}),
    [selectedAgent, selectedStore],
  )

  return useMemo(
    () => ({ options, scope, selected, canWrite: selected?.writable === true, loaded, error, choose, refresh }),
    [options, scope, selected, loaded, error, choose, refresh],
  )
}
