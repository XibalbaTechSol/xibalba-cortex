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
const storedApiBaseUrl = sessionStorage.getItem(URL_STORAGE_KEY) ?? DEFAULT_BASE_URL
// Never persist a cross-origin loopback API URL in the browser viewer. It bypasses
// the Vite proxy and makes the HttpOnly cookie host/samesite boundary inconsistent.
let apiBaseUrl = import.meta.env.DEV && /https?:\/\/(127\.0\.0\.1|localhost):8420/.test(storedApiBaseUrl)
  ? '/cortex-api'
  : storedApiBaseUrl

export function isSignedIn(): boolean {
  return signedIn
}

function markSignedIn(value: boolean): void {
  signedIn = value
  // the CSRF token is derived from the session cookie, so a new session means a new token
  csrfToken = undefined
  if (value) sessionStorage.setItem(SIGNED_IN_KEY, '1')
  else sessionStorage.removeItem(SIGNED_IN_KEY)
}

// local_api.py requires `X-Cortex-CSRF-Token` on every state-changing request that authenticates
// with the session cookie (_verify_csrf), and hands the token out at GET /api/auth/csrf. A bearer
// credential (the dev proxy, machine callers) has no cookie to ride, so that route answers 400 and
// no header is needed. `undefined` = not asked yet; `null` = asked, none required.
let csrfToken: string | null | undefined

async function csrfHeader(): Promise<Record<string, string>> {
  if (csrfToken === undefined) {
    const response = await fetch(`${getApiBaseUrl()}/api/auth/csrf`, { credentials: 'include' })
    if (response.ok) {
      const body = (await response.json().catch(() => ({}))) as { csrf_token?: string }
      csrfToken = body.csrf_token ?? null
    } else if (response.status === 400) {
      csrfToken = null // not cookie-authenticated: nothing to forge, nothing to send
    } else {
      // 401 etc.: leave it unset so the next write asks again, and let that request report the real error
      return {}
    }
  }
  return csrfToken ? { 'X-Cortex-CSRF-Token': csrfToken } : {}
}

/** fetch for a state-changing route: attaches the CSRF header and retries once if the token went stale. */
async function mutatingFetch(path: string, init: RequestInit): Promise<Response> {
  const send = async () => fetch(`${getApiBaseUrl()}${path}`, { ...init, credentials: 'include', headers: { ...(init.headers as Record<string, string> | undefined), ...(await csrfHeader()) } })
  const response = await send()
  if (response.status === 403 && csrfToken) {
    // the session may have been replaced since the token was fetched; ask again exactly once
    csrfToken = undefined
    return send()
  }
  return response
}

/**
 * Dev only: the Vite dev server's proxy attaches a local operator token to every /cortex-api
 * request, so there is no cookie to sign in for. Prove the proxy reaches a Cortex profile, then
 * mark the viewer signed in. A production build has no such proxy and this just fails honestly.
 */
export async function connectLocalDev(): Promise<void> {
  const response = await fetch(`${getApiBaseUrl()}/api/status`, { credentials: 'include' })
  if (!response.ok) throw new Error('No local Cortex profile is reachable through the dev proxy. Start the local API, or sign in with an account.')
  markSignedIn(true)
}

export function getApiBaseUrl(): string {
  return apiBaseUrl
}

export function setApiBaseUrl(value: string): void {
  const candidate = value.trim().replace(/\/+$/, '') || DEFAULT_BASE_URL
  const normalized = import.meta.env.DEV && /https?:\/\/(127\.0\.0\.1|localhost):8420/.test(candidate)
    ? '/cortex-api'
    : candidate
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
  // a valid bearer credential that is not an account session gets HTTP 200 with `{"error": ...}`
  // and no `account`; treat that as the failure it is rather than returning a value of the wrong shape
  if (!payload.account) throw new Error(payload.error || "no account for this credential")
  return payload
}

export async function accountSessions(): Promise<{sessions: Array<Record<string, unknown>>}> {
  const response = await fetch(getApiBaseUrl() + "/api/auth/sessions", { credentials: "include" })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
  return payload
}

export async function accountRevokeSession(sessionId: string): Promise<void> {
  const response = await mutatingFetch("/api/auth/sessions/revoke", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) })
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
  const response = await mutatingFetch("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.status + " " + response.statusText)
}

