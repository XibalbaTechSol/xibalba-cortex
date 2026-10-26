// What a runtime did, for the Timeline and the Inspector: pure helpers over the recent tool-call
// correlations (GET /api/invocations) the console already loads.
//
// A policy decision is a fact the store recorded: the kernel said allow, deny or ask for a tool call,
// with a reason. A denial or an ask is an INTERVENTION: the runtime was stopped or had to wait for a
// person. Those are the events a reader of the timeline most wants to see, so they become marks on
// the session's lane; allowed calls would be noise and are only counted.

import type { Invocation } from '../api'
import { parseServerTime } from './model'

export interface Intervention {
  invocationId: string
  sessionId: string
  /** ms since epoch, from when the store first saw the call */
  at: number
  verdict: 'deny' | 'ask'
  tool: string
  reason: string
  runtime: string | null
}

function verdictOf(inv: Invocation): string {
  const decision = inv.pre_tool?.kernel_decision
  const raw = decision && typeof decision === 'object' ? (decision as Record<string, unknown>).verdict : null
  return typeof raw === 'string' ? raw.toLowerCase() : ''
}

/** Deny and ask decisions that can be placed in time, oldest first. A call with no usable time is skipped, not guessed. */
export function interventions(invocations: readonly Invocation[]): Intervention[] {
  const out: Intervention[] = []
  for (const inv of invocations) {
    const verdict = verdictOf(inv)
    if (verdict !== 'deny' && verdict !== 'ask') continue
    const at = parseServerTime(inv.first_seen_at)
    if (at === null || !inv.session_id) continue
    out.push({
      invocationId: inv.invocation_id, sessionId: inv.session_id, at, verdict,
      tool: inv.tool_name ?? 'a tool', reason: inv.pre_tool?.policy_reason ?? 'no reason recorded', runtime: inv.runtime,
    })
  }
  return out.sort((a, b) => a.at - b.at)
}

/** "Denied: write_file. destructive action" — the one line shown on hover and read by a screen reader. */
export function describeIntervention(i: Intervention): string {
  return `${i.verdict === 'deny' ? 'Denied' : 'Asked for approval'}: ${i.tool}. ${i.reason}`
}

export interface SessionRuntime {
  runtimes: string[]
  invocations: number
  allowed: number
  denied: number
  asked: number
  /** calls with a pre-tool record but no recorded decision */
  undecided: number
}

/** The runtime view of one session, from the recent invocations the console has. Null when it has none. */
export function sessionRuntime(invocations: readonly Invocation[], sessionId: string): SessionRuntime | null {
  const mine = invocations.filter((i) => i.session_id === sessionId)
  if (mine.length === 0) return null
  const runtimes = [...new Set(mine.map((i) => i.runtime).filter((r): r is string => Boolean(r)))].sort()
  let allowed = 0, denied = 0, asked = 0, undecided = 0
  for (const inv of mine) {
    const verdict = verdictOf(inv)
    if (verdict === 'allow') allowed += 1
    else if (verdict === 'deny') denied += 1
    else if (verdict === 'ask') asked += 1
    else undecided += 1
  }
  return { runtimes, invocations: mine.length, allowed, denied, asked, undecided }
}

/** Intervention marks for one lane, kept to the ones that fall on its visible span. */
export function interventionsForSession(all: readonly Intervention[], sessionId: string | undefined): Intervention[] {
  return sessionId ? all.filter((i) => i.sessionId === sessionId) : []
}
