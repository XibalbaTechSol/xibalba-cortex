// Pure helpers for the Review drawer: describe a proposal in words, label PARA categories, and
// split a queue into what this workspace may see and what it may not.
//
// The extraction-proposal and PARA endpoints list the whole store and take no agent scope, and
// `GET /api/memory/{id}` does not enforce the agent query parameter for operator credentials, so a
// per-memory read proves nothing. The console instead matches each item's source memory against
// the workspace's own scoped memory listing and hides whatever is not in it, counting what it hid.
// Fail closed: not found in the scoped listing means not shown.

import type { ExtractionProposal, ParaClassification } from '../api'

export interface ProposalView {
  kind: 'entity' | 'relation' | 'contradiction' | 'unknown'
  title: string
  /** short facts under the title */
  facts: string[]
  /** what Accept would do, in plain words, shown before the second click */
  effect: string
}

const text = (value: unknown): string => (typeof value === 'string' ? value : value == null ? '' : String(value))

const confidenceText = (value: unknown): string | null => {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) && value !== '' && value !== null ? `confidence ${Math.round(n * 100)}%` : null
}

export function describeProposal(p: ExtractionProposal): ProposalView {
  const payload = p.payload ?? {}
  const confidence = confidenceText(payload.confidence)
  if (p.task_type === 'extract_entities') {
    const name = text(payload.name) || '(unnamed)'
    const type = text(payload.entity_type) || 'unknown'
    return {
      kind: 'entity',
      title: name,
      facts: [`entity · ${type}`, ...(confidence ? [confidence] : [])],
      effect: `Adds the entity “${name}” (${type}) to the graph, evidenced by the source memory. The memory itself is not changed.`,
    }
  }
  if (p.task_type === 'extract_relations') {
    const subject = text(payload.subject)
    const predicate = text(payload.predicate)
    const object = text(payload.object)
    return {
      kind: 'relation',
      title: `${subject} — ${predicate} → ${object}`,
      facts: ['relation', ...(confidence ? [confidence] : [])],
      effect: `Adds the relation “${subject} ${predicate} ${object}” to the graph, evidenced by the source memory. The memory itself is not changed.`,
    }
  }
  if (p.task_type === 'detect_contradictions') {
    const other = text(payload.contradicting_memory_id)
    const reason = text(payload.reason)
    return {
      kind: 'contradiction',
      title: `Conflicts with ${other.slice(0, 8)}…`,
      facts: ['contradiction', ...(reason ? [reason] : [])],
      effect: 'Records a contradiction between the two memories. It does not decide which one is right.',
    }
  }
  return {
    kind: 'unknown',
    title: p.task_type,
    facts: [],
    effect: 'This proposal type is not one the console recognises; the server will refuse to apply it if it has no handler.',
  }
}

export const PARA_LABEL: Record<ParaClassification['category'], string> = {
  project: 'Project',
  area: 'Area',
  resource: 'Resource',
  archive: 'Archive',
}

export const PARA_MEANING: Record<ParaClassification['category'], string> = {
  project: 'a goal with an end state',
  area: 'an ongoing responsibility',
  resource: 'reference material',
  archive: 'no longer active',
}

export const percent = (n: number): string => `${Math.round(n * 100)}%`

/** Keep items whose source memory resolved in this workspace; count the rest as hidden. */
export function partitionByScope<T>(items: readonly T[], inScope: ReadonlySet<string>, memoryIdOf: (item: T) => string): { visible: T[]; hidden: number } {
  const visible = items.filter((item) => inScope.has(memoryIdOf(item)))
  return { visible, hidden: items.length - visible.length }
}