// `GET /api/graph` (GraphStore.graph_payload) returns five node classes and eight edge types.
// This used to declare only `memory | entity` and `relation | similarity | contradiction`, which
// understated the payload: session/exchange/merkle nodes and the structural edges have always
// been sent, and the legacy graph code reads them through its own DemoNode adapter. Widened so
// the types match the wire. Every added field is optional, so existing readers are unaffected.
export type GraphNodeType = 'memory' | 'entity' | 'session' | 'exchange' | 'merkle'
export type GraphEdgeType =
  | 'relation' | 'similarity' | 'contradiction'
  | 'contains' | 'prompt' | 'response' | 'context' | 'merkle_root'

export interface GraphNode {
  id: string
  type: GraphNodeType
  label: string
  status?: string
  evidence_class?: string
  source_kind?: string
  entity_type?: string
  /** exchange nodes: ISO prompt time. */
  timestamp?: string | null
  /** session nodes: "YYYY-MM-DD HH:MM:SS" (UTC, no zone marker). */
  started_at?: string
  /** merkle nodes: whether the server-computed root is valid. */
  valid?: boolean
  agent_id?: string
  /** memory nodes (backend 2026-10-06+): the store's write time, and the event time if the writer set one. */
  created_at?: string
  observed_at?: string | null
  session_id?: string | null
}

export interface GraphEdge {
  source: string
  target: string
  type: GraphEdgeType
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
  observed_at?: string | null
  metadata: Record<string, unknown>
}

