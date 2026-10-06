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
