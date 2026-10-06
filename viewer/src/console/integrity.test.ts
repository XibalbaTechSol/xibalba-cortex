// Proofs and roots here come from the Python store (xibalba_cortex.events), see merkleVerify.test.ts.
import { describe, expect, it } from 'vitest'
import { describeBatch, orderStates, verifyCheckpoint, verifySessionBatch } from './integrity'

const leaves = [
  'sha256:d2dbf006f96dd05044a8f63d8f118f23925ba4cc5750f8b6c8e287fd506c8188',
  'sha256:4140bf0e8569ed03ec838871ff2f190e9b3ea86bc083d7e9901049f75f00e855',
  'sha256:649837ddcb7e1967086d7d35aaef7b975c513815d96fc6e70015e93a2bfe0f9a',
  'sha256:9fde56c376760bd399b82eb8569229a2dff19219411ac71154dfeab2cf502454',
  'sha256:697f943b9ec5f90eddda8ae7473f5eb688187e3467f312fefa8677dde255042c',
]
const ROOT = 'sha256:2ed231aacb98947f3e4743fdd59a796d3a4079cc0fdef8621f5c25ccfef4df18'
const proofs = [
  { domain: 'exchange_batch', index: 0, payload_hash: leaves[0], siblings: [{ hash: 'caeb2d38ca2931377a2abf2e0cf1775bac2792949bf17e1c2306cb75c8edde09' }, { hash: 'a4367cbeaac485bbb5f91eb226a8d1fadfcae4ae4417a4293e37b439834bbfe2' }, { hash: '7f496149be1d1e4be5f806276e02e9813de4cc50271bc6bd4a59edf19c2fe9eb' }], root: ROOT },
  { domain: 'exchange_batch', index: 1, payload_hash: leaves[1], siblings: [{ hash: '9cf5f34997ce5582e5803df2583aeda339c3b591fa53b3f3aaadca8ec0171b64' }, { hash: 'a4367cbeaac485bbb5f91eb226a8d1fadfcae4ae4417a4293e37b439834bbfe2' }, { hash: '7f496149be1d1e4be5f806276e02e9813de4cc50271bc6bd4a59edf19c2fe9eb' }], root: ROOT },
  { domain: 'exchange_batch', index: 2, payload_hash: leaves[2], siblings: [{ hash: 'f6488f853590a9987a561f1a78ba9947422eeebcc9798d396ae881e8523aea1e' }, { hash: '09e1212745455f57bf6c7123958c9e912ae55c1ad51abc9192d30891253a043e' }, { hash: '7f496149be1d1e4be5f806276e02e9813de4cc50271bc6bd4a59edf19c2fe9eb' }], root: ROOT },
  { domain: 'exchange_batch', index: 3, payload_hash: leaves[3], siblings: [{ hash: 'bfc0ac94237ef20b1ac211ccae7897a15324387f288024245a591a82106fef5f' }, { hash: '09e1212745455f57bf6c7123958c9e912ae55c1ad51abc9192d30891253a043e' }, { hash: '7f496149be1d1e4be5f806276e02e9813de4cc50271bc6bd4a59edf19c2fe9eb' }], root: ROOT },
  { domain: 'exchange_batch', index: 4, payload_hash: leaves[4], siblings: [{ hash: '8403b200e019b38a4b0c2289cf4541f0ef06c93d0aa3eef2ca7c4e5fa1501d97' }], root: ROOT },
]
const serve = (list = proofs) => async (i: number) => list[i]

describe('verifyCheckpoint', () => {
  const cp = { root_hash: 'sha256:2b5c1ff234a6dd6c0029343a0632e0f8dc5206ceb66984002835e43f10f6d8e2', leaf_hashes: leaves, leaf_count: 5 }
  it('matches when the stored root is what the leaves produce', async () => {
    expect((await verifyCheckpoint(cp)).state).toBe('match')
  })
  it('flags a stored root that the leaves do not produce', async () => {
    expect((await verifyCheckpoint({ ...cp, root_hash: ROOT })).state).toBe('mismatch')
  })
  it('flags a leaf list that was edited or truncated', async () => {
    expect((await verifyCheckpoint({ ...cp, leaf_hashes: leaves.slice(0, 4) })).state).toBe('mismatch')
    expect((await verifyCheckpoint({ ...cp, leaf_hashes: [leaves[1], leaves[0], ...leaves.slice(2)] })).state).toBe('mismatch')
  })
  it('says an empty projection cannot be verified instead of passing it', async () => {
    expect((await verifyCheckpoint({ root_hash: '', leaf_hashes: [], leaf_count: 0 })).state).toBe('unverifiable')
  })
})

describe('verifySessionBatch', () => {
  it('verifies every exchange and recomputes the full root', async () => {
    const r = await verifySessionBatch(5, serve())
    expect(r).toMatchObject({ checked: 5, verified: 5, failed: [], rootsAgree: true, root: ROOT, complete: true, recomputedMatches: true })
    expect(describeBatch(r).tone).toBe('ok')
  })
  it('reports a tampered proof by exchange number', async () => {
    const bad = proofs.map((p, i) => (i === 2 ? { ...p, payload_hash: leaves[0] } : p))
    const r = await verifySessionBatch(5, serve(bad))
    expect(r.failed).toEqual([2])
    expect(describeBatch(r)).toMatchObject({ tone: 'bad' })
    expect(describeBatch(r).text).toContain('exchange 3')
  })
  it('rejects a proof served for the wrong index', async () => {
    const r = await verifySessionBatch(5, async (i) => proofs[i === 1 ? 2 : i])
    expect(r.failed).toContain(1)
  })
  it('treats a fetch error as a failure, not a pass', async () => {
    const r = await verifySessionBatch(5, async (i) => { if (i === 3) throw new Error('boom'); return proofs[i] })
    expect(r.failed).toEqual([3])
    expect(r.recomputedMatches).toBeNull()
  })
  it('detects proofs that name different roots', async () => {
    const r = await verifySessionBatch(5, async (i) => (i === 4 ? { ...proofs[4], root: leaves[0] } : proofs[i]))
    expect(r.rootsAgree).toBe(false)
  })
  it('says so when it only checked a prefix', async () => {
    const r = await verifySessionBatch(5, serve(), 3)
    expect(r).toMatchObject({ checked: 3, verified: 3, complete: false, recomputedMatches: null })
    expect(describeBatch(r).text).toContain('first 3 of 5')
  })
  it('has nothing to prove for an empty session', async () => {
    const r = await verifySessionBatch(0, serve())
    expect(describeBatch(r).tone).toBe('neutral')
  })
})

describe('orderStates', () => {
  it('puts problems first', () => {
    expect(orderStates({ verified: 10, failed: 1, pending: 3 }).map(([n]) => n)).toEqual(['failed', 'pending', 'verified'])
  })
})
