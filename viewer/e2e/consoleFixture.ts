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
    // the Inspector elides this for display, and elideHash() on undefined is
    // what tore the whole console down on every full-page route.
    content_hash: `sha256:${String(i + 1).repeat(8)}abcdef0123456789`,
    // the Inspector reads memory.source.* unconditionally on the provenance
    // tab; without it the six full-page routes crashed on render.
    source: {
      kind: (n as { source_kind?: string }).source_kind ?? 'direct_user',
      locator: 'fixture://memory/' + i, role: 'user', agent_id: 'xibalba.agent',
      session_id: 's1', prompt_id: null, tool_name: null, exchange_id: null,
    },
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

/* The full-page surfaces (Memories, Entities, Sessions, Operations, Agents,
 * Settings) each read their own endpoint and destructure the result during
 * render, so the catch-all below is not enough for them: before these were
 * added, every one of those six routes tore the tree down and left no `.xc` at
 * all. The shapes here were taken from a live local API and refilled with
 * synthetic values -- no real DID, device name, store id or database path. */

const STATUS = {
  schema_version: 16, journal_mode: 'wal', foreign_keys: true, fts5: true,
  integrity_check: 'skipped (fast mode)', profile_id: 'default',
  canonicalization: 'xibalba.canonical-json.v1', identity_mode: 'full',
  db_path: '/tmp/fixture/graph-memory.sqlite3', memory_count: MEMORIES.length,
  memory_count_deferred: false, backup_ready: true, backup_method: 'sqlite_online_backup',
  features: {
    provenance: true, lexical: true, vector: true, inference: true, embeddings: true,
    graph: true, context_assembly: true, connectors: true, governance: true,
    telemetry: true, audit: true,
  },
  quotas: { max_memories: null },
}

const AGENT_ID = 'did:integrity:0000000000000000000000000000000000000000000000000000000000000001'

const AGENTS = {
  agents: [{
    agent_id: AGENT_ID, device_id: 'fixture-device-01', agent_name: 'fixture-agent',
    device_name: 'fixture-device-01', pair_status: 'active',
    pair_updated_at: sqlite(0), memories: MEMORIES.length, memories_counted: true,
    sessions: 1, sessions_counted: false, last_seen_at: sqlite(5),
    store_id: 'store-fixture', profile_id: 'default', store_access: 'writable',
    writable: true, did: AGENT_ID, on_chain: false, seen: true,
    handle: null, name: null, local_label: 'fixture-agent',
  }],
  oracle_reachable: false,
  primary_profile_id: 'default',
}

const AGENT_DEVICES = {
  pairs: [{
    device_id: 'fixture-device-01', agent_id: AGENT_ID,
    display_name: 'fixture-device-01', status: 'active',
    created_at: sqlite(0), updated_at: sqlite(5), last_seen_at: sqlite(5),
  }],
}

const OPERATIONS = {
  schema_version: 'xibalba.dashboard_operations.v1',
  profile_id: 'default',
  health: { state: 'healthy', status: STATUS },
  readiness: { state: 'ready', checks: { foreign_keys: true, fts5: true, backup_ready: true } },
  features: STATUS.features,
  quotas: { max_memories: null },
  embedding_coverage: {
    model: {
      model_key: 'fixture/embed@r1', model_id: 'fixture/embed', revision: 'r1',
      dimension: 384, distance_metric: 'cosine', normalize: true,
      vector_table: 'memory_vectors', state: 'active', availability: 'present',
      availability_detail: null, registered_at: sqlite(0), checked_at: null,
    },
    eligible: MEMORIES.length, current: MEMORIES.length, missing: 0, stale: 0, failed: 0,
    coverage: 1,
  },
  audit: {
    schema_version: 'xibalba.audit_report.v1', profile_id: 'default',
    memory_event_counts: { create: MEMORIES.length, forget: 0 },
    inference_task_states: { completed: 1, failed: 0, pending: 0 },
    proposal_states: {}, session_count: 1, forgotten_memory_count: 0,
    integrity_links: {
      total_memories: MEMORIES.length, linked_records: 0,
      states: { unlinked: MEMORIES.length, hash_match_local: 0, ancestry_verified: 0 },
    },
  },
  connectors: {
    hermes_sessions: { entrypoint: 'xibalba-cortex-session-sync', state: 'implemented', idempotency: 'session-and-content' },
    claude_transcripts: { entrypoint: 'xibalba-cortex-transcript-ingest', state: 'implemented', idempotency: 'file-offset-and-content' },
  },
  production: {
    state: 'local_only', active_tokens: 1, token_lifecycle: 'implemented',
    tenant_onboarding: 'implemented',
    isolation_model: 'one profile home and SQLite store per tenant',
    open_gates: ['external pilot deployment'],
  },
  disclaimer: 'Fixture data; not deployment, SLA, compliance, or pilot-readiness evidence.',
}

