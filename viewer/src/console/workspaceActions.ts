// The words and the arithmetic behind the console's write and outward actions: export a window,
// import a document, attach a file, verify a link, anchor a root, back up. Pure, so each claim the
// console makes after one of these is tested.
//
// Every action here follows the same rules, stated on screen next to the control: say what it does to
// the system BEFORE the person commits, say what the result does and does not show AFTER, and never
// show or ask for a path (the server owns every location).

import type { BackupResult, ImportResult, IntegrityLinkVerification, SessionAnchorResult } from '../api'
import { isNodeVisible, type Facets, type GraphModel, type TimeWindow } from './model'

export const MAX_EXPORT_MEMORIES = 500
export const MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024

// ---- export this window -----------------------------------------------------------------------------------

export interface ExportPlan {
  /** memory ids that will be in the bundle */
  ids: string[]
  /** timed memories inside the window, before filters */
  inWindow: number
  /** left out because a Filters switch hides them */
  hiddenByFilters: number
  /** with a window set: memories with no timestamp, which cannot be said to be inside it */
  untimedLeftOut: number
  /** more than the server accepts in one bundle */
  tooMany: boolean
}

/**
 * Which memories an export of the current view would contain. It is the memories you can SEE: inside
 * the time window and not hidden by Filters. With no window, memories that have no timestamp are
 * included (nothing excludes them); with a window they are left out and counted, because the console
 * cannot claim an untimed memory falls inside a window.
 */
export function exportPlan(model: GraphModel | null, facets: Facets | null, window: TimeWindow | null): ExportPlan {
  const empty: ExportPlan = { ids: [], inWindow: 0, hiddenByFilters: 0, untimedLeftOut: 0, tooMany: false }
  if (!model || !facets) return empty
  const ids: string[] = []
  let inWindow = 0
  let hidden = 0
  let untimedOut = 0
  for (const node of model.nodes) {
    if (node.cls !== 'memory' || !node.memoryId) continue
    const timed = node.time !== null
    if (window && !timed) { untimedOut += 1; continue }
    if (window && timed && (node.time! < window.from || node.time! > window.to)) continue
    inWindow += 1
    // facets only (the window was applied above, so untimed handling stays explicit)
    if (!isNodeVisible(node, facets, null)) { hidden += 1; continue }
    ids.push(node.memoryId)
  }
  return { ids, inWindow, hiddenByFilters: hidden, untimedLeftOut: untimedOut, tooMany: ids.length > MAX_EXPORT_MEMORIES }
}

export function describeExport(plan: ExportPlan, window: TimeWindow | null): string[] {
  const lines: string[] = []
  if (plan.ids.length === 0) return ['Nothing to export: no memory is both inside this window and shown by the Filters.']
  lines.push(`${plan.ids.length} memor${plan.ids.length === 1 ? 'y' : 'ies'} will be exported as one provenance bundle (JSON) with a Merkle commitment over them.`)
  if (plan.hiddenByFilters > 0) lines.push(`${plan.hiddenByFilters} more in the ${window ? 'window' : 'workspace'} ${plan.hiddenByFilters === 1 ? 'is' : 'are'} left out because Filters hide them.`)
  if (plan.untimedLeftOut > 0) lines.push(`${plan.untimedLeftOut} memor${plan.untimedLeftOut === 1 ? 'y has' : 'ies have'} no timestamp, so ${plan.untimedLeftOut === 1 ? 'it cannot' : 'they cannot'} be placed inside a window and ${plan.untimedLeftOut === 1 ? 'is' : 'are'} left out. Clear the window to include ${plan.untimedLeftOut === 1 ? 'it' : 'them'}.`)
  if (plan.tooMany) lines.push(`A bundle holds at most ${MAX_EXPORT_MEMORIES} memories. Narrow the window or the Filters.`)
  lines.push('Forgotten memories are never included. The commitment shows these memories are in this bundle; it does not show they are true.')
  return lines
}

export function exportFilename(now: Date = new Date()): string {
  return `cortex-provenance-${now.toISOString().replace(/[:.]/g, '-').slice(0, 19)}.json`
}

// ---- uploads -----------------------------------------------------------------------------------------------

/** A reason this file cannot be attached, or null. The server checks again; this saves the wait. */
export function attachProblem(file: { name: string; size: number }): string | null {
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_ATTACHMENT_BYTES) return `That file is ${formatBytes(file.size)}. An attachment can be at most ${formatBytes(MAX_ATTACHMENT_BYTES)}.`
  return null
}

