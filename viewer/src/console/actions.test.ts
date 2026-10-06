import { describe, expect, it } from 'vitest'
import { buildContradiction, buildLink, buildNewMemory, buildSupersede, canForget, canSupersede } from './actions'

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
