// Pure validation + payload shaping for the write actions. Kept free of React and fetch so the
// rules (what is refused before a request is ever sent) are unit-tested. The server remains the
// authority: it re-checks scope and content, so this is the fast, friendly first line only.

/** Statuses a human may give a replacement memory. `superseded`/`forgotten` are produced by the
 *  store itself, and `quarantined`/`disputed` are decisions made elsewhere, so none are offered. */
export const SUPERSEDE_STATUSES = ['confirmed', 'active', 'candidate'] as const
export type SupersedeStatus = (typeof SUPERSEDE_STATUSES)[number]

export type Built<T> = { ok: true; payload: T } | { ok: false; error: string }

const fail = (error: string): { ok: false; error: string } => ({ ok: false, error })

export interface SupersedeForm {
  content: string
  status: SupersedeStatus
}

export type SupersedePayload = {
  new_content: string
  status: SupersedeStatus
  evidence_class: string
  /** The server requires a source. A person typed this in the console, so it is `direct_user`;
   *  the server binds the agent id itself from the verified workspace. */
  source: { kind: 'direct_user'; locator: string }
}

export function buildSupersede(oldId: string, oldContent: string, form: SupersedeForm): Built<SupersedePayload> {
  const content = form.content.trim()
  if (!content) return fail('Write the replacement text.')
  if (content === oldContent.trim()) return fail('The replacement is identical to the current text.')
  if (!SUPERSEDE_STATUSES.includes(form.status)) return fail('Choose a status for the replacement.')
  return {
    ok: true,
    payload: {
      new_content: content,
      status: form.status,
      // same default the legacy viewer's write-back used
      evidence_class: 'extracted_proposition',
      source: { kind: 'direct_user', locator: `console://memory/${oldId}/supersede` },
    },
  }
}

export interface LinkForm {
  subject: string
  predicate: string
  object: string
  confidence: string
}

export function buildLink(
  memoryId: string,
  form: LinkForm,
): Built<{ subject: string; predicate: string; object: string; evidence_memory_id: string; confidence: number }> {
  const subject = form.subject.trim()
  const predicate = form.predicate.trim()
  const object = form.object.trim()
  if (!subject || !predicate || !object) return fail('Subject, relation and object are all required.')
  // the store folds case and whitespace when matching entities, so compare the same way
  const fold = (s: string) => s.toLowerCase().split(/\s+/).filter(Boolean).join(' ')
  if (fold(subject) === fold(object)) return fail('Subject and object are the same entity.')
  const confidence = form.confidence.trim() === '' ? 1 : Number(form.confidence)
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) return fail('Confidence is a number from 0 to 1.')
  return { ok: true, payload: { subject, predicate, object, evidence_memory_id: memoryId, confidence } }
}

export interface ContradictionForm {
  otherId: string
  reason: string
}

export function buildContradiction(
  memoryId: string,
  form: ContradictionForm,
): Built<{ memory_id_a: string; memory_id_b: string; reason: string }> {
  const other = form.otherId.trim().replace(/^memory:/, '')
  const reason = form.reason.trim()
  if (!other) return fail('Pick the memory this one contradicts.')
  if (other === memoryId) return fail('A memory cannot contradict itself.')
  if (!reason) return fail('Say why they conflict; the reason is stored with the record.')
  return { ok: true, payload: { memory_id_a: memoryId, memory_id_b: other, reason } }
}

/** Forgetting is final for the content, so it is only offered where it can still change something. */
export function canForget(status: string): boolean {
  return status !== 'forgotten'
}

/** A superseded or forgotten memory should not be superseded again from the console. */
export function canSupersede(status: string): boolean {
  return status !== 'forgotten' && status !== 'superseded'
}

// --- asking the extraction worker to look at a memory ----------------------------------------------

/** Task types a person can queue from a memory. Their results are proposals that wait in Review. */
export const EXTRACTION_TASKS = ['extract_entities', 'extract_relations', 'classify_para', 'detect_contradictions', 'extract_memory_metadata'] as const
export type ExtractionTask = (typeof EXTRACTION_TASKS)[number]

/** Not a queued task: a synchronous, rule-based run with no model, offered next to the queued ones. */
export const STRUCTURAL = 'structural_entities' as const
export type ExtractionChoice = ExtractionTask | typeof STRUCTURAL