export function importProblem(file: { name: string; size: number }): string | null {
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_IMPORT_BYTES) return `That file is ${formatBytes(file.size)}. Import takes text or Markdown up to ${formatBytes(MAX_IMPORT_BYTES)}; split a larger document.`
  if (/\.(pdf|docx?|xlsx?|pptx?|png|jpe?g|gif|zip|gz|tar|bin|exe)$/i.test(file.name)) return 'Import takes text and Markdown. For another kind of file, attach it to a memory instead.'
  return null
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export function describeImport(r: ImportResult): string[] {
  const lines = [
    r.imported === 0
      ? `Nothing new: all ${r.already_present} section${r.already_present === 1 ? '' : 's'} of ${r.document.name} were already in this workspace.`
      : `${r.imported} of ${r.document.sections} section${r.document.sections === 1 ? '' : 's'} of ${r.document.name} stored as candidate memories${r.already_present ? `; ${r.already_present} already present` : ''}.`,
  ]
  if (r.imported > 0) lines.push('Entities and relations found in them are proposals waiting in Review. Nothing was added to the graph.')
  return lines
}

// ---- integrity link ----------------------------------------------------------------------------------------

export interface Verdict { tone: 'anchored' | 'review' | 'conflict' | 'none'; title: string; detail: string }

/**
 * What a link verification means. The server's own scope is "byte lineage only": the cited DAG node's
 * content hash was compared with this memory's content. It says nothing about truth, authorization,
 * completeness, ancestry to a root, or on-chain anchoring, and the wording keeps that attached to the
 * good result so a green tag is never read as more than it is.
 */
export function describeLinkVerification(r: IntegrityLinkVerification): Verdict {
  const bound = 'This is a byte-lineage check only: it does not show the memory is true, authorized or complete, or that it is anchored on-chain.'
  switch (r.verification_state) {
    case 'hash_match_local':
      return { tone: 'anchored', title: 'The cited node’s content matches', detail: `The DAG node’s content hash equals this memory’s current content. ${bound}` }
    case 'verification_failed':
      return { tone: 'conflict', title: 'The cited node does not match this memory', detail: `The DAG node’s content hash differs from this memory’s current content${r.failure_reason ? ` (${r.failure_reason.replace(/_/g, ' ')})` : ''}. The memory or the node changed after they were linked.` }
    case 'content_unavailable':
      return { tone: 'review', title: 'The cited node could not be found', detail: `${r.failure_reason ? r.failure_reason.replace(/_/g, ' ') : 'The node was not found'}. Nothing was compared, so this says nothing about whether they match.` }
    case 'unlinked':
      return { tone: 'none', title: 'This memory is not linked to a DAG node', detail: 'There is no node to compare against. Link states are recorded when an agent cites a node.' }
    default:
      return { tone: 'review', title: r.verification_state.replace(/_/g, ' '), detail: bound }
  }
}

// ---- anchoring ---------------------------------------------------------------------------------------------

export const ANCHOR_CONFIRMATION = [
  'This sends the session’s Merkle root to the anchor service this server is configured with.',
  'It leaves this machine and cannot be taken back.',
  'The root commits to the session’s content hashes; the content itself is not sent.',
]

export function describeAnchor(r: SessionAnchorResult): Verdict {
  if (r.anchored) return { tone: 'anchored', title: 'The root was sent', detail: 'The anchor service accepted the session root. That records that this root was submitted; it does not by itself show external finality.' }
  return { tone: 'review', title: 'The root was not anchored', detail: r.error ?? 'The anchor service did not accept it. Nothing is recorded as anchored.' }
}

// ---- backup ------------------------------------------------------------------------------------------------

export const BACKUP_CONFIRMATION = [
  'This writes a verified copy of the whole store to the backup location this server is configured with.',
  'It does not change the live store. The copy is named by the server; you cannot choose where it goes.',
]

export function describeBackup(r: BackupResult): Verdict {
  const sound = r.integrity_check === 'ok'
  const same = r.reconciliation ? r.reconciliation.equal : null
  if (!sound) return { tone: 'conflict', title: 'The copy failed its integrity check', detail: r.claim }
  if (same === false) return { tone: 'conflict', title: 'The copy differs from the live store', detail: r.claim }
  return { tone: 'anchored', title: same ? 'The copy is complete' : 'The copy passed its integrity check', detail: r.claim }
}

/** "3 domains match" / "memories differ" as a short line for a reconciliation summary. */
export function reconciliationLine(r: { equal: boolean; domains: Record<string, { equal: boolean; live_leaf_count: number | null; destination_leaf_count: number | null }> }): string {
  const names = Object.keys(r.domains)
  if (r.equal) return `${names.join(', ')} all match the live store as of now.`
  const differing = names.filter((n) => !r.domains[n].equal)
  return `${differing.join(', ')} differ from the live store. The live store may have changed since the copy was taken, or the copy is incomplete.`
}

// ---- ending a session -------------------------------------------------------------------------------------

export const END_SESSION_CONFIRMATION = [
  'Ending a session closes it for good: it cannot be reopened.',
  'Its exchanges are built into a Merkle chain, and a summary is queued for the summary worker.',
  'The agent that opened it can no longer add to it.',
]
