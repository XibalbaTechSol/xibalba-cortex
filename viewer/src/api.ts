// Thin client for xibalba_cortex.local_api (stdlib http.server, localhost:8420 by default). No
// framework response envelope -- every route just returns the JSON body GraphStore's own method
// returned, so these types mirror store.py's returned dicts directly.
//
// local_api.py authenticates the browser with an HttpOnly, Secure, SameSite=Strict session
// cookie set at sign-in. The token is never readable from JavaScript and is never held in
// sessionStorage, so an XSS bug cannot exfiltrate it. Every request below therefore sends
// `credentials: 'include'` and carries no Authorization header. Bearer tokens remain in
// local_api.py for machine callers (MCP, CLI, workers) that cannot hold a cookie.

// Production defaults to the page's own origin: Caddy serves the viewer and proxies /api/* to
// local_api.py, which is what lets the Secure, SameSite=Strict cookie be stored and sent back. A
// cross-origin default (e.g. http://localhost:8420) would be blocked by CORS for credentialed
// requests and as mixed content under HTTPS. Same model as the Shield UI.
const DEFAULT_BASE_URL = import.meta.env.VITE_LOCAL_API_URL ?? (import.meta.env.DEV ? '/cortex-api' : '')
const SIGNED_IN_KEY = 'xibalba-cortex.signed-in'
const URL_STORAGE_KEY = 'xibalba-cortex.local-api-url'
// Non-secret UI hint only: the real credential is the HttpOnly cookie, which this code cannot
// read. This just lets the app render the authenticated shell without a round-trip first; any
// stale value is corrected by the next 401.
let signedIn = sessionStorage.getItem(SIGNED_IN_KEY) === '1'
let apiBaseUrl = sessionStorage.getItem(URL_STORAGE_KEY) ?? DEFAULT_BASE_URL

export function isSignedIn(): boolean {
  return signedIn
}

function markSignedIn(value: boolean): void {
  signedIn = value
  if (value) sessionStorage.setItem(SIGNED_IN_KEY, '1')
  else sessionStorage.removeItem(SIGNED_IN_KEY)
}

export function getApiBaseUrl(): string {
  return apiBaseUrl
}

export function setApiBaseUrl(value: string): void {
  const normalized = value.trim().replace(/\/+$/, '') || DEFAULT_BASE_URL
  apiBaseUrl = normalized
  sessionStorage.setItem(URL_STORAGE_KEY, normalized)
}

export async function accountAuth(path: "signup" | "login", input: Record<string, string>): Promise<{account: Record<string, unknown>}> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/" + path, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
  markSignedIn(true)
  return payload
}

export async function accountMe(): Promise<{account: Record<string, unknown>; session_expires_at?: string | null}> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/me", { credentials: "include" })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
  return payload
}

export async function accountSessions(): Promise<{sessions: Array<Record<string, unknown>>}> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/sessions", { credentials: "include" })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
  return payload
}

export async function accountRevokeSession(sessionId: string): Promise<void> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/sessions/revoke", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
}

export async function accountEvents(): Promise<{events: Array<Record<string, unknown>>}> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/events", { credentials: "include" })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
  return payload
}

export async function accountLogout(): Promise<void> {
  // Always call the server: it owns the session record and the cookie, and this client cannot
  // tell whether a cookie is present.
  await fetch(getApiBaseUrl() + "/api/auth/logout", { method: "POST", credentials: "include" })
  markSignedIn(false)
}

export async function accountChangePassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/password", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
}

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
  agent_id?: string | null
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
  memories: number | null
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
  agent_id?: string | null
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

export interface SessionReplayEvent {
  replay_index: number
  event_type: "prompt" | "tool_call" | "tool_result" | "response"
  role: string
  memory_id?: string
  content?: string
  meta_json?: { summary?: string; [key: string]: any }
  meta_status?: string
  relevance_score?: number
  tool_name?: string
  tool_input?: unknown
  tool_output?: unknown
  timestamp: string | null
  end_timestamp?: string | null
  timestamp_source: string
  prompt_id: string | null
}

export interface SessionReplay {
  schema_version: string
  exchange_count: number
  event_count: number
  events: SessionReplayEvent[]
  replayable: boolean
  completeness: { status: string; missing: Array<Record<string, unknown>>; exchange_chain: Record<string, unknown> }
  disclaimer: string
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
  claim_owner: string | null
  claim_token: string | null
  lease_expires_at: string | null
  attempt_count: number
  error: string | null
  created_at: string
  updated_at: string
}

