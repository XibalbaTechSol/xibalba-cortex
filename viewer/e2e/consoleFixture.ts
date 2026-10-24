import type { Page } from '@playwright/test'

/* A stub of the Cortex local API, shaped like the real one.
 *
 * The console destructures and iterates these payloads during render, so a thin
 * `{}` stub tears the whole tree down ("e is not iterable") and would let a
 * conformance sweep pass over an empty document. The graph payload mirrors the
 * one in src/console/model.test.ts, which was captured from a live local API. */

const T0 = Date.parse('2026-09-30T11:00:00Z')
const iso = (m: number) => new Date(T0 + m * 60_000).toISOString().replace('.000Z', 'Z')
const sqlite = (m: number) => new Date(T0 + m * 60_000).toISOString().slice(0, 19).replace('T', ' ')

export const GRAPH = {
  nodes: [
    { id: 'session:s1', type: 'session', label: 'Session s1', status: 'closed', started_at: sqlite(0) },
    { id: 'exchange:e1', type: 'exchange', label: 'Exchange 0', timestamp: iso(10) },
    { id: 'memory:m-observed', type: 'memory', label: 'observed', status: 'confirmed', evidence_class: 'policy', source_kind: 'direct_user' },
    { id: 'memory:m-ctx', type: 'memory', label: 'via exchange', status: 'active', evidence_class: 'observed_event', source_kind: 'direct_model_response' },
    { id: 'memory:m-old', type: 'memory', label: 'superseded', status: 'superseded', evidence_class: 'policy', source_kind: 'imported_document' },
    { id: 'entity:x', type: 'entity', label: 'store.py', entity_type: 'unknown', agent_id: '' },
    { id: 'merkle:sha256:abc', type: 'merkle', label: 'Root sha256:a', valid: true },
  ],
  edges: [
    { source: 'session:s1', target: 'exchange:e1', type: 'contains' },
    { source: 'exchange:e1', target: 'memory:m-ctx', type: 'prompt' },
    { source: 'session:s1', target: 'merkle:sha256:abc', type: 'merkle_root' },
    { source: 'memory:m-ctx', target: 'memory:m-observed', type: 'similarity', cosine_similarity: 0.9 },
  ],
}

const MEMORIES = GRAPH.nodes
  .filter((n) => n.type === 'memory')
  .map((n, i) => ({
    id: n.id.replace('memory:', ''), memory_id: n.id.replace('memory:', ''),
    content: `${n.label} memory body`, status: n.status, agent_id: 'xibalba.agent',
    created_at: iso(i * 5), observed_at: iso(i * 5), session_id: 's1',
    evidence_class: (n as { evidence_class?: string }).evidence_class ?? 'inference',
    source_kind: (n as { source_kind?: string }).source_kind ?? 'direct_user',
    tags: [], entities: [], attachments: [],
  }))

const SESSIONS = [{
  session_id: 's1', id: 's1', agent_id: 'xibalba.agent', runtime: 'claude-code',
  status: 'closed', started_at: iso(0), ended_at: iso(60), memory_count: MEMORIES.length,
  exchange_count: 1, merkle_root: 'sha256:abc',
}]

/** Every array-ish key the console might read, so no destructure finds undefined. */
const EMPTY_COLLECTIONS = {
  items: [], results: [], rows: [], memories: [], sessions: [], agents: [], devices: [],
  entities: [], relations: [], proposals: [], classifications: [], tasks: [], tokens: [],
  attachments: [], files: [], events: [], checkpoints: [], links: [], contradictions: [],
  channels: [], candidates: [], backups: [], models: [], total: 0, count: 0, next: null,
}

export async function stubConsoleApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })

    if (path.endsWith('/api/graph')) return json(GRAPH)
    if (path.endsWith('/api/memories')) return json({ ...EMPTY_COLLECTIONS, memories: MEMORIES, items: MEMORIES, total: MEMORIES.length })
    if (path.endsWith('/api/sessions')) return json({ ...EMPTY_COLLECTIONS, sessions: SESSIONS, items: SESSIONS, total: 1 })
    if (path.includes('/api/auth/account')) return json({ display_name: 'Operator', email: 'op@example.com', role: 'Operator' })
    if (path.includes('/api/stats') || path.includes('/api/status')) return json({ ...EMPTY_COLLECTIONS, memory_count: MEMORIES.length, session_count: 1 })
    return json(EMPTY_COLLECTIONS)
  })
}
