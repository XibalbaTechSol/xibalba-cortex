import { describe, expect, it } from 'vitest'
import type { Invocation } from '../api'
import { describeIntervention, interventions, interventionsForSession, sessionRuntime } from './runtime'

const inv = (over: Partial<Invocation> & { verdict?: string; reason?: string }): Invocation => ({
  invocation_id: over.invocation_id ?? 'i', session_id: over.session_id ?? 's1', agent_id: null, runtime: over.runtime ?? 'claude', tool_name: over.tool_name ?? 'write_file',
  tool_call_id: 'c', first_seen_at: over.first_seen_at ?? '2026-10-10 09:00:00', last_seen_at: '2026-10-10 09:00:01',
  pre_tool: over.verdict === undefined ? null : { intent_rationale: null, tool_input_hash: null, policy_reason: over.reason ?? 'because', kernel_decision: { verdict: over.verdict } },
  post_tool: null, runtime_status: 'awaiting_outcome',
})

describe('interventions', () => {
  it('keeps only deny and ask, oldest first, with the reason the policy gave', () => {
    const out = interventions([
      inv({ invocation_id: 'a', verdict: 'allow' }),
      inv({ invocation_id: 'b', verdict: 'deny', reason: 'destructive action', first_seen_at: '2026-10-10 10:00:00' }),
      inv({ invocation_id: 'c', verdict: 'ask', reason: 'needs approval', first_seen_at: '2026-10-10 09:30:00' }),
      inv({ invocation_id: 'd' }),
    ])
    expect(out.map((i) => [i.invocationId, i.verdict, i.reason])).toEqual([['c', 'ask', 'needs approval'], ['b', 'deny', 'destructive action']])
  })
  it('skips a call it cannot place in time rather than inventing a time', () => {
    expect(interventions([inv({ verdict: 'deny', first_seen_at: 'not a time' })])).toEqual([])
  })
  it('says what happened in one line', () => {
    const [i] = interventions([inv({ verdict: 'deny', reason: 'destructive action', tool_name: 'rm' })])
    expect(describeIntervention(i)).toBe('Denied: rm. destructive action')
    const [a] = interventions([inv({ verdict: 'ask', reason: 'needs approval' })])
    expect(describeIntervention(a)).toMatch(/^Asked for approval:/)
  })
  it('selects the marks of one session', () => {
    const all = interventions([inv({ verdict: 'deny', session_id: 's1' }), inv({ invocation_id: 'x', verdict: 'deny', session_id: 's2' })])
    expect(interventionsForSession(all, 's2').map((i) => i.invocationId)).toEqual(['x'])
    expect(interventionsForSession(all, undefined)).toEqual([])
  })
})

describe('sessionRuntime', () => {
  it('counts decisions and names the runtimes, and is null for a session with no calls', () => {
    const list = [inv({ verdict: 'allow' }), inv({ invocation_id: '2', verdict: 'deny' }), inv({ invocation_id: '3', runtime: 'codex', verdict: 'ask' }), inv({ invocation_id: '4' }), inv({ invocation_id: '5', session_id: 'other', verdict: 'deny' })]
    expect(sessionRuntime(list, 's1')).toEqual({ runtimes: ['claude', 'codex'], invocations: 4, allowed: 1, denied: 1, asked: 1, undecided: 1 })
    expect(sessionRuntime(list, 'nobody')).toBeNull()
  })
})
