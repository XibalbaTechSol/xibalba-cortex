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
// the person chose the profile's own memories (no agent namespace) on purpose; without this the
// first agent workspace is selected automatically whenever one exists
const PRIMARY_KEY = 'xibalba-cortex.selected-primary'

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
  /** The server counted this namespace and found no memories (e.g. a device paired before its first write). */
  knownEmpty: boolean
}

export const HEALTHCARE_RESEARCHER_DID = 'did:integrity:healthcare-researcher-latent-space-01'

export const HEALTHCARE_RESEARCHER_DEMO_OPTION: AgentOption = {
  agentId: HEALTHCARE_RESEARCHER_DID,
  storeId: 'store-healthcare-researcher',
  profileId: 'demo-healthcare',
  label: '🩺 Healthcare Researcher (Latent Medical Space Demo)',
  writable: false,
  knownEmpty: false,
}

export function toOptions(workspaces: AgentWorkspace[]): AgentOption[] {
  const options = canonicalWorkspaces(workspaces).map((w) => {
    const isDemo = w.agent_id === HEALTHCARE_RESEARCHER_DID || w.agent_id === 'demo-healthcare-researcher'
    return {
      agentId: isDemo ? HEALTHCARE_RESEARCHER_DID : w.agent_id,
      storeId: w.store_id!,
      profileId: w.profile_id!,
      label: isDemo ? '🩺 Healthcare Researcher (Latent Medical Space Demo)' : (w.agent_name || w.agent_id),
      writable: isDemo ? false : w.writable === true,
      knownEmpty: isDemo ? false : (w.memories_counted === true && w.memories === 0),
    }
  })
  if (!options.some((o) => o.agentId === HEALTHCARE_RESEARCHER_DID || o.agentId === 'demo-healthcare-researcher')) {
    const defaultStoreId = options[0]?.storeId || HEALTHCARE_RESEARCHER_DEMO_OPTION.storeId
    const defaultProfileId = options[0]?.profileId || HEALTHCARE_RESEARCHER_DEMO_OPTION.profileId
    options.push({
      ...HEALTHCARE_RESEARCHER_DEMO_OPTION,
      storeId: defaultStoreId,
      profileId: defaultProfileId,
    })
  }
  return options
}

/** The workspace to open when nothing is chosen yet: the first that may hold memories, so the
 * console does not land on an empty namespace when a populated one exists. */
export function defaultOption(options: AgentOption[]): AgentOption | undefined {
  const userOptions = options.filter((o) => o.agentId !== HEALTHCARE_RESEARCHER_DID && o.agentId !== 'demo-healthcare-researcher')
  if (userOptions.length > 0) {
    return userOptions.find((o) => !o.knownEmpty) ?? userOptions[0]
  }
  return options.find((o) => !o.knownEmpty) ?? options[0]
}

function readStorage(key: string): string | null {
  try {
    const local = window.localStorage?.getItem(key)
    if (local !== null && local !== undefined) return local
    return window.sessionStorage?.getItem(key) ?? null
  } catch {
    return null
  }
}

function readInitial(): { agentId: string; storeId: string } {
  try {
    const params = new URLSearchParams(window.location.search)
    const agentId = params.get('agent_id') || ''
    const storeId = params.get('store_id') || ''
    if (agentId && storeId) return { agentId, storeId }
  } catch { /* fall through to storage */ }
  try {
    return { agentId: readStorage(AGENT_KEY) ?? '', storeId: readStorage(STORE_KEY) ?? '' }
  } catch {
    return { agentId: '', storeId: '' }
  }
}

function readPrimary(): boolean {
  try {
    return readStorage(PRIMARY_KEY) === '1'
  } catch {
    return false
  }
}

function persistPrimary(value: boolean): void {
  try {
    if (value) {
      window.localStorage?.setItem(PRIMARY_KEY, '1')
      window.sessionStorage?.setItem(PRIMARY_KEY, '1')
    } else {
      window.localStorage?.removeItem(PRIMARY_KEY)
      window.sessionStorage?.removeItem(PRIMARY_KEY)
    }
  } catch { /* storage may be blocked */ }
}

function persist(agentId: string, storeId: string): void {
  try {
    const url = new URL(window.location.href)
    if (agentId) url.searchParams.set('agent_id', agentId); else url.searchParams.delete('agent_id')
    if (storeId) url.searchParams.set('store_id', storeId); else url.searchParams.delete('store_id')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  } catch { /* history is a convenience */ }
  try {
    window.localStorage?.setItem(AGENT_KEY, agentId)
    window.sessionStorage?.setItem(AGENT_KEY, agentId)
  } catch { /* storage may be blocked */ }
  try {
    window.localStorage?.setItem(STORE_KEY, storeId)
    window.sessionStorage?.setItem(STORE_KEY, storeId)
  } catch { /* storage may be blocked */ }
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
  /** The profile's own memories, with no agent namespace, chosen on purpose. Always read-only. */
  primary: boolean
  choose: (agentId: string, storeId: string) => void
  choosePrimary: () => void
  refresh: () => void
}

export function useWorkspace(): Workspace {
  const [workspaces, setWorkspaces] = useState<AgentWorkspace[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const [chosen, setChosen] = useState(readInitial)
  const [primary, setPrimary] = useState(readPrimary)

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
    () => (primary ? null : options.find((o) => o.agentId === chosen.agentId && o.storeId === chosen.storeId) ?? null),
    [options, chosen, primary],
  )

  // Nothing valid selected but namespaces exist: take the default rather than leave the user in a
  // scope the server does not recognise. Nothing exists: stay unscoped (primary profile, read-only).
  useEffect(() => {
    if (!loaded || selected || primary || options.length === 0) return
    const first = defaultOption(options)!
    persist(first.agentId, first.storeId)
    setChosen({ agentId: first.agentId, storeId: first.storeId })
  }, [loaded, selected, primary, options])

  const choose = useCallback((agentId: string, storeId: string) => {
    persistPrimary(false)
    setPrimary(false)
    persist(agentId, storeId)
    setChosen({ agentId, storeId })
  }, [])

  const choosePrimary = useCallback(() => {
    persistPrimary(true)
    setPrimary(true)
    persist('', '')
    setChosen({ agentId: '', storeId: '' })
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
    () => ({ options, scope, selected, primary, canWrite: selected?.writable === true, loaded, error, choose, choosePrimary, refresh }),
    [options, scope, selected, primary, loaded, error, choose, choosePrimary, refresh],
  )
}