export interface ParaClassification {
  task_id: string
  memory_id: string
  source_content_hash: string
  category: 'project' | 'area' | 'resource' | 'archive'
  confidence: number
  rationale: string
  signals: string[]
  alternatives: string[]
  status: 'proposed' | 'accepted' | 'dismissed' | 'kept_original' | 'stale'
  decision_note: string | null
  created_at: string
  decided_at: string | null
}

export interface ExtractionProposal {
  id: string
  task_id: string
  task_type: string
  item_index: number
  source_memory_id: string
  source_content_hash: string
  payload: Record<string, unknown>
  evidence_quote: string | null
  status: 'proposed' | 'accepted' | 'dismissed' | 'stale'
  decision_note: string | null
  decided_by: string | null
  created_at: string
  decided_at: string | null
}

export interface RetrievalTraceChannelResult {
  rank: number
  raw_score: number | null
}

export interface RetrievalTraceResultRecord {
  rank: number
  memory_id: string
  score: number
  signals: string[]
  channels: Record<string, RetrievalTraceChannelResult>
  cosine_similarity: number | null
  provenance: { content_hash: string; source_id: string; evidence_class: string; status: string }
}

export interface RetrievalTrace {
  id: string
  query: string
  signals: string[]
  results: RetrievalTraceResultRecord[]
  root_hash: string
  profile_domain: string
  query_vector_hash: string | null
  embedding_model_id: string | null
  embedding_model_revision: string | null
  filters: Record<string, unknown>
  candidate_pool_sizes: Record<string, number>
  rrf_params: { method: string; k: number; weights: Record<string, number> }
  graph_evidence: Array<Record<string, unknown>>
  leaf_hashes: string[]
  degraded: Array<Record<string, unknown>>
  checkpoint_id: string | null
  linked_task_id: string | null
  linked_session_id: string | null
  created_at: string
}

export interface MerkleInclusionProof {
  domain: string
  index: number
  payload_hash: string
  siblings: Array<{ hash: string }>
  root: string
}

export interface HybridRetrieveResult {
  trace_id: string
  root_hash: string
  signals: string[]
  channel_status: Record<string, string>
  degraded: Array<Record<string, unknown>>
  results: Memory[]
}

export interface ProjectionCheckpoint {
  id: string
  projection_id: string
  root_hash: string
  leaf_count: number
  leaf_hashes: string[]
  metadata: Record<string, unknown>
  status: 'active' | 'degraded' | 'unavailable'
  created_at: string
}

export interface ProjectionReconciliation {
  id: string
  projection_id: string
  checkpoint_id: string
  canonical_root_hash: string
  observed_root_hash: string
  equal: boolean
  reordered: boolean
  missing: string[]
  extra: string[]
  action: 'noop' | 'rebuild_projection' | 'mark_degraded' | 'manual_review'
}

export interface EmbeddingModel {
  model_key: string
  model_id: string
  revision: string
  dimension: number
  distance_metric: string
  normalize: boolean
  vector_table: string
  state: 'active' | 'shadow' | 'deprecated' | 'failed'
  availability: string
  availability_detail: string | null
  registered_at: string
  checked_at: string | null
}

export interface InferenceSettings {
  enabled: boolean
  provider: string
  harness: string
  profile_name: string
  allow_fallback: boolean
  task_types: string[]
  batch_size: number
  interval_seconds: number
  max_attempts: number
  timeout_seconds: number
  max_parallel_families: number
  combined_batching: boolean
  max_evidence_chars_per_memory: number
  max_items_per_type: number
  human_review_confidence_threshold: number
  task_confidence_thresholds: Record<string, number>
  promotion_policy: 'confidence_gated' | 'review_required'
  contradictions_require_review: boolean
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

export interface OperationsSnapshot {
  schema_version: string
  profile_id: string
  health: { state: string; status: StoreStatus }
  readiness: { state: string; checks: Record<string, boolean> }
  features: Record<string, boolean>
  quotas: Record<string, number | null>
  embedding_coverage: Record<string, unknown>
  audit: Record<string, unknown>
  connectors: Record<string, { entrypoint: string; state: string; idempotency?: string; requirement?: string }>
  production: { state: string; active_tokens: number; token_lifecycle: string; tenant_onboarding: string; isolation_model: string; open_gates: string[] }
  disclaimer: string
}

export interface AgentWorkspace {
  agent_id: string
  device_id?: string | null
  agent_name?: string | null
  device_name?: string | null
  pair_status?: 'active' | 'detached' | 'revoked' | null
  pair_updated_at?: string | null
  memories: number
  /** False means the API skipped an expensive count; zero is not a measured total. */
  memories_counted?: boolean
  sessions: number
  last_seen_at?: string | null
  /** Standardized 2026-09-13 identity fields (integrity_sdk.agent_identity, same contract
   *  Shield and the dashboard use). integrity_sdk's resolver fails open on an unreachable
   *  oracle -- it still returns on_chain: false rather than omitting the field -- so
   *  `identity_verified` is the honest signal for whether that false actually means
   *  "confirmed off-chain" or "couldn't check." Never render on_chain/wallet_address as
   *  confirmed when identity_verified is false. */
  on_chain?: boolean
  wallet_address?: string | null
  identity_verified?: boolean
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, { credentials: "include" })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(body.error ?? `request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(body.error ?? `request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

async function getBlob(path: string): Promise<Blob> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, { credentials: "include" })
  if (!response.ok) throw new Error(`request failed: ${response.status}`)
  return response.blob()
}

