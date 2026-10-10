// Pure helpers for the Sessions page: how an invocation's state and a kernel decision are worded.
// Kept out of the component so the wording of a security-relevant state is tested, not eyeballed.

import type { Invocation } from '../api'

export type Tone = 'ok' | 'review' | 'conflict' | 'neutral'

export const INVOCATION_STATUS: Record<Invocation['runtime_status'], { label: string; tone: Tone; meaning: string }> = {
  complete: { label: 'complete', tone: 'ok', meaning: 'Intent and outcome were both recorded.' },
  awaiting_outcome: { label: 'awaiting outcome', tone: 'review', meaning: 'The intent was recorded but no outcome has arrived yet.' },
  orphan_outcome: { label: 'orphan outcome', tone: 'conflict', meaning: 'An outcome was recorded with no matching intent, which should not happen.' },
}

/** `kernel_decision` is whatever the adapter attached; show its verdict when it has one and say so when it does not. */
export function describeKernelDecision(decision: Record<string, unknown> | null | undefined): { verdict: string; tone: Tone; detail: string | null } {
  if (!decision || typeof decision !== 'object') return { verdict: 'no decision recorded', tone: 'neutral', detail: null }
  const raw = decision.verdict ?? decision.decision ?? decision.result
  const verdict = typeof raw === 'string' && raw ? raw : 'unspecified'
  const lower = verdict.toLowerCase()
  const tone: Tone = /^(allow|allowed|permit|permitted|ok|approve|approved)$/.test(lower) ? 'ok' : /^(deny|denied|block|blocked|reject|rejected)$/.test(lower) ? 'conflict' : 'review'
  const case_ = decision.matched_case ?? decision.reason
  return { verdict, tone, detail: typeof case_ === 'string' ? case_ : null }
}

/** One short line for an exchange's footer: counts only, nothing inferred. */
export function exchangeSummary(e: { context_contributions: unknown[]; tool_calls: unknown[]; latency_ms: number | null }): string {
  const parts = [
    `${e.context_contributions.length} context memor${e.context_contributions.length === 1 ? 'y' : 'ies'}`,
    `${e.tool_calls.length} tool call${e.tool_calls.length === 1 ? '' : 's'}`,
  ]
  if (e.latency_ms !== null) parts.push(`${e.latency_ms} ms`)
  return parts.join(' · ')
}
