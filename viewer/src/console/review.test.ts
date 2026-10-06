import { describe, expect, it } from 'vitest'
import type { ExtractionProposal } from '../api'
import { describeProposal, partitionByScope } from './review'

const proposal = (task_type: string, payload: Record<string, unknown>): ExtractionProposal => ({
  id: 'p1', task_id: 't1', task_type, item_index: 0, source_memory_id: 'm1', source_content_hash: 'sha256:x',
  payload, evidence_quote: null, status: 'proposed', decision_note: null, decided_by: null, created_at: '2026-10-06 10:00:00', decided_at: null,
})

describe('describeProposal', () => {
  it('describes an entity and says the memory is untouched', () => {
    const v = describeProposal(proposal('extract_entities', { name: 'Texas', entity_type: 'location', confidence: 0.8 }))
    expect(v.kind).toBe('entity')
    expect(v.title).toBe('Texas')
    expect(v.facts).toEqual(['entity · location', 'confidence 80%'])
    expect(v.effect).toContain('The memory itself is not changed')
  })
  it('describes a relation', () => {
    const v = describeProposal(proposal('extract_relations', { subject: 'a', predicate: 'uses', object: 'b' }))
    expect(v.title).toBe('a — uses → b')
    expect(v.facts).toEqual(['relation'])
  })
  it('describes a contradiction without picking a side', () => {
    const v = describeProposal(proposal('detect_contradictions', { contradicting_memory_id: 'abcdef123456', reason: 'retry count differs' }))
    expect(v.kind).toBe('contradiction')
    expect(v.title).toBe('Conflicts with abcdef12…')
    expect(v.effect).toContain('does not decide')
  })
  it('does not invent a confidence that is missing or blank', () => {
    expect(describeProposal(proposal('extract_entities', { name: 'x' })).facts).toEqual(['entity · unknown'])
    expect(describeProposal(proposal('extract_entities', { name: 'x', confidence: '' })).facts).toEqual(['entity · unknown'])
  })
  it('falls back for an unknown type instead of throwing', () => {
    expect(describeProposal(proposal('mystery', {})).kind).toBe('unknown')
  })
})

describe('partitionByScope', () => {
  it('keeps only items whose memory resolved, and counts the rest', () => {
    const items = [{ m: 'a' }, { m: 'b' }, { m: 'c' }]
    const r = partitionByScope(items, new Set(['a', 'c']), (i) => i.m)
    expect(r.visible).toEqual([{ m: 'a' }, { m: 'c' }])
    expect(r.hidden).toBe(1)
  })
  it('shows nothing when nothing resolved (fail closed)', () => {
    expect(partitionByScope([{ m: 'a' }], new Set(), (i) => i.m)).toEqual({ visible: [], hidden: 1 })
  })
})
