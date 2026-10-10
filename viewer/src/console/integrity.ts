// Verification logic for the Integrity drawer, kept free of React and fetch (the proof fetcher is
// injected) so what "verified here" means is unit-tested against proofs built by the Python store.
//
// What this proves, and what it does not: checking a proof recomputes hashes in this browser, so it
// shows the leaves and the root the server reported are internally consistent under the declared
// construction. It does not show the leaves themselves are the right ones (the server supplies
// them), nor truth, authorization, completeness or external anchoring. The wording in the UI says
// exactly that and no more.

import type { ProjectionCheckpoint } from '../api'
import { domainMerkleRoot, verifyDomainMerkleProof, type MerkleInclusionProofLike } from '../merkleVerify'

export type CheckpointCheck =
  | { state: 'match'; recomputed: string }
  | { state: 'mismatch'; recomputed: string | null }
  | { state: 'unverifiable'; reason: string }

/** Recompute a checkpoint's root from its own leaf hashes and compare with the stored root. */
export async function verifyCheckpoint(cp: Pick<ProjectionCheckpoint, 'root_hash' | 'leaf_hashes' | 'leaf_count'>): Promise<CheckpointCheck> {
  if (!Array.isArray(cp.leaf_hashes)) return { state: 'unverifiable', reason: 'the checkpoint carries no leaf hashes' }
  if (cp.leaf_hashes.length !== cp.leaf_count) {
    return { state: 'mismatch', recomputed: null }
  }
  try {
    const recomputed = await domainMerkleRoot('projection_checkpoint', cp.leaf_hashes)
    if (recomputed === null) {
      return cp.root_hash ? { state: 'mismatch', recomputed: null } : { state: 'unverifiable', reason: 'the projection was empty when it was checkpointed' }
    }
    return recomputed === cp.root_hash ? { state: 'match', recomputed } : { state: 'mismatch', recomputed }
  } catch (e) {
    return { state: 'unverifiable', reason: e instanceof Error ? e.message : String(e) }
  }
}

export interface SessionBatchResult {
  /** exchanges the server says the session has */
  exchangeCount: number
  /** proofs fetched and checked */
  checked: number
  /** proofs whose path recomputes to their stated root and whose index is the one asked for */
  verified: number
  /** indexes whose proof did not verify or could not be fetched */
  failed: number[]
  /** every checked proof names the same root */
  rootsAgree: boolean
  /** the batch root all proofs name (null if none/disagree) */
  root: string | null
  /** true when every exchange was checked, so the full root could be recomputed */
  complete: boolean
  /** with `complete`: the root recomputed from all leaves equals the stated root */
  recomputedMatches: boolean | null
}

export const MAX_PROOFS = 200

/**
 * Check inclusion proofs for a session's exchanges. `fetchProof(i)` returns the server's proof for
 * exchange i. Beyond MAX_PROOFS the check is a prefix and says so (`complete: false`).
 */
export async function verifySessionBatch(
  exchangeCount: number,
  fetchProof: (index: number) => Promise<MerkleInclusionProofLike>,
  max = MAX_PROOFS,
): Promise<SessionBatchResult> {
  const total = Math.min(exchangeCount, max)
  const failed: number[] = []
  const roots = new Set<string>()
  const payloads: string[] = []
  let verified = 0
  for (let i = 0; i < total; i += 1) {
    try {
      const proof = await fetchProof(i)
      payloads.push(proof.payload_hash)
      roots.add(proof.root)
      if (proof.index === i && (await verifyDomainMerkleProof(proof))) verified += 1
      else failed.push(i)
    } catch {
      failed.push(i)
      payloads.push('')
    }
  }
  const rootsAgree = roots.size <= 1
  const root = roots.size === 1 ? [...roots][0] : null
  const complete = total === exchangeCount && exchangeCount > 0
  let recomputedMatches: boolean | null = null
  if (complete && root && failed.length === 0) {
    recomputedMatches = (await domainMerkleRoot('exchange_batch', payloads)) === root
  }
  return { exchangeCount, checked: total, verified, failed, rootsAgree, root, complete, recomputedMatches }
}

/** One plain sentence for a batch result; never says more than was checked. */
export function describeBatch(r: SessionBatchResult): { tone: 'ok' | 'bad' | 'neutral'; text: string } {
  if (r.exchangeCount === 0) return { tone: 'neutral', text: 'This session has no exchanges, so there is nothing to prove inclusion of.' }
  if (r.failed.length > 0) {
    return { tone: 'bad', text: `${r.failed.length} of ${r.checked} inclusion proofs did not verify in this browser (exchange ${r.failed.slice(0, 5).map((n) => n + 1).join(', ')}${r.failed.length > 5 ? '…' : ''}).` }
  }
  if (!r.rootsAgree) return { tone: 'bad', text: 'The proofs name different roots, so they cannot all belong to one batch.' }
  if (r.complete && r.recomputedMatches === false) return { tone: 'bad', text: 'Every proof verifies, but the root recomputed from all leaves differs from the stated root.' }
  if (r.complete) return { tone: 'ok', text: `All ${r.checked} exchanges verified in this browser, and the root recomputed from every leaf matches.` }
  return { tone: 'neutral', text: `Verified the first ${r.checked} of ${r.exchangeCount} exchanges in this browser. The rest were not checked, so the full root was not recomputed.` }
}

/** Order integrity-link states for display: problems first, then by count. */
export function orderStates(states: Record<string, number>): Array<[string, number]> {
  const rank = (name: string) => (/fail|invalid|mismatch|error|missing/i.test(name) ? 0 : /verified|valid|ok/i.test(name) ? 2 : 1)
  return Object.entries(states).sort((a, b) => rank(a[0]) - rank(b[0]) || b[1] - a[1] || a[0].localeCompare(b[0]))
}

export const isProblemState = (name: string): boolean => /fail|invalid|mismatch|error|missing/i.test(name)