export async function stubConsoleApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })

    if (path.endsWith('/api/graph')) return json(GRAPH)
    /* `/api/memory/<id>` -- singular, and distinct from the plural collection above. Without it
       the catch-all answered with EMPTY_COLLECTIONS, so the Inspector got a truthy memory whose
       `content` was undefined and the console unmounted the moment a memory was selected. */
    if (path.includes('/api/memory/')) {
      const id = decodeURIComponent(path.split('/api/memory/')[1] ?? '')
      const found = MEMORIES.find((m) => m.id === id)
      if (found) return json(found)
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'not found' }) })
    }
    if (path.endsWith('/api/memories')) return json({ ...EMPTY_COLLECTIONS, memories: MEMORIES, items: MEMORIES, total: MEMORIES.length })
    // the live endpoint returns a bare array here; an object leaves Sessions
    // with nothing to iterate and unmounts the console.
    if (path.endsWith('/api/invocations')) return json([])
    if (path.endsWith('/api/profile/config')) return json({
      profile_id: 'default', mode: 'local', identity_mode: 'full', retention_tier: 'standard',
      storage: { backend: 'sqlite', pool_size: null, ssl_mode: null },
      inference: {}, embeddings: {}, retrieval: {}, features: STATUS.features,
      telemetry: {}, quotas: {}, auth: {}, remote: { configured: false },
      destinations: { backup: false, vault: false, integrity_dag: false, anchor_service: false, oracle: false },
      changed_by: 'configuration file or environment; restart required',
    })
    if (path.endsWith('/api/runtimes')) return json({ runtimes: [] })
    if (path.endsWith('/api/workers')) return json({ as_of: iso(0), workers: [], basis: 'Synthetic fixture' })
    if (path.endsWith('/api/connectors')) return json({ connectors: [], webhook_senders: [], ingest_by_source_kind: [], provider_telemetry: [], basis: 'Synthetic fixture' })
    if (path.endsWith('/api/backups')) return json({ configured: false, backups: [] })
    if (path.endsWith('/api/sessions')) return json(SESSIONS)
    if (path.includes('/api/sessions/page')) return json({ sessions: SESSIONS, offset: 0, limit: 50, has_more: false, count_status: 'exact', store_id: 'store-fixture', profile_id: 'default' })
    if (path.endsWith('/api/operations')) return json(OPERATIONS)
    if (path.endsWith('/api/agents')) return json(AGENTS)
    if (path.endsWith('/api/agent-devices')) return json(AGENT_DEVICES)
    if (path.includes('/api/auth/account')) return json({ display_name: 'Operator', email: 'op@example.com', role: 'Operator' })
    if (path.includes('/api/stats')) return json({ memories: MEMORIES.length, entities: 1, relations: 1, sessions: SESSIONS.length, embedded_memories: MEMORIES.length })
    if (path.includes('/api/status')) return json(STATUS)
    return json(EMPTY_COLLECTIONS)
  })
}
