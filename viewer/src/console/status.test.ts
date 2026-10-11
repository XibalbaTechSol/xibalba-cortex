import { describe, expect, it } from 'vitest'
import type { RuntimeRow, WorkerRow } from '../api'
import { ago, coverageSentence, describeVault, leafHashProblem, runtimeSentence, workerSentence, workerTone } from './status'

const NOW = Date.parse('2026-10-11T12:00:00Z')
const worker = (over: Partial<WorkerRow>): WorkerRow => ({ id: 'para', label: 'PARA', state: 'idle', task_types: [], pending: 0, in_flight: 0, stalled_leases: 0, completed_24h: 0, failed_24h: 0, last_activity_at: null, oldest_pending_at: null, claimed_by: [], ...over })

describe('ago', () => {
  it('says how long, in the largest sensible unit', () => {
    expect(ago(null, NOW)).toBe('never')
    expect(ago('2026-10-11T11:59:40Z', NOW)).toBe('just now')
    expect(ago('2026-10-11T11:58:00Z', NOW)).toBe('2 minutes ago')
    expect(ago('2026-10-11T11:00:00Z', NOW)).toBe('1 hour ago')
    expect(ago('2026-10-08 12:00:00', NOW)).toBe('3 days ago')
    expect(ago('garbage', NOW)).toBe('never')
  })
})

describe('worker wording', () => {
  it('idle and backlog and not-seen are three different claims', () => {
    const idle = workerSentence(worker({ state: 'idle', last_activity_at: '2026-10-11T11:00:00Z' }), NOW)
    const backlog = workerSentence(worker({ state: 'backlog', pending: 4, oldest_pending_at: '2026-10-10T12:00:00Z' }), NOW)
    const unseen = workerSentence(worker({ state: 'no work seen' }), NOW)
    expect(idle).toMatch(/^Nothing waiting/)
    expect(backlog).toMatch(/4 waiting, the oldest 1 day ago, and nothing has picked it up/)
    expect(unseen).toBe('No work of this kind has been seen.')
    expect(new Set([idle, backlog, unseen]).size).toBe(3)
  })
  it('names who holds a claim and what is stuck', () => {
    expect(workerSentence(worker({ state: 'working', in_flight: 1, pending: 2, claimed_by: ['hermes-1'] }), NOW)).toMatch(/1 in flight \(hermes-1\), 2 waiting/)
    expect(workerSentence(worker({ state: 'stalled', stalled_leases: 2 }), NOW)).toMatch(/2 claimed and past its lease/)
    expect(workerSentence(worker({ state: 'failing', failed_24h: 5, completed_24h: 1 }), NOW)).toMatch(/5 failed in the last day against 1 completed/)
  })
  it('puts attention where it is needed: only a stuck or failing worker is not green', () => {
    expect(workerTone('idle')).toBe('anchored')
    expect(workerTone('working')).toBe('anchored')
    expect(workerTone('backlog')).toBe('review')
    expect(workerTone('stalled')).toBe('review')
    expect(workerTone('failing')).toBe('conflict')
    expect(workerTone('no work seen')).toBe('none')
  })
  it('states embedding coverage with what is missing', () => {
    const w = worker({ coverage: { eligible: 100, current: 90, missing: 6, stale: 3, failed: 1, model: 'bge-small' } })
    expect(coverageSentence(w)).toBe('90 of 100 memories embedded, 6 missing, 3 stale, 1 failed (bge-small).')
    expect(coverageSentence(worker({}))).toBeNull()
  })
})

describe('runtime wording', () => {
  it('summarises what a runtime wrote and what the policy did', () => {
    const r: RuntimeRow = { runtime: 'claude', sessions: 2, memories: 1, invocations: 3, decisions: { allow: 1, deny: 1, ask: 1, other: 0 }, outcomes: { success: 1, error: 0, other: 0 }, first_seen_at: null, last_seen_at: '2026-10-11T11:00:00Z', activity: 'recent', interventions: [] }
    expect(runtimeSentence(r, NOW)).toBe('2 sessions, 1 memory, 3 tool calls, 1 allowed, 1 denied, 1 asked. Last wrote 1 hour ago.')
    expect(runtimeSentence({ ...r, invocations: 0, decisions: { allow: 0, deny: 0, ask: 0, other: 0 } }, NOW)).toMatch(/no tool calls recorded\. Last wrote/)
  })
})

describe('vault lookup', () => {
  it('validates the hash shape before asking', () => {
    expect(leafHashProblem('')).toMatch(/Enter a leaf hash/)
    expect(leafHashProblem('0x1234')).toMatch(/64 hexadecimal/)
    expect(leafHashProblem(`0x${'ab'.repeat(32)}`)).toBeNull()
    expect(leafHashProblem(`  0x${'AB'.repeat(32)}  `)).toBeNull()
  })
  it('keeps "not found" and "could not read" apart, and never implies a memory was checked', () => {
    const missing = describeVault({ found: false, anchored: false })
    const unreadable = describeVault({ found: false, anchored: false, error: 'the vault could not be read' })
    expect(missing.title).toBe('Not in the vault')
    expect(missing.detail).toMatch(/says nothing about any memory/)
    expect(unreadable.title).toBe('The vault could not be read')
    expect(unreadable.tone).toBe('review')
    expect(missing.title).not.toBe(unreadable.title)
  })
  it('reports anchored, unanchored and tampered entries differently', () => {
    expect(describeVault({ found: true, anchored: true, recomputed_hash_matches: true })).toMatchObject({ tone: 'anchored', title: 'Found and anchored' })
    expect(describeVault({ found: true, anchored: false, recomputed_hash_matches: true })).toMatchObject({ tone: 'review', title: 'Found, not yet anchored' })
    expect(describeVault({ found: true, anchored: true, recomputed_hash_matches: false })).toMatchObject({ tone: 'conflict' })
    expect(describeVault({ found: true, anchored: false, recomputed_hash_matches: true, error: 'the vault could not be read' }).title).toMatch(/anchor list could not be read/)
  })
})

import { onlySource } from './status'
describe('onlySource', () => {
  it('turns every other source kind off and leaves the rest of the facets alone', () => {
    const facets = { classes: { memory: true }, sources: { direct_user: true, connector_event: true, imported_document: true } }
    const next = onlySource(facets, 'connector_event')
    expect(next.sources).toEqual({ direct_user: false, connector_event: true, imported_document: false })
    expect(next.classes).toBe(facets.classes)
    expect(facets.sources.direct_user).toBe(true) // the input is not mutated
  })
  it('still shows a kind the current sample has not seen yet', () => {
    expect(onlySource({ sources: { direct_user: true } }, 'connector_event').sources).toEqual({ direct_user: false, connector_event: true })
  })
})
