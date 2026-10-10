import { describe, expect, it } from 'vitest'
import { INVOCATION_STATUS, describeKernelDecision, exchangeSummary } from './sessions'

describe('describeKernelDecision', () => {
  it('reads the verdict and the matched case', () => {
    expect(describeKernelDecision({ verdict: 'allow', matched_case: 'within_budget' })).toEqual({ verdict: 'allow', tone: 'ok', detail: 'within_budget' })
    expect(describeKernelDecision({ verdict: 'DENY', reason: 'destructive' })).toEqual({ verdict: 'DENY', tone: 'conflict', detail: 'destructive' })
  })
  it('does not call an unrecognised verdict good: it is flagged for review', () => {
    expect(describeKernelDecision({ verdict: 'escalate' }).tone).toBe('review')
    expect(describeKernelDecision({}).verdict).toBe('unspecified')
  })
  it('says so when there is no decision at all', () => {
    expect(describeKernelDecision(null)).toMatchObject({ verdict: 'no decision recorded', tone: 'neutral' })
    expect(describeKernelDecision(undefined).tone).toBe('neutral')
  })
})

describe('INVOCATION_STATUS', () => {
  it('flags an outcome with no intent as a conflict and a missing outcome as review, never ok', () => {
    expect(INVOCATION_STATUS.orphan_outcome.tone).toBe('conflict')
    expect(INVOCATION_STATUS.awaiting_outcome.tone).toBe('review')
    expect(INVOCATION_STATUS.complete.tone).toBe('ok')
  })
})

describe('exchangeSummary', () => {
  it('pluralises and omits an unknown latency', () => {
    expect(exchangeSummary({ context_contributions: [1], tool_calls: [], latency_ms: null })).toBe('1 context memory · 0 tool calls')
    expect(exchangeSummary({ context_contributions: [1, 2], tool_calls: [1], latency_ms: 120 })).toBe('2 context memories · 1 tool call · 120 ms')
  })
})
