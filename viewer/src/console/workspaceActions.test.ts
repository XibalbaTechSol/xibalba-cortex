import { describe, expect, it } from 'vitest'
import type { BackupResult, ImportResult } from '../api'
import { buildModel, defaultFacets } from './model'
import {
  ANCHOR_CONFIRMATION, BACKUP_CONFIRMATION, END_SESSION_CONFIRMATION, MAX_ATTACHMENT_BYTES, MAX_EXPORT_MEMORIES, MAX_IMPORT_BYTES,
  attachProblem, describeAnchor, describeBackup, describeExport, describeImport, describeLinkVerification, exportFilename, exportPlan,
  formatBytes, importProblem, reconciliationLine,
} from './workspaceActions'

// three timed memories (one superseded: hidden by default), one untimed
const model = buildModel({
  nodes: [
    { id: 'memory:a', type: 'memory', label: 'a', status: 'active', created_at: '2026-10-01 10:00:00', source: { kind: 'direct_user' } },
    { id: 'memory:b', type: 'memory', label: 'b', status: 'active', created_at: '2026-10-05 10:00:00', source: { kind: 'direct_user' } },
    { id: 'memory:c', type: 'memory', label: 'c', status: 'superseded', created_at: '2026-10-05 11:00:00', source: { kind: 'direct_user' } },
    { id: 'memory:d', type: 'memory', label: 'd', status: 'active', source: { kind: 'direct_user' } },
  ],
  edges: [],
} as never, new Map([
  ['a', { observedAt: '2026-10-01 10:00:00', createdAt: null, sessionId: null }],
  ['b', { observedAt: '2026-10-05 10:00:00', createdAt: null, sessionId: null }],
  ['c', { observedAt: '2026-10-05 11:00:00', createdAt: null, sessionId: null }],
]))
const T = (s: string) => Date.parse(s.replace(' ', 'T') + 'Z')

describe('exportPlan', () => {
  it('with no window, exports every memory the Filters show, untimed included', () => {
    const plan = exportPlan(model, defaultFacets(model), null)
    expect(plan.ids.sort()).toEqual(['a', 'b', 'd'])
    expect(plan.hiddenByFilters).toBe(1) // c is superseded, hidden by default
    expect(plan.untimedLeftOut).toBe(0)
  })
  it('with a window, leaves out what is outside it and what has no time, and counts both honestly', () => {
    const plan = exportPlan(model, defaultFacets(model), { from: T('2026-10-04 00:00:00'), to: T('2026-10-06 00:00:00') })
    expect(plan.ids).toEqual(['b'])
    expect(plan.inWindow).toBe(2)
    expect(plan.hiddenByFilters).toBe(1)
    expect(plan.untimedLeftOut).toBe(1)
  })
  it('exports a hidden memory once the Filters show it', () => {
    const facets = defaultFacets(model)
    facets.statuses.superseded = true
    expect(exportPlan(model, facets, null).ids.sort()).toEqual(['a', 'b', 'c', 'd'])
  })
  it('flags a bundle the server would refuse for size, and is empty without a model', () => {
    expect(exportPlan(null, null, null).ids).toEqual([])
    expect(MAX_EXPORT_MEMORIES).toBe(500)
  })
  it('says what will happen, and what the commitment does not show', () => {
    const plan = exportPlan(model, defaultFacets(model), { from: T('2026-10-04 00:00:00'), to: T('2026-10-06 00:00:00') })
    const text = describeExport(plan, { from: 0, to: 1 }).join(' ')
    expect(text).toMatch(/1 memory will be exported as one provenance bundle/)
    expect(text).toMatch(/left out because Filters hide them/)
    expect(text).toMatch(/no timestamp/)
    expect(text).toMatch(/does not show they are true/)
    expect(describeExport({ ids: [], inWindow: 0, hiddenByFilters: 0, untimedLeftOut: 0, tooMany: false }, null)[0]).toMatch(/Nothing to export/)
  })
  it('names the file by time, with no characters a filesystem dislikes', () => {
    expect(exportFilename(new Date('2026-10-11T09:08:07.123Z'))).toBe('cortex-provenance-2026-10-11T09-08-07.json')
  })
})

