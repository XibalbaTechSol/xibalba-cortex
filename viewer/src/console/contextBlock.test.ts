import { describe, expect, it } from 'vitest'
import type { ContextBlock, ContextItem } from '../api'
import { budgetText, contextItemCount, contextSections } from './contextBlock'

const item = (id: string): ContextItem => ({
  memory_id: id, content: id, valid_from: null, valid_to: null,
  provenance: { content_hash: 'sha256:x', source: {}, evidence_class: 'observed_event', status: 'confirmed' }, retrieval: {},
})
const block = (over: Partial<ContextBlock>): ContextBlock => ({
  schema_version: 'xibalba.context_block.v1', query: 'q', trace_id: 't', budget: { max_total_chars: 12000, used_chars: 1204 },
  current_facts: [], historical_facts: [], summaries: [], observations: [], degraded: [], channel_status: {}, score_semantics: null, ...over,
})

describe('contextSections', () => {
  it('drops empty sections and keeps the server order', () => {
    const out = contextSections(block({ observations: [item('o')], current_facts: [item('c')] }))
    expect(out.map((s) => s.key)).toEqual(['current_facts', 'observations'])
  })
  it('returns nothing for an empty block', () => {
    expect(contextSections(block({}))).toEqual([])
    expect(contextItemCount(block({}))).toBe(0)
  })
  it('counts every item across sections', () => {
    expect(contextItemCount(block({ current_facts: [item('a'), item('b')], summaries: [item('c')] }))).toBe(3)
  })
})

describe('budgetText', () => {
  it('words the budget as a cap', () => {
    expect(budgetText(block({}))).toBe('1,204 of 12,000 characters used')
  })
})
