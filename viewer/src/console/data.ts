// Loading for the console: the graph payload plus the extra reads needed to place nodes in time.

import { api, type GraphPayload, type Invocation, type Session, type Stats, type StoreStatus, type WorkspaceScope } from '../api'
import type { MemoryTimeInfo } from './model'

const PAGE = 200
const MAX_PAGES = 10

export interface MemoryIndex {
  info: Map<string, MemoryTimeInfo>
  /** False when the store has more memories than MAX_PAGES * PAGE, so some are unplaced by session. */
  complete: boolean
}

/**
 * `GET /api/graph` omits `source.observed_at` and `source.session_id`, both of which the timeline
 * needs. They are on `GET /api/memories`, so page through it and index by memory id.
 */
export async function loadMemoryIndex(scope: WorkspaceScope): Promise<MemoryIndex> {
  const info = new Map<string, MemoryTimeInfo>()
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const res = await api.memories({ limit: PAGE, offset: page * PAGE, agentId: scope.agentId, storeId: scope.storeId })
    for (const m of res.memories) {
      info.set(m.id, { observedAt: m.source?.observed_at ?? null, createdAt: m.created_at ?? null, sessionId: m.source?.session_id ?? null })
    }
    if (!res.has_more) return { info, complete: true }
  }
  return { info, complete: false }
}

export interface LoadedData {
  graph: GraphPayload
  memories: MemoryIndex
  /** Set when the memory index could not be read; timing then falls back to exchanges only. */
  memoriesError: string | null
  sessions: Session[]
  /** Recent correlated tool calls, for policy interventions on the Timeline. Empty when unreadable: it is a mark layer, not a requirement. */
  invocations: Invocation[]
  stats: Stats | null
  status: StoreStatus | null
  /** Whether the workspace has at least one agent, or `null` when the listing did not answer.
   *  Drives the first-run gate in `state.tsx`; `null` deliberately does not gate. */
  hasAgents: boolean | null
}

export async function loadConsoleData(scope: WorkspaceScope, similarity: number): Promise<LoadedData> {
  const [graph, memories, sessions, stats, status, invocations, agents] = await Promise.allSettled([
    api.graph(500, similarity, scope),
    loadMemoryIndex(scope),
    api.sessions(200, scope),
    api.stats(),
    api.status(),
    api.invocations(500),
    // Only "is there at least one?" is needed, so ask for one row rather than the page the
    // Agents surface loads. Nothing here counts agents; a zero-length list is the whole signal.
    api.agents(1),
  ])
  // The graph is the one hard requirement; everything else degrades with a stated reason.
  if (graph.status === 'rejected') throw graph.reason
  return {
    graph: graph.value,
    memories: memories.status === 'fulfilled' ? memories.value : { info: new Map(), complete: false },
    memoriesError: memories.status === 'rejected' ? String(memories.reason) : null,
    sessions: sessions.status === 'fulfilled' ? sessions.value : [],
    invocations: invocations.status === 'fulfilled' && Array.isArray(invocations.value) ? invocations.value : [],
    stats: stats.status === 'fulfilled' ? stats.value : null,
    status: status.status === 'fulfilled' ? status.value : null,
    // `null` means the listing did not answer, which is not the same as "no agents". The
    // first-run gate only fires on a definite zero, so a failed request leaves the landing alone.
    hasAgents: agents.status === 'fulfilled' ? (agents.value.agents?.length ?? 0) > 0 : null,
  }
}