describe('files', () => {
  it('refuses an empty or oversized attachment before sending it', () => {
    expect(attachProblem({ name: 'a.png', size: 0 })).toBe('That file is empty.')
    expect(attachProblem({ name: 'a.png', size: MAX_ATTACHMENT_BYTES + 1 })).toMatch(/at most 200 MB/)
    expect(attachProblem({ name: 'a.png', size: 5_000_000 })).toBeNull()
  })
  it('import takes text and says where other files belong', () => {
    expect(importProblem({ name: 'notes.md', size: 1000 })).toBeNull()
    expect(importProblem({ name: 'paper.pdf', size: 1000 })).toMatch(/attach it to a memory instead/)
    expect(importProblem({ name: 'big.txt', size: MAX_IMPORT_BYTES + 1 })).toMatch(/split a larger document/)
    expect(importProblem({ name: 'empty.txt', size: 0 })).toBe('That file is empty.')
  })
  it('formats sizes', () => {
    expect([formatBytes(12), formatBytes(2048), formatBytes(5 * 1024 * 1024), formatBytes(200 * 1024 * 1024)]).toEqual(['12 B', '2.0 KB', '5.0 MB', '200 MB'])
  })
  it('reports an import in words, including a repeat that stored nothing', () => {
    const base: ImportResult = { document: { name: 'relay.md', sha256: 'sha256:x', bytes: 10, sections: 3 }, imported: 3, already_present: 0, memory_ids: [], proposal_runs: 3, status: 'candidate', note: '' }
    expect(describeImport(base).join(' ')).toMatch(/3 of 3 sections of relay\.md stored as candidate memories.*proposals waiting in Review.*Nothing was added to the graph/)
    expect(describeImport({ ...base, imported: 0, already_present: 3 })).toEqual(['Nothing new: all 3 sections of relay.md were already in this workspace.'])
    expect(describeImport({ ...base, imported: 2, already_present: 1 })[0]).toMatch(/1 already present/)
  })
})

describe('link verification wording', () => {
  const r = (state: string, extra: object = {}) => ({ memory_id: 'm', node_id: 'n', verification_state: state, failure_reason: null, scope: 'byte_lineage_only', truth_authorization_completeness: false, anchored: false, ...extra })
  it('a match never reads as more than byte lineage', () => {
    const v = describeLinkVerification(r('hash_match_local'))
    expect(v.tone).toBe('anchored')
    expect(v.detail).toMatch(/byte-lineage check only/)
    expect(v.detail).toMatch(/not.*true, authorized or complete.*anchored on-chain/)
  })
  it('a mismatch, a missing node and an unlinked memory are three different findings', () => {
    expect(describeLinkVerification(r('verification_failed', { failure_reason: 'content_hash_mismatch' }))).toMatchObject({ tone: 'conflict', detail: expect.stringContaining('content hash mismatch') })
    expect(describeLinkVerification(r('content_unavailable', { failure_reason: 'integrity_dag_node_not_found' }))).toMatchObject({ tone: 'review', detail: expect.stringContaining('says nothing about whether they match') })
    expect(describeLinkVerification(r('unlinked'))).toMatchObject({ tone: 'none', title: 'This memory is not linked to a DAG node' })
  })
})

describe('outward actions say what they do before, and what they show after', () => {
  it('anchoring states that it leaves the machine and cannot be taken back', () => {
    expect(ANCHOR_CONFIRMATION.join(' ')).toMatch(/leaves this machine and cannot be taken back/)
    expect(describeAnchor({ anchored: true })).toMatchObject({ tone: 'anchored' })
    expect(describeAnchor({ anchored: true }).detail).toMatch(/does not by itself show external finality/)
    expect(describeAnchor({ anchored: false, error: 'agent a is not registered' })).toMatchObject({ tone: 'review', detail: 'agent a is not registered' })
  })
  it('a backup says it cannot choose where it goes, and that complete is not restorable', () => {
    expect(BACKUP_CONFIRMATION.join(' ')).toMatch(/you cannot choose where it goes/)
    const ok: BackupResult = { name: 'n', integrity_check: 'ok', schema_version: 16, reconciliation: { equal: true, domains: {} }, claim: 'The copy is complete … does not show it restores.' }
    expect(describeBackup(ok)).toMatchObject({ tone: 'anchored', title: 'The copy is complete' })
    expect(describeBackup({ ...ok, reconciliation: { equal: false, domains: {} } })).toMatchObject({ tone: 'conflict', title: 'The copy differs from the live store' })
    expect(describeBackup({ ...ok, integrity_check: 'malformed' })).toMatchObject({ tone: 'conflict', title: 'The copy failed its integrity check' })
    expect(describeBackup({ ...ok, reconciliation: null })).toMatchObject({ tone: 'anchored', title: 'The copy passed its integrity check' })
  })
  it('summarises a reconciliation', () => {
    const d = (equal: boolean) => ({ equal, live_leaf_count: 1, destination_leaf_count: 1 })
    expect(reconciliationLine({ equal: true, domains: { memories: d(true), entities: d(true) } })).toBe('memories, entities all match the live store as of now.')
    expect(reconciliationLine({ equal: false, domains: { memories: d(false), entities: d(true) } })).toMatch(/^memories differ from the live store/)
  })
  it('ending a session says it cannot be reopened', () => {
    expect(END_SESSION_CONFIRMATION.join(' ')).toMatch(/cannot be reopened/)
  })
})