export type InferenceRequestPayload = {
  task_type: ExtractionTask
  subject_type: 'memory'
  subject_id: string
  input_payload: { source_content_hash: string }
  requested_by: string
  idempotency_key: string
  agent_id?: string
  store_id?: string
}

/**
 * Queue one extraction task for one memory. The idempotency key names the task type, the memory and
 * its exact content hash, so pressing the button twice returns the same task instead of queueing a
 * duplicate, while a superseded memory (new hash) is a new request.
 */
export function buildInferenceRequest(
  memory: { id: string; content_hash: string },
  taskType: string,
  scope: { agentId?: string; storeId?: string },
): Built<InferenceRequestPayload> {
  if (!(EXTRACTION_TASKS as readonly string[]).includes(taskType)) return { ok: false, error: 'Choose a task type.' }
  if (!memory.id || !memory.content_hash) return { ok: false, error: 'This memory has no content hash to anchor the task to.' }
  return {
    ok: true,
    payload: {
      task_type: taskType as ExtractionTask,
      subject_type: 'memory',
      subject_id: memory.id,
      input_payload: { source_content_hash: memory.content_hash },
      requested_by: 'cortex-console',
      idempotency_key: `console:${taskType}:${memory.id}:${memory.content_hash}`,
      ...(scope.agentId ? { agent_id: scope.agentId } : {}),
      ...(scope.storeId ? { store_id: scope.storeId } : {}),
    },
  }
}

// --- a new memory, written from the Memories page ---------------------------------------------------

export const NEW_MEMORY_STATUSES = ['candidate', 'active', 'confirmed'] as const
export type NewMemoryStatus = (typeof NEW_MEMORY_STATUSES)[number]

/** The evidence classes a person can claim for something they type in. `summary`, `policy` and
 *  `protocol_receipt` are produced by other mechanisms, so they are not offered. */
export const NEW_MEMORY_CLASSES = ['declared_intent', 'observed_event', 'extracted_proposition', 'inference'] as const
export type NewMemoryClass = (typeof NEW_MEMORY_CLASSES)[number]

export interface NewMemoryForm {
  content: string
  status: NewMemoryStatus
  evidenceClass: NewMemoryClass
}

export type NewMemoryPayload = {
  content: string
  status: NewMemoryStatus
  evidence_class: NewMemoryClass
  source: { kind: 'direct_user'; locator: string }
  /** the persisted agent id of the selected workspace; omitted for the primary profile */
  workspace_agent_id?: string
}

export function buildNewMemory(form: NewMemoryForm, workspaceAgentId: string | undefined): Built<NewMemoryPayload> {
  const content = form.content.trim()
  if (!content) return fail('Write the memory.')
  if (!NEW_MEMORY_STATUSES.includes(form.status)) return fail('Choose a status.')
  if (!NEW_MEMORY_CLASSES.includes(form.evidenceClass)) return fail('Choose an evidence class.')
  return {
    ok: true,
    payload: {
      content,
      status: form.status,
      evidence_class: form.evidenceClass,
      // a person typed it in the console, so that is the provenance it is recorded with
      source: { kind: 'direct_user', locator: 'console://memories/new' },
      ...(workspaceAgentId ? { workspace_agent_id: workspaceAgentId } : {}),
    },
  }
}

// --- recording an exchange into an existing session -------------------------------------------------

export interface ExchangeForm {
  sessionId: string
  prompt: string
  response: string
}

export type ExchangePayload = {
  external_session_id: string
  user_prompt: string
  model_response: string
  runtime: string
}

/** Recording an exchange is how a prompt/response pair joins a session's hash chain. The session
 *  must already exist (the server refuses an unknown one), so it is chosen, not invented here. */
export function buildExchange(form: ExchangeForm): Built<ExchangePayload> {
  const sessionId = form.sessionId.trim()
  const prompt = form.prompt.trim()
  const response = form.response.trim()
  if (!sessionId) return fail('Choose the session to record into.')
  if (!prompt) return fail('Write the prompt.')
  if (!response) return fail('Write the model response.')
  return { ok: true, payload: { external_session_id: sessionId, user_prompt: prompt, model_response: response, runtime: 'console' } }
}