export interface Memory {
  id: string
  content: string
  content_hash: string
  status: string
  /** UTC, the store's own write time; not the event time (source.observed_at). */
  created_at?: string
  valid_from?: string | null
  valid_to?: string | null
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
  /** the entity the edge leaves (backend 2026-10-06+; older servers omit it) */
  subject?: string
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
  /** Returned by GET /api/status; not declared before the console needed it. */
  profile_id?: string
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

export interface WorkspaceScope {
  agentId?: string
  storeId?: string
}

function scopeParams(scope: WorkspaceScope = {}): string {
  const params = new URLSearchParams()
  if (scope.agentId) params.set('agent_id', scope.agentId)
  if (scope.storeId) params.set('store_id', scope.storeId)
  const query = params.toString()
  return query ? `&${query}` : ''
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

export interface SessionMerkleProof {
  session_id: string
  tree_kind: string
  leaf: string
  leaf_index: number
  exchange_count: number
  root: string
  proof: MerkleInclusionProof
  disclaimer: string
}

export interface KernelIntent {
  invocation_id: string | null
  tool_call_id: string | null
  correlation_mode: 'invocation_id' | 'legacy_tool_call_id'
  tool_name: string | null
  declared_intent: { intent_rationale: string | null; tool_input_hash: string | null }
  kernel_decision: Record<string, unknown>
  actual_outcome: Record<string, unknown>
  [key: string]: unknown
}

export interface Invocation {
  invocation_id: string
  session_id: string
  agent_id: string | null
  runtime: string | null
  tool_name: string | null
  tool_call_id: string | null
  first_seen_at: string
  last_seen_at: string
  pre_tool: { intent_rationale: string | null; tool_input_hash: string | null; policy_reason: string | null; kernel_decision: Record<string, unknown> | null } | null
  post_tool: { outcome: string | null; result: unknown; duration_ms: number | null } | null
  runtime_status: 'complete' | 'awaiting_outcome' | 'orphan_outcome'
}

export interface DecisionTraceEvent {
  event_id: string
  trace_id: string
  sequence_number: number
  event_hash: string
  parent_event_hash: string | null
  envelope: Record<string, unknown>
  advisory: Record<string, unknown> | null
  created_at: string
}

export interface DecisionTrace {
  trace_id: string
  session_id: string
  events: DecisionTraceEvent[]
  root: string | null
  valid: boolean
  disclaimer?: string
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
  retry_after?: string | null
  failure_class?: string | null
  dead_letter_reason?: string | null
  requested_provider_id?: string | null
  executing_provider_id?: string | null
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

/** One on-chain verdict from IntegrityKernel for a self-test UserOperation (kernel_bridge.KernelDecision.to_dict). */
export interface KernelBridgeDecision {
  user_op_hash: string
  success: boolean | null
  actual_gas_cost: number | string | null
  revert_reason_hex: string | null
  adapter_note: string | null
}

export type KernelBridgeSelfTest =
  | { ok: false; error: string }
  | { ok: true; matched: KernelBridgeDecision; kernel_exceeding: KernelBridgeDecision; passed: boolean }

/** GET /api/memory/{id}/verify-chain (GraphStore.verify_chain). */
export interface ChainVerification {
  valid: boolean
  length: number
  broken_at_event_id: number | null
  head_node_id: string | null
}

/** GET /api/session/{id}/verify-chain (GraphStore.verify_exchange_chain). */
export interface ExchangeChainVerification {
  valid: boolean
  length: number
  broken_at_sequence_number: number | null
  head_node_id: string | null
  /** present when a mismatch was explained by an older commitment format rather than tampering */
  legacy_commitment?: boolean
}

/** GET /api/memory/{id}/provenance (GraphStore.export_memory_bundle). */
export interface ProvenanceBundle {
  schema_version: string
  count: number
  memory_ids: string[]
  memories: Memory[]
  leaf_hashes: string[]
  root_hash: string
  include_forgotten: boolean
  disclaimer: string
}

/** GET /api/session/{id}/otel-summary (GraphStore.session_otel_summary). */
export interface OtelSummary {
  session_id: string
  counts_by_kind: Record<string, number>
  metric_totals: Record<string, { total: number | null; count: number }>
}

export interface ContextItem {
  memory_id: string
  content: string
  valid_from: string | null
  valid_to: string | null
  provenance: { content_hash: string; source: Record<string, unknown>; evidence_class: string; status: string }
  retrieval: Record<string, unknown>
}

/** POST /api/context/assemble (GraphStore.assemble_context). */
export interface ContextBlock {
  schema_version: string
  query: string
  trace_id: string
  budget: { max_total_chars: number; used_chars: number }
  current_facts: ContextItem[]
  historical_facts: ContextItem[]
  summaries: ContextItem[]
  observations: ContextItem[]
  degraded: unknown
  channel_status: Record<string, unknown>
  score_semantics: unknown
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

export interface ReadinessReport {
  schema_version: string
  ready: boolean
  profile_id: string
  checks: Record<string, boolean | string>
}

export interface OperationsAudit {
  schema_version: string
  memory_event_counts: Record<string, number>
  inference_task_states: Record<string, number>
  proposal_states: Record<string, number>
  session_count: number
  forgotten_memory_count: number
  integrity_links: { total_memories: number; linked_records: number; states: Record<string, number> }
  [key: string]: unknown
}

export interface EmbeddingCoverage {
  model: EmbeddingModel | null
  eligible: number
  current: number
  missing: number
  stale: number
  failed: number
  coverage_ratio: number
}

export interface OperationsSnapshot {
  schema_version: string
  profile_id: string
  health: { state: string; status: StoreStatus }
  readiness: { state: string; checks: Record<string, boolean> }
  features: Record<string, boolean>
  quotas: Record<string, number | null>
  embedding_coverage: EmbeddingCoverage
  audit: OperationsAudit
  connectors: Record<string, { entrypoint: string; state: string; idempotency?: string; requirement?: string }>
  production: { state: string; active_tokens: number; token_lifecycle: string; tenant_onboarding: string; isolation_model: string; open_gates: string[] }
  disclaimer: string
}

export interface AgentWorkspace {
  agent_id: string
  /** Older local APIs may omit these scope fields; the viewer must fail closed. */
  store_id?: string
  profile_id?: string
  store_access?: 'writable' | 'read_only'
  /** True only when this identity's workspace belongs to the API's writable primary store. */
  writable?: boolean
  device_id?: string | null
  agent_name?: string | null
  device_name?: string | null
  pair_status?: 'active' | 'detached' | 'revoked' | null
  pair_updated_at?: string | null
  memories: number
  /** False means the API skipped an expensive count; zero is not a measured total. */
  memories_counted?: boolean
  sessions: number
  sessions_counted?: boolean
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
  /** the identity registry's own label, or a shortened pseudonym */
  display_name?: string | null
  did?: string | null
  handle?: string | null
  seen?: boolean
}

export interface AgentDevicePair {
  device_id: string
  agent_id: string
  display_name: string
  status: 'active' | 'detached' | 'revoked'
  created_at: string
  updated_at: string
  last_seen_at: string | null
}

export interface AgentSummary {
  agent_id: string
  memories: number
  sessions: number
  sources: number
  embedded_memories: number | null
  recent_memories: Memory[]
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
  const response = await mutatingFetch(path, {
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

async function getBlob(path: string): Promise<Blob> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, { credentials: "include" })
  if (!response.ok) throw new Error(`request failed: ${response.status}`)
  return response.blob()
}

export const api = {
  stats: () => getJson<Stats>('/api/stats'),
  status: () => getJson<StoreStatus>('/api/status'),
  operations: () => getJson<OperationsSnapshot>('/api/operations'),
  /** /readyz answers 503 with the same body when not ready, so a 503 is a result, not an error. */
  readiness: async (): Promise<ReadinessReport> => {
    const response = await fetch(`${getApiBaseUrl()}/readyz`, { credentials: 'include' })
    const body = (await response.json().catch(() => null)) as ReadinessReport | null
    if (!body || typeof body.ready !== 'boolean') throw new Error(`readiness check failed: ${response.status} ${response.statusText}`)
    return body
  },
  /** Prometheus text exposition, unauthenticated by design. */
  metrics: async (): Promise<string> => {
    const response = await fetch(`${getApiBaseUrl()}/metrics`, { credentials: 'include' })
    if (!response.ok) throw new Error(`metrics unavailable: ${response.status}`)
    return response.text()
  },
  integrityLinks: (limit = 50) => getJson<IntegrityLinksStatus>(`/api/integrity-links?limit=${limit}`),
  sessions: (limit = 100, scope: WorkspaceScope = {}) => getJson<Session[]>(`/api/sessions?limit=${limit}${scopeParams(scope)}`),
  sessionsPage: (limit = 50, offset = 0, scope: WorkspaceScope = {}) =>
    getJson<{sessions: Session[]; offset: number; limit: number; has_more: boolean; count_status: string; store_id: string; profile_id: string}>(`/api/sessions/page?limit=${limit}&offset=${offset}${scopeParams(scope)}`),
  agents: (limit = 100) => getJson<{agents: AgentWorkspace[]; oracle_reachable: boolean}>(`/api/agents?limit=${limit}`),
  agentSummary: (agentId: string, storeId: string) =>
    getJson<AgentSummary>(`/api/agent/${encodeURIComponent(agentId)}/summary?limit=0&store_id=${encodeURIComponent(storeId)}`),
  agentMemories: (agentId: string, deviceId?: string, limit = 100, scope: WorkspaceScope = {}) => getJson<{agent_id: string; memories: Memory[]}>(`/api/agent/${encodeURIComponent(agentId)}/memories?limit=${limit}${deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : ''}${scopeParams(scope)}`),
  /** Pairings, newest first. /api/agents lists workspaces; this lists which devices are paired to them. */
  agentDevices: () => getJson<{ pairs: AgentDevicePair[] }>('/api/agent-devices'),
  associateAgentDevice: (agentId: string, deviceId: string, displayName?: string) =>
    postJson<AgentDevicePair>('/api/agent-devices/associate', { agent_id: agentId, device_id: deviceId, display_name: displayName || deviceId }),
  renameAgentDevice: (deviceId: string, displayName: string) =>
    postJson<AgentDevicePair>(`/api/agent-devices/${encodeURIComponent(deviceId)}/rename`, { display_name: displayName }),
  detachAgentDevice: (deviceId: string) =>
    postJson<AgentDevicePair>(`/api/agent-devices/${encodeURIComponent(deviceId)}/detach`, {}),
  revokeAgentDevice: (deviceId: string) =>
    postJson<AgentDevicePair>(`/api/agent-devices/${encodeURIComponent(deviceId)}/revoke`, {}),
  graph: (limit = 500, similarityThreshold = 0.75, scope: WorkspaceScope = {}) =>
    getJson<GraphPayload>(`/api/graph?limit=${limit}&similarity_threshold=${similarityThreshold}${scopeParams(scope)}`),
  search: (query: string, limit = 20, scope: WorkspaceScope = {}) =>
    getJson<Memory[]>(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}${scopeParams(scope)}`),
  memories: (opts: { limit?: number; offset?: number; statuses?: string[]; agentId?: string; storeId?: string; query?: string } = {}) => {
    const { limit = 50, offset = 0, statuses, agentId, storeId, query } = opts
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (statuses?.length) params.set('status', statuses.join(','))
    if (agentId) params.set('agent_id', agentId)
    if (storeId) params.set('store_id', storeId)
    if (query?.trim()) params.set('q', query.trim())
    return getJson<{ memories: Memory[]; has_more: boolean; offset: number; limit: number }>(`/api/memories?${params.toString()}`)
  },
  memory: (id: string, scope: WorkspaceScope = {}) => getJson<Memory>(`/api/memory/${encodeURIComponent(id)}?${scopeParams(scope).slice(1)}`),
  similar: (id: string, limit = 10, scope: WorkspaceScope = {}) =>
    getJson<SimilarHit[]>(`/api/memory/${encodeURIComponent(id)}/similar?limit=${limit}${scopeParams(scope)}`),
  neighbors: (id: string, scope: WorkspaceScope = {}) => getJson<EntityRelation[]>(`/api/memory/${encodeURIComponent(id)}/neighbors?${scopeParams(scope).slice(1)}`),
  memoryEvents: (id: string, scope: WorkspaceScope = {}) => getJson<MemoryEvent[]>(`/api/memory/${encodeURIComponent(id)}/events?${scopeParams(scope).slice(1)}`),
  memoryOtel: (id: string, scope: WorkspaceScope = {}) => getJson<OtelEvent[]>(`/api/memory/${encodeURIComponent(id)}/otel?${scopeParams(scope).slice(1)}`),
  attachments: (id: string, scope: WorkspaceScope = {}) => getJson<Attachment[]>(`/api/memory/${encodeURIComponent(id)}/attachments?${scopeParams(scope).slice(1)}`),
  attachmentFile: (id: string, scope: WorkspaceScope = {}) => getBlob(`/api/attachment/${encodeURIComponent(id)}/file?${scopeParams(scope).slice(1)}`),
  contradictions: (id: string, scope: WorkspaceScope = {}) => getJson<Memory[]>(`/api/memory/${encodeURIComponent(id)}/contradictions?${scopeParams(scope).slice(1)}`),
  entityNeighbors: (name: string, maxDepth = 1, scope: WorkspaceScope = {}) =>
    getJson<TraversalResult>(`/api/entity/${encodeURIComponent(name)}/neighbors?max_depth=${maxDepth}${scopeParams(scope)}`),
  entityPath: (from: string, to: string, maxDepth = 3, scope: WorkspaceScope = {}) =>
    getJson<TraversalResult>(`/api/entity/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&max_depth=${maxDepth}${scopeParams(scope)}`),
  sessionReplay: (id: string, scope: WorkspaceScope = {}) => getJson<SessionReplay>(`/api/session/${encodeURIComponent(id)}/replay?${scopeParams(scope).slice(1)}`),
  sessionOtel: (id: string, scope: WorkspaceScope = {}) => getJson<OtelEvent[]>(`/api/session/${encodeURIComponent(id)}/otel?${scopeParams(scope).slice(1)}`),
  kernelIntents: (id: string, scope: WorkspaceScope = {}) => getJson<KernelIntent[]>(`/api/session/${encodeURIComponent(id)}/kernel-intents?${scopeParams(scope).slice(1)}`),
  decisionTrace: (id: string, traceId: string, scope: WorkspaceScope = {}) =>
    getJson<DecisionTrace>(`/api/session/${encodeURIComponent(id)}/decision-trace?trace_id=${encodeURIComponent(traceId)}${scopeParams(scope)}`),
  /** URL of the server-rendered audit view; opened in a new tab, so it carries the session cookie. */
  decisionTraceHtmlUrl: (id: string, traceId: string, scope: WorkspaceScope = {}) =>
    `${getApiBaseUrl()}/api/session/${encodeURIComponent(id)}/decision-trace.html?trace_id=${encodeURIComponent(traceId)}${scopeParams(scope)}`,
  invocations: (limit = 100) => getJson<Invocation[]>(`/api/invocations?limit=${limit}`),
  sessionExchanges: (id: string, scope: WorkspaceScope = {}) => getJson<Exchange[]>(`/api/session/${encodeURIComponent(id)}/exchanges?${scopeParams(scope).slice(1)}`),
  buildSessionExchanges: (id: string) => postJson(`/api/session/${encodeURIComponent(id)}/exchanges/build`, {}),
  /** Inclusion proof for the exchange at `index`, in the `exchange_batch` domain. */
  sessionMerkleProof: (id: string, index: number, scope: WorkspaceScope = {}) =>
    getJson<SessionMerkleProof>(`/api/session/${encodeURIComponent(id)}/merkle-proof?index=${index}${scopeParams(scope)}`),
  /** The server recomputes a memory's event hash chain. Local consistency only, not on-chain anchoring. */
  memoryVerifyChain: (id: string, scope: WorkspaceScope = {}) => getJson<ChainVerification>(`/api/memory/${encodeURIComponent(id)}/verify-chain?${scopeParams(scope).slice(1)}`),
  /** A bounded provenance bundle for one memory, with the server's Merkle commitment over it. */
  memoryProvenance: (id: string, includeForgotten = false, scope: WorkspaceScope = {}) =>
    getJson<ProvenanceBundle>(`/api/memory/${encodeURIComponent(id)}/provenance?include_forgotten=${includeForgotten ? 1 : 0}${scopeParams(scope)}`),
  /** The server recomputes a session's exchange chain (node hashes and parent linkage). */
  sessionVerifyChain: (id: string, scope: WorkspaceScope = {}) => getJson<ExchangeChainVerification>(`/api/session/${encodeURIComponent(id)}/verify-chain?${scopeParams(scope).slice(1)}`),
  sessionMemories: (id: string, scope: WorkspaceScope = {}) => getJson<Memory[]>(`/api/session/${encodeURIComponent(id)}/memories?${scopeParams(scope).slice(1)}`),
  sessionOtelSummary: (id: string, scope: WorkspaceScope = {}) => getJson<OtelSummary>(`/api/session/${encodeURIComponent(id)}/otel-summary?${scopeParams(scope).slice(1)}`),
  /** The bounded, provenance-bearing context block hybrid retrieval would hand an agent. Read-only. */
  assembleContext: (payload: { query: string; limit?: number; max_total_chars?: number; temporal_at?: string; filters?: Record<string, unknown> }) =>
    postJson<ContextBlock>('/api/context/assemble', payload),
  sessionMerkleRoot: (id: string, scope: WorkspaceScope = {}) => getJson<MerkleRoot>(`/api/session/${encodeURIComponent(id)}/merkle-root?${scopeParams(scope).slice(1)}`),
  inferenceManifest: () => getJson<InferenceManifest>('/api/inference/manifest'),
  inferenceTasks: (status = 'pending', limit = 50, scope: WorkspaceScope = {}) =>
    getJson<InferenceTask[]>(`/api/inference/tasks?status=${encodeURIComponent(status)}&limit=${limit}${scopeParams(scope)}`),
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
  claimInferenceTask: (id: string, claimedBy: string, scope: WorkspaceScope = {}) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/claim?${scopeParams(scope).slice(1)}`, { claimed_by: claimedBy }),
  completeInferenceTask: (id: string, outputPayload: Record<string, unknown>, error?: string, claimedBy?: string | null, claimToken?: string | null, scope: WorkspaceScope = {}) =>
    postJson<InferenceTask>(`/api/inference/tasks/${encodeURIComponent(id)}/complete?${scopeParams(scope).slice(1)}`, {
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
  /**
   * Guided System Test for the kernel bridge. Without a session id it only submits the two
   * UserOperations and reports the decisions; with one it also records them as real
   * pre/post_tool_call events in that session. A bridge that is not deployed answers 200 with
   * `ok: false` and the reason in `error`, which callers must show, not swallow.
   */
  kernelBridgeSelfTest: (sessionId?: string) => postJson<KernelBridgeSelfTest>('/api/kernel-bridge/self-test', sessionId ? { session_id: sessionId } : {}),
  inferenceSettings: () => getJson<InferenceSettings>('/api/settings/inference'),
  updateInferenceSettings: (settings: InferenceSettings) => postJson<{ok: boolean; inference: InferenceSettings; message: string}>('/api/settings/inference', settings as unknown as Record<string, unknown>),
}
