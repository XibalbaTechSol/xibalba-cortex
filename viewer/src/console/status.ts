// Wording for the Operations status cards (runtimes, workers, connectors) and the vault lookup.
// Pure, so what the console tells a person about a worker or a vault is tested, not improvised in JSX.
//
// The rule behind every sentence here: say what the store knows and no more. A worker is described
// by the work it leaves behind (there is no heartbeat), a runtime by what it wrote, a connector by
// what the store can attribute to it. "Idle" and "not seen" are different claims.

import type { RuntimeRow, VaultLeafResult, WorkerRow, WorkerState } from '../api'
import { parseServerTime } from './model'

/** "3 minutes ago", "2 days ago"; "never" for null; "just now" under a minute. */
export function ago(iso: string | null, now: number = Date.now()): string {
  const at = iso ? parseServerTime(iso) : null
  if (at === null) return 'never'
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 60) return 'just now'
  const unit = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'} ago`
  if (seconds < 3600) return unit(Math.floor(seconds / 60), 'minute')
  if (seconds < 86_400) return unit(Math.floor(seconds / 3600), 'hour')
  return unit(Math.floor(seconds / 86_400), 'day')
}

export type Tone = 'anchored' | 'review' | 'conflict' | 'none'

export function workerTone(state: WorkerState): Tone {
  switch (state) {
    case 'working': case 'draining': case 'idle': return 'anchored'
    case 'backlog': case 'stalled': return 'review'
    case 'failing': return 'conflict'
    default: return 'none'
  }
}

/** One plain sentence per worker: the count that matters and the evidence for the state. */
export function workerSentence(w: WorkerRow, now: number = Date.now()): string {
  const last = w.last_activity_at ? `last activity ${ago(w.last_activity_at, now)}` : 'no activity recorded'
  switch (w.state) {
    case 'working': return `${w.in_flight} in flight${w.claimed_by.length ? ` (${w.claimed_by.join(', ')})` : ''}, ${w.pending} waiting; ${last}.`
    case 'draining': return `${w.pending} waiting and being worked through; ${last}.`
    case 'idle': return `Nothing waiting; ${last}.`
    case 'backlog': return `${w.pending} waiting${w.oldest_pending_at ? `, the oldest ${ago(w.oldest_pending_at, now)}` : ''}, and nothing has picked it up recently; ${last}.`
    case 'stalled': return `${w.stalled_leases} claimed and past its lease: whichever worker took it did not finish or release it; ${last}.`
    case 'failing': return `${w.failed_24h} failed in the last day against ${w.completed_24h ?? 0} completed; ${last}.`
    default: return 'No work of this kind has been seen.'
  }
}

/** Embedding backfill coverage as a sentence, when the worker row carries it. */
export function coverageSentence(w: WorkerRow): string | null {
  const c = w.coverage
  if (!c || c.eligible === null) return null
  const parts = [`${c.current ?? 0} of ${c.eligible} memories embedded`]
  if (c.missing) parts.push(`${c.missing} missing`)
  if (c.stale) parts.push(`${c.stale} stale`)
  if (c.failed) parts.push(`${c.failed} failed`)
  return `${parts.join(', ')}${c.model ? ` (${c.model})` : ''}.`
}

export function runtimeSentence(r: RuntimeRow, now: number = Date.now()): string {
  const calls = r.invocations ? `${r.invocations} tool call${r.invocations === 1 ? '' : 's'}` : 'no tool calls recorded'
  const stops = r.decisions.deny + r.decisions.ask
  const policy = r.invocations ? `, ${r.decisions.allow} allowed${stops ? `, ${r.decisions.deny} denied, ${r.decisions.ask} asked` : ''}` : ''
  return `${r.sessions} session${r.sessions === 1 ? '' : 's'}, ${r.memories} memor${r.memories === 1 ? 'y' : 'ies'}, ${calls}${policy}. Last wrote ${ago(r.last_seen_at, now)}.`
}

/** "0x" followed by 64 hex characters: the only shape the server will look up. */
export function leafHashProblem(input: string): string | null {
  const v = input.trim()
  if (!v) return 'Enter a leaf hash.'
  if (!/^0x[0-9a-fA-F]{64}$/.test(v)) return 'A leaf hash is 0x followed by 64 hexadecimal characters.'
  return null
}

export interface VaultVerdict { tone: Tone; title: string; detail: string }

/**
 * What a vault answer means, and what it does not. The vault records commit and test evidence for the
 * protocol's own development; it holds nothing about a memory, so "not found" says nothing about any
 * memory's integrity. "Could not read" is a different claim from "not found".
 */
export function describeVault(r: VaultLeafResult): VaultVerdict {
  if (r.error && !r.found) return { tone: 'review', title: 'The vault could not be read', detail: 'This is not "not found": the server could not read its vault, so nothing can be said about this leaf. Check the server log.' }
  if (!r.found) return { tone: 'none', title: 'Not in the vault', detail: 'No leaf with this hash is recorded. That says nothing about any memory: the vault holds commit and test evidence, not memory content.' }
  const recomputed = r.recomputed_hash_matches
  const hashNote = recomputed === true ? 'The hash was recomputed from the leaf’s own fields and matches.' : recomputed === false ? 'The hash recomputed from the leaf’s fields does NOT match the stored one: the vault entry has been altered or is malformed.' : 'The hash could not be recomputed.'
  if (recomputed === false) return { tone: 'conflict', title: 'Found, but the entry does not match its hash', detail: hashNote }
  if (r.error) return { tone: 'review', title: 'Found; the anchor list could not be read', detail: `${hashNote} Whether it is anchored is unknown.` }
  return r.anchored
    ? { tone: 'anchored', title: 'Found and anchored', detail: `${hashNote} A later anchor covers this leaf.` }
    : { tone: 'review', title: 'Found, not yet anchored', detail: `${hashNote} No anchor covers this leaf yet.` }
}

/**
 * Facets that show only memories of one source kind (the Graph and Timeline then show what a connector
 * brought in). Every other kind is switched off; classes, statuses and the rest are left as they are.
 */
export function onlySource<F extends { sources: Record<string, boolean> }>(facets: F, kind: string): F {
  const sources: Record<string, boolean> = {}
  for (const key of Object.keys(facets.sources)) sources[key] = key === kind
  sources[kind] = true
  return { ...facets, sources }
}
