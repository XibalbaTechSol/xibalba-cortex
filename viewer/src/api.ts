// Thin client for xibalba_graph.local_api (stdlib http.server, read-only, localhost:8420 by
// default). No auth, no framework response envelope -- every route just returns the JSON body
// GraphStore's own method returned, so these types mirror store.py's returned dicts directly.

const BASE_URL = import.meta.env.VITE_LOCAL_API_URL ?? 'http://localhost:8420'

export interface GraphNode {
  id: string
  type: 'memory' | 'entity'
  label: string
  status?: string
  evidence_class?: string
  source_kind?: string
  entity_type?: string
}

export interface GraphEdge {
  source: string
  target: string
  type: 'relation' | 'similarity' | 'contradiction'
  predicate?: string
  cosine_similarity?: number
  evidence_memory_id?: string
  reason?: string
}

export interface GraphPayload {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface MemorySource {
  kind: string
  locator?: string | null
  role?: string | null
  session_id?: string | null
  prompt_id?: string | null
  metadata: Record<string, unknown>
}

export interface Memory {
  id: string
  content: string
  content_hash: string
  status: string
  source: MemorySource
  quarantine_reasons: string[]
  supersedes_id: string | null
  evidence_class: string
  cosine_similarity?: number
}

export interface SimilarHit {
  memory: Memory
  cosine_similarity: number
}

export interface EntityRelation {
  subject: string
  predicate: string
  object: string
  evidence_memory_id?: string
}

export interface TraversalEdge {
  predicate: string
  object: string
  evidence_memory_id?: string
}

export interface TraversalResult {
  truncated?: boolean
  edges: TraversalEdge[]
}

export interface Stats {
  memories: number
  entities: number
  relations: number
  sessions: number
  embedded_memories: number
}

export interface StoreStatus {
  schema_version: number
  journal_mode: string
  foreign_keys: boolean
  fts5: boolean
  integrity_check: string
  identity_mode: string
  db_path: string
  memory_count: number
  backup_ready: boolean
  backup_method: string
}

export interface IntegrityLinkRecord {
  memory_id: string
  node_id: string | null
  verification_state: string
  expected_content_hash: string | null
  failure_reason: string | null
  verified_at: string | null
}

export interface IntegrityLinksStatus {
  total_memories: number
  linked_records: number
  states: Record<string, number>
  sample: IntegrityLinkRecord[]
}

export interface Session {
  id: string
  external_session_id: string
  retention_tier: string
  started_at: string
  ended_at: string | null
  summary_memory_id: string | null
}

export interface MemoryEvent {
  id: number
  event_type: string
  detail: Record<string, unknown>
  node_id: string
  parent_event_id: string | null
  created_at: string
}

export interface OtelEvent {
  id: string
  session_id: string
  kind: string
  name: string
  trace_id: string | null
  span_id: string | null
  parent_span_id: string | null
  prompt_id: string | null
  memory_id: string | null
  value: number | null
  unit: string | null
  start_time: string | null
  end_time: string | null
  attributes: Record<string, unknown>
  created_at: string
}

export interface Attachment {
  id: string
  memory_id: string
  media_type: string
  content_hash: string
  byte_size: number
  storage_locator: string
  created_at: string
}

export interface ContextContribution {
  memory: Memory
  contribution_id: string
  context_kind: string
  relevance: number | null
  metadata: Record<string, unknown>
}

export interface Exchange {
  id: string
  session_id: string
  sequence_number: number
  prompt_id: string | null
  prompt_time: string | null
  response_time: string | null
  latency_ms: number | null
  node_id: string
  parent_node_id: string | null
  prompt_memories: Memory[]
  response_memories: Memory[]
  context_contributions: ContextContribution[]
  tool_calls: OtelEvent[]
}

export interface MerkleRoot {
  session_id: string
  root_node_id: string | null
  exchange_count: number
  valid: boolean
  root_kind: string
}

export interface InferenceManifest {
  name: string
  role: string
  input_rule: string
  output_rule: string
  task_types: string[]
  tools: string[]
}

export interface InferenceTask {
  id: string
  task_type: string
  status: string
  subject_type: string
  subject_id: string
  input: Record<string, unknown>
  output: Record<string, unknown> | null
  requested_by: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface RecordModelExchangePayload {
  external_session_id: string
  user_prompt: string
  model_response: string
  context?: Array<Record<string, unknown>>
  runtime?: string
  agent_id?: string
  prompt_id?: string
  prompt_time?: string
  response_time?: string
  metadata?: Record<string, unknown>
  idempotency_key?: string
}

export interface RecordModelExchangeResult {
  session: Session
  exchange: Exchange
  prompt_memory: Memory
  response_memory: Memory
  context_memory_ids: string[]
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(body.error ?? `request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(body.error ?? `request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  stats: () => getJson<Stats>('/api/stats'),
  status: () => getJson<StoreStatus>('/api/status'),
  integrityLinks: (limit = 50) => getJson<IntegrityLinksStatus>(`/api/integrity-links?limit=${limit}`),
  sessions: (limit = 100) => getJson<Session[]>(`/api/sessions?limit=${limit}`),
  graph: (limit = 500, similarityThreshold = 0.75) =>
    getJson<GraphPayload>(`/api/graph?limit=${limit}&similarity_threshold=${similarityThreshold}`),
  search: (query: string, limit = 20) =>
    getJson<Memory[]>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  memory: (id: string) => getJson<Memory>(`/api/memory/${encodeURIComponent(id)}`),
  similar: (id: string, limit = 10) =>
    getJson<SimilarHit[]>(`/api/memory/${encodeURIComponent(id)}/similar?limit=${limit}`),
  neighbors: (id: string) => getJson<EntityRelation[]>(`/api/memory/${encodeURIComponent(id)}/neighbors`),
  memoryEvents: (id: string) => getJson<MemoryEvent[]>(`/api/memory/${encodeURIComponent(id)}/events`),
  memoryOtel: (id: string) => getJson<OtelEvent[]>(`/api/memory/${encodeURIComponent(id)}/otel`),
  attachments: (id: string) => getJson<Attachment[]>(`/api/memory/${encodeURIComponent(id)}/attachments`),
  contradictions: (id: string) => getJson<Memory[]>(`/api/memory/${encodeURIComponent(id)}/contradictions`),
  entityNeighbors: (name: string, maxDepth = 1) =>
    getJson<TraversalResult>(`/api/entity/${encodeURIComponent(name)}/neighbors?max_depth=${maxDepth}`),
  entityPath: (from: string, to: string, maxDepth = 3) =>
    getJson<TraversalResult>(`/api/entity/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&max_depth=${maxDepth}`),
  sessionExchanges: (id: string) => getJson<Exchange[]>(`/api/session/${encodeURIComponent(id)}/exchanges`),
  sessionMerkleRoot: (id: string) => getJson<MerkleRoot>(`/api/session/${encodeURIComponent(id)}/merkle-root`),
  inferenceManifest: () => getJson<InferenceManifest>('/api/inference/manifest'),
  inferenceTasks: (status = 'pending', limit = 50) =>
    getJson<InferenceTask[]>(`/api/inference/tasks?status=${encodeURIComponent(status)}&limit=${limit}`),
  recordModelExchange: (payload: RecordModelExchangePayload) =>
    postJson<RecordModelExchangeResult>('/api/exchanges/model', payload as unknown as Record<string, unknown>),
  requestInferenceTask: (payload: Record<string, unknown>) =>
    postJson<InferenceTask>('/api/inference/tasks', payload),
  createProposition: (payload: Record<string, unknown>) =>
    postJson<Memory>('/api/memory/propositions', payload),
  linkEntities: (payload: Record<string, unknown>) =>
    postJson<EntityRelation>('/api/memory/link-entities', payload),
  markContradiction: (payload: Record<string, unknown>) =>
    postJson<Record<string, unknown>>('/api/memory/contradictions', payload),
  supersedeMemory: (id: string, payload: Record<string, unknown>) =>
    postJson<Memory>(`/api/memory/${encodeURIComponent(id)}/supersede`, payload),
  claimInferenceTask: (id: string, claimedBy: string) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/claim`, { claimed_by: claimedBy }),
  completeInferenceTask: (id: string, outputPayload: Record<string, unknown>, error?: string) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/complete`, {
      output_payload: outputPayload,
      ...(error ? { error } : {}),
    }),
}
