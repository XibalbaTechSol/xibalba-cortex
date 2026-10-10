import { describe, expect, it } from 'vitest'
import { EXTRACTION_TASKS, buildContradiction, buildExchange, buildInferenceRequest, buildLink, buildNewMemory, buildSupersede, canForget, canSupersede } from './actions'

describe('buildSupersede', () => {
  it('trims and returns the payload', () => {
    expect(buildSupersede('m1', 'old', { content: '  new text  ', status: 'confirmed' })).toEqual({
      ok: true,
      payload: {
        new_content: 'new text',
        status: 'confirmed',
        evidence_class: 'extracted_proposition',
        source: { kind: 'direct_user', locator: 'console://memory/m1/supersede' },
      },
    })
  })
  it('refuses empty and unchanged text', () => {
    expect(buildSupersede('m1', 'old', { content: '   ', status: 'active' }).ok).toBe(false)
    expect(buildSupersede('m1', 'same', { content: ' same ', status: 'active' }).ok).toBe(false)
  })
})

describe('buildLink', () => {
  const ok = { subject: 'store.py', predicate: 'computes', object: 'domain root', confidence: '' }
  it('defaults confidence to 1 and ties the link to the evidence memory', () => {
    expect(buildLink('m1', ok)).toEqual({
      ok: true,
      payload: { subject: 'store.py', predicate: 'computes', object: 'domain root', evidence_memory_id: 'm1', confidence: 1 },
    })
  })
  it('requires all three parts', () => {
    expect(buildLink('m1', { ...ok, predicate: ' ' }).ok).toBe(false)
  })
  it('refuses a self link, folding case and spacing like the store', () => {
    expect(buildLink('m1', { ...ok, subject: 'Domain  Root', object: 'domain root' }).ok).toBe(false)
  })
  it('bounds confidence to 0..1 and rejects non-numbers', () => {
    expect(buildLink('m1', { ...ok, confidence: '0.4' }).ok).toBe(true)
    expect(buildLink('m1', { ...ok, confidence: '1.2' }).ok).toBe(false)
    expect(buildLink('m1', { ...ok, confidence: '-0.1' }).ok).toBe(false)
    expect(buildLink('m1', { ...ok, confidence: 'high' }).ok).toBe(false)
  })
})

describe('buildContradiction', () => {
  it('accepts a graph node id with its memory: prefix', () => {
    expect(buildContradiction('m1', { otherId: 'memory:m2', reason: ' retry count differs ' })).toEqual({
      ok: true,
      payload: { memory_id_a: 'm1', memory_id_b: 'm2', reason: 'retry count differs' },
    })
  })
  it('refuses self, missing target and missing reason', () => {
    expect(buildContradiction('m1', { otherId: 'm1', reason: 'x' }).ok).toBe(false)
    expect(buildContradiction('m1', { otherId: '', reason: 'x' }).ok).toBe(false)
    expect(buildContradiction('m1', { otherId: 'm2', reason: ' ' }).ok).toBe(false)
  })
})

describe('action availability', () => {
  it('does not offer forget twice or supersede on dead memories', () => {
    expect(canForget('forgotten')).toBe(false)
    expect(canForget('confirmed')).toBe(true)
    expect(canSupersede('superseded')).toBe(false)
    expect(canSupersede('forgotten')).toBe(false)
    expect(canSupersede('active')).toBe(true)
  })
})

describe('buildNewMemory', () => {
  const form = { content: '  The relay retries twice.  ', status: 'active', evidenceClass: 'observed_event' } as const
  it('trims, records a console provenance, and names the workspace only when there is one', () => {
    expect(buildNewMemory(form, undefined)).toEqual({
      ok: true,
      payload: { content: 'The relay retries twice.', status: 'active', evidence_class: 'observed_event', source: { kind: 'direct_user', locator: 'console://memories/new' } },
    })
    const scoped = buildNewMemory(form, 'pseudonym:abc')
    expect(scoped.ok && scoped.payload.workspace_agent_id).toBe('pseudonym:abc')
  })
  it('refuses empty content and values outside the offered sets', () => {
    expect(buildNewMemory({ ...form, content: '   ' }, undefined).ok).toBe(false)
    expect(buildNewMemory({ ...form, status: 'forgotten' as never }, undefined).ok).toBe(false)
    expect(buildNewMemory({ ...form, evidenceClass: 'policy' as never }, undefined).ok).toBe(false)
  })
})

describe('buildExchange', () => {
  it('trims and tags the runtime as the console', () => {
    expect(buildExchange({ sessionId: ' sess-1 ', prompt: ' q ', response: ' a ' })).toEqual({
      ok: true,
      payload: { external_session_id: 'sess-1', user_prompt: 'q', model_response: 'a', runtime: 'console' },
    })
  })
  it('refuses a missing session, prompt or response', () => {
    expect(buildExchange({ sessionId: '', prompt: 'q', response: 'a' }).ok).toBe(false)
    expect(buildExchange({ sessionId: 's', prompt: ' ', response: 'a' }).ok).toBe(false)
    expect(buildExchange({ sessionId: 's', prompt: 'q', response: '' }).ok).toBe(false)
  })
})


describe('buildInferenceRequest', () => {
  const memory = { id: 'm-1', content_hash: 'sha256:abc' }
  it('anchors the task to the memory and its exact content hash', () => {
    const built = buildInferenceRequest(memory, 'extract_entities', { agentId: 'agent-a', storeId: 'store-1' })
    expect(built).toEqual({
      ok: true,
      payload: {
        task_type: 'extract_entities',
        subject_type: 'memory',
        subject_id: 'm-1',
        input_payload: { source_content_hash: 'sha256:abc' },
        requested_by: 'cortex-console',
        idempotency_key: 'console:extract_entities:m-1:sha256:abc',
        agent_id: 'agent-a',
        store_id: 'store-1',
      },
    })
  })
  it('omits scope fields it was not given instead of sending empty strings', () => {
    const built = buildInferenceRequest(memory, 'classify_para', {})
    expect(built.ok && 'agent_id' in built.payload).toBe(false)
    expect(built.ok && 'store_id' in built.payload).toBe(false)
  })
  it('makes the same request twice produce the same key, and an edited memory a new one', () => {
    const a = buildInferenceRequest(memory, 'extract_relations', {})
    const b = buildInferenceRequest(memory, 'extract_relations', {})
    const edited = buildInferenceRequest({ ...memory, content_hash: 'sha256:def' }, 'extract_relations', {})
    expect(a.ok && b.ok && edited.ok && a.payload.idempotency_key === b.payload.idempotency_key && a.payload.idempotency_key !== edited.payload.idempotency_key).toBe(true)
  })
  it('refuses an unknown task type and a memory with no hash', () => {
    expect(buildInferenceRequest(memory, 'write_everything', {}).ok).toBe(false)
    expect(buildInferenceRequest({ id: 'm', content_hash: '' }, 'extract_entities', {}).ok).toBe(false)
  })
  it('offers only task types the worker contract lists as extraction', () => {
    expect(EXTRACTION_TASKS).not.toContain('summarize_session')
  })
})
