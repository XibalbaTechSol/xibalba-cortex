import { describe, expect, it } from 'vitest'
import { describeExchangeChain, describeMemoryChain, kindCounts, metricRows, provenanceFilename } from './verify'

describe('describeMemoryChain', () => {
  it('names the event where a break was found', () => {
    const v = describeMemoryChain({ valid: false, length: 5, broken_at_event_id: 12, head_node_id: 'h' })
    expect(v.tone).toBe('bad')
    expect(v.detail).toContain('event 12 of 5')
  })
  it('says a clean chain is local consistency, never anchoring', () => {
    const v = describeMemoryChain({ valid: true, length: 3, broken_at_event_id: null, head_node_id: 'h' })
    expect(v.tone).toBe('ok')
    expect(v.detail).toMatch(/not on-chain anchoring/)
    expect(v.detail).toContain('3 events')
  })
  it('does not call an empty chain verified', () => {
    const v = describeMemoryChain({ valid: true, length: 0, broken_at_event_id: null, head_node_id: null })
    expect(v.tone).toBe('neutral')
    expect(v.headline).toBe('Nothing to verify')
  })
  it('uses the singular for one event', () => {
    expect(describeMemoryChain({ valid: true, length: 1, broken_at_event_id: null, head_node_id: 'h' }).detail).toContain('1 event:')
  })
})

describe('describeExchangeChain', () => {
  it('names the exchange where a break was found', () => {
    const v = describeExchangeChain({ valid: false, length: 4, broken_at_sequence_number: 2, head_node_id: 'h' })
    expect(v.tone).toBe('bad')
    expect(v.detail).toContain('exchange 2 of 4')
  })
  it('mentions the older commitment format only when the server says it was used', () => {
    const base = { valid: true, length: 2, broken_at_sequence_number: null, head_node_id: 'h' }
    expect(describeExchangeChain(base).detail).not.toMatch(/older commitment/)
    expect(describeExchangeChain({ ...base, legacy_commitment: true }).detail).toMatch(/older commitment format/)
  })
  it('does not call an empty session verified', () => {
    expect(describeExchangeChain({ valid: true, length: 0, broken_at_sequence_number: null, head_node_id: null }).tone).toBe('neutral')
  })
})

describe('provenanceFilename', () => {
  it('keeps ordinary ids and strips path-ish characters', () => {
    expect(provenanceFilename('mem-123')).toBe('provenance-mem-123.json')
    expect(provenanceFilename('../../etc/passwd')).toBe('provenance-.._.._etc_passwd.json')
    expect(provenanceFilename('')).toBe('provenance-memory.json')
  })
  it('bounds the length', () => {
    expect(provenanceFilename('x'.repeat(500)).length).toBeLessThanOrEqual('provenance-.json'.length + 64)
  })
})

describe('otel summary wording', () => {
  const summary = { session_id: 's', counts_by_kind: { span: 1, metric: 2 }, metric_totals: { b: { total: null, count: 1 }, a: { total: 5, count: 2 } } }
  it('always names all three kinds, with zero where absent', () => {
    expect(kindCounts(summary)).toBe('1 span · 2 metrics · 0 logs')
  })
  it('sorts metrics and calls a null sum "no value", not 0', () => {
    expect(metricRows(summary)).toEqual([
      { name: 'a', total: '5', count: 2 },
      { name: 'b', total: 'no value', count: 1 },
    ])
  })
})