export const api = {
  stats: () => getJson<Stats>('/api/stats'),
  status: () => getJson<StoreStatus>('/api/status'),
  operations: () => getJson<OperationsSnapshot>('/api/operations'),
  integrityLinks: (limit = 50) => getJson<IntegrityLinksStatus>(`/api/integrity-links?limit=${limit}`),
  sessions: (limit = 100, agentId?: string) => getJson<Session[]>(`/api/sessions?limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ''}`),
  agents: (limit = 100) => getJson<{agents: AgentWorkspace[]; oracle_reachable: boolean}>(`/api/agents?limit=${limit}`),
  agentMemories: (agentId: string, deviceId?: string, limit = 100) => getJson<{agent_id: string; memories: Memory[]}>(`/api/agent/${encodeURIComponent(agentId)}/memories?limit=${limit}${deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : ''}`),
  associateAgentDevice: (agentId: string, deviceId: string, displayName?: string) =>
    postJson<AgentWorkspace>('/api/agent-devices/associate', { agent_id: agentId, device_id: deviceId, display_name: displayName || deviceId }),
  renameAgentDevice: (deviceId: string, displayName: string) =>
    postJson<AgentWorkspace>(`/api/agent-devices/${encodeURIComponent(deviceId)}/rename`, { display_name: displayName }),
  detachAgentDevice: (deviceId: string) =>
    postJson<AgentWorkspace>(`/api/agent-devices/${encodeURIComponent(deviceId)}/detach`, {}),
  revokeAgentDevice: (deviceId: string) =>
    postJson<AgentWorkspace>(`/api/agent-devices/${encodeURIComponent(deviceId)}/revoke`, {}),
  graph: (limit = 500, similarityThreshold = 0.75, agentId?: string) =>
    getJson<GraphPayload>(`/api/graph?limit=${limit}&similarity_threshold=${similarityThreshold}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ''}`),
  search: (query: string, limit = 20, agentId?: string) =>
    getJson<Memory[]>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ''}`),
  memories: (opts: { limit?: number; offset?: number; statuses?: string[]; agentId?: string } = {}) => {
    const { limit = 50, offset = 0, statuses, agentId } = opts
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (statuses?.length) params.set('status', statuses.join(','))
    if (agentId) params.set('agent_id', agentId)
    return getJson<{ memories: Memory[]; has_more: boolean; offset: number; limit: number }>(`/api/memories?${params.toString()}`)
  },
  memory: (id: string) => getJson<Memory>(`/api/memory/${encodeURIComponent(id)}`),
  similar: (id: string, limit = 10) =>
    getJson<SimilarHit[]>(`/api/memory/${encodeURIComponent(id)}/similar?limit=${limit}`),
  neighbors: (id: string) => getJson<EntityRelation[]>(`/api/memory/${encodeURIComponent(id)}/neighbors`),
  memoryEvents: (id: string) => getJson<MemoryEvent[]>(`/api/memory/${encodeURIComponent(id)}/events`),
  memoryOtel: (id: string) => getJson<OtelEvent[]>(`/api/memory/${encodeURIComponent(id)}/otel`),
  attachments: (id: string) => getJson<Attachment[]>(`/api/memory/${encodeURIComponent(id)}/attachments`),
  attachmentFile: (id: string) => getBlob(`/api/attachment/${encodeURIComponent(id)}/file`),
  contradictions: (id: string) => getJson<Memory[]>(`/api/memory/${encodeURIComponent(id)}/contradictions`),
  entityNeighbors: (name: string, maxDepth = 1) =>
    getJson<TraversalResult>(`/api/entity/${encodeURIComponent(name)}/neighbors?max_depth=${maxDepth}`),
  entityPath: (from: string, to: string, maxDepth = 3) =>
    getJson<TraversalResult>(`/api/entity/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&max_depth=${maxDepth}`),
  sessionReplay: (id: string) => getJson<SessionReplay>(`/api/session/${encodeURIComponent(id)}/replay`),
  sessionExchanges: (id: string) => getJson<Exchange[]>(`/api/session/${encodeURIComponent(id)}/exchanges`),
  buildSessionExchanges: (id: string) => postJson(`/api/session/${encodeURIComponent(id)}/exchanges/build`, {}),
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
  forgetMemory: (id: string) =>
    postJson<Memory & { content_hash_retained: boolean; deletion_receipt: Record<string, unknown> }>(`/api/memory/${encodeURIComponent(id)}/forget`, {}),
  claimInferenceTask: (id: string, claimedBy: string) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/claim`, { claimed_by: claimedBy }),
  completeInferenceTask: (id: string, outputPayload: Record<string, unknown>, error?: string, claimedBy?: string | null, claimToken?: string | null) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/complete`, {
      output_payload: outputPayload,
      ...(error ? { error } : {}),
      ...(claimedBy ? { claimed_by: claimedBy } : {}),
      ...(claimToken ? { claim_token: claimToken } : {}),
    }),
  paraClassifications: (status = 'proposed', limit = 50) =>
    getJson<ParaClassification[]>(`/api/para/classifications?status=${encodeURIComponent(status)}&limit=${limit}`),
  decidePara: (taskId: string, decision: 'accept' | 'dismiss' | 'keep_original', note?: string) =>
    postJson<ParaClassification>(`/api/para/classifications/${encodeURIComponent(taskId)}/decision`, {
      decision,
      ...(note ? { note } : {}),
    }),
  extractionProposals: (status = 'proposed', limit = 50, taskId?: string, sourceMemoryId?: string) =>
    getJson<ExtractionProposal[]>(
      `/api/extraction-proposals?status=${encodeURIComponent(status)}&limit=${limit}` +
        (taskId ? `&task_id=${encodeURIComponent(taskId)}` : '') +
        (sourceMemoryId ? `&source_memory_id=${encodeURIComponent(sourceMemoryId)}` : ''),
    ),
  decideExtractionProposal: (proposalId: string, decision: 'accept' | 'dismiss', decidedBy?: string, note?: string) =>
    postJson<ExtractionProposal>(`/api/extraction-proposals/${encodeURIComponent(proposalId)}/decision`, {
      decision,
      ...(decidedBy ? { decided_by: decidedBy } : {}),
      ...(note ? { note } : {}),
    }),
  hybridRetrieve: (payload: {
    query: string
    limit?: number
    temporal_at?: string
    filters?: Record<string, unknown>
    max_per_source?: number
    max_total_chars?: number
  }) => postJson<HybridRetrieveResult>('/api/retrieval/hybrid', payload),
  retrievalTrace: (id: string) => getJson<RetrievalTrace>(`/api/retrieval/trace/${encodeURIComponent(id)}`),
  retrievalTraceEvidence: (id: string, rank: number) =>
    getJson<MerkleInclusionProof>(`/api/retrieval/trace/${encodeURIComponent(id)}/evidence?rank=${rank}`),
  projectionCheckpoints: (projectionId: string, limit = 50) =>
    getJson<ProjectionCheckpoint[]>(`/api/projections/${encodeURIComponent(projectionId)}/checkpoints?limit=${limit}`),
  latestProjectionCheckpoint: (projectionId: string) =>
    getJson<ProjectionCheckpoint>(`/api/projections/${encodeURIComponent(projectionId)}/checkpoints/latest`),
  createProjectionCheckpoint: (projectionId: string) =>
    postJson<ProjectionCheckpoint>(`/api/projections/${encodeURIComponent(projectionId)}/checkpoint`, {}),
  reconcileProjectionCheckpoint: (projectionId: string) =>
    postJson<ProjectionReconciliation>(`/api/projections/${encodeURIComponent(projectionId)}/reconcile`, {}),
  rebuildProjectionCheckpoint: (projectionId: string) =>
    postJson<ProjectionCheckpoint & { verified: boolean }>(`/api/projections/${encodeURIComponent(projectionId)}/rebuild`, {}),
  embeddingModels: () => getJson<EmbeddingModel[]>('/api/embedding/models'),
  inferenceSettings: () => getJson<InferenceSettings>('/api/settings/inference'),
  updateInferenceSettings: (settings: InferenceSettings) => postJson<{ok: boolean; inference: InferenceSettings; message: string}>('/api/settings/inference', settings as unknown as Record<string, unknown>),
}
