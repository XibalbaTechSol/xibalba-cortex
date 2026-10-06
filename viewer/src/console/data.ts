// Loading for the console: the graph payload plus the extra reads needed to place nodes in time.

import { api, type GraphPayload, type Session, type Stats, type StoreStatus, type WorkspaceScope } from '../api'
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
      info.set(m.id, { observedAt: m.source?.observed_at ?? null, sessionId: m.source?.session_id ?? null })
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
  stats: Stats | null
  status: StoreStatus | null
}

export async function loadConsoleData(scope: WorkspaceScope, similarity: number): Promise<LoadedData> {
  const [graph, memories, sessions, stats, status] = await Promise.allSettled([
    api.graph(500, similarity, scope),
    loadMemoryIndex(scope),
    api.sessions(200, scope),
    api.stats(),
    api.status(),
  ])
  // The graph is the one hard requirement; everything else degrades with a stated reason.
  if (graph.status === 'rejected') throw graph.reason
  return {
    graph: graph.value,
    memories: memories.status === 'fulfilled' ? memories.value : { info: new Map(), complete: false },
    memoriesError: memories.status === 'rejected' ? String(memories.reason) : null,
    sessions: sessions.status === 'fulfilled' ? sessions.value : [],
    stats: stats.status === 'fulfilled' ? stats.value : null,
    status: status.status === 'fulfilled' ? status.value : null,
  }
}
