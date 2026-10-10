// Vectors below were produced by the Python reference (xibalba_cortex.events.domain_merkle_root /
// domain_merkle_proof) so this file pins the browser implementation to the server's construction,
// not to itself.
import { describe, expect, it } from 'vitest'
import { domainMerkleRoot, verifyDomainMerkleProof } from './merkleVerify'

const leaves = [
  'sha256:d2dbf006f96dd05044a8f63d8f118f23925ba4cc5750f8b6c8e287fd506c8188',
  'sha256:4140bf0e8569ed03ec838871ff2f190e9b3ea86bc083d7e9901049f75f00e855',
  'sha256:649837ddcb7e1967086d7d35aaef7b975c513815d96fc6e70015e93a2bfe0f9a',
  'sha256:9fde56c376760bd399b82eb8569229a2dff19219411ac71154dfeab2cf502454',
  'sha256:697f943b9ec5f90eddda8ae7473f5eb688187e3467f312fefa8677dde255042c',
]

describe('domainMerkleRoot', () => {
  it('matches the Python reference for odd and even leaf counts', async () => {
    expect(await domainMerkleRoot('projection_checkpoint', leaves)).toBe('sha256:2b5c1ff234a6dd6c0029343a0632e0f8dc5206ceb66984002835e43f10f6d8e2')
    expect(await domainMerkleRoot('projection_checkpoint', leaves.slice(0, 1))).toBe('sha256:d8e4e7aa70a5c5f185b356bead934d1b10bbd49e737bbaa8dc61c10a2a8f4cda')
    expect(await domainMerkleRoot('projection_checkpoint', leaves.slice(0, 2))).toBe('sha256:59af8e45313467a8c086115af1342e53e42a1ead66fc65e6e3370c8b2cc147c8')
  })
  it('is domain separated: same leaves, different domain, different root', async () => {
    expect(await domainMerkleRoot('exchange_batch', leaves)).toBe('sha256:2ed231aacb98947f3e4743fdd59a796d3a4079cc0fdef8621f5c25ccfef4df18')
  })
  it('commits to order', async () => {
    expect(await domainMerkleRoot('projection_checkpoint', [...leaves].reverse())).toBe('sha256:32f7b9cc5e70a7194ea02e49640603b28015af59e8ba61dd7b5c11aa672eb75e')
  })
  it('returns null for no leaves rather than inventing a root', async () => {
    expect(await domainMerkleRoot('projection_checkpoint', [])).toBeNull()
  })
  it('rejects an unknown domain', async () => {
    await expect(domainMerkleRoot('nope', leaves)).rejects.toThrow(/unknown Merkle domain/)
  })
})

describe('verifyDomainMerkleProof (exchange_batch)', () => {
  const proof2 = {
    domain: 'exchange_batch', index: 2, payload_hash: leaves[2],
    siblings: [
      { hash: 'f6488f853590a9987a561f1a78ba9947422eeebcc9798d396ae881e8523aea1e' },
      { hash: '09e1212745455f57bf6c7123958c9e912ae55c1ad51abc9192d30891253a043e' },
      { hash: '7f496149be1d1e4be5f806276e02e9813de4cc50271bc6bd4a59edf19c2fe9eb' },
    ],
    root: 'sha256:2ed231aacb98947f3e4743fdd59a796d3a4079cc0fdef8621f5c25ccfef4df18',
  }
  const proof4 = {
    domain: 'exchange_batch', index: 4, payload_hash: leaves[4],
    siblings: [{ hash: '8403b200e019b38a4b0c2289cf4541f0ef06c93d0aa3eef2ca7c4e5fa1501d97' }],
    root: 'sha256:2ed231aacb98947f3e4743fdd59a796d3a4079cc0fdef8621f5c25ccfef4df18',
  }
  it('accepts server-built proofs, including the odd last leaf', async () => {
    expect(await verifyDomainMerkleProof(proof2)).toBe(true)
    expect(await verifyDomainMerkleProof(proof4)).toBe(true)
  })
  it('rejects a tampered leaf, index, sibling or root', async () => {
    expect(await verifyDomainMerkleProof({ ...proof2, payload_hash: leaves[3] })).toBe(false)
    expect(await verifyDomainMerkleProof({ ...proof2, index: 3 })).toBe(false)
    expect(await verifyDomainMerkleProof({ ...proof2, siblings: [{ hash: '00'.repeat(32) }, ...proof2.siblings.slice(1)] })).toBe(false)
    expect(await verifyDomainMerkleProof({ ...proof2, root: proof2.root.replace(/.$/, '0') })).toBe(false)
  })
  it('fails closed on a malformed proof', async () => {
    expect(await verifyDomainMerkleProof({ ...proof2, domain: 'unknown' })).toBe(false)
    expect(await verifyDomainMerkleProof({ ...proof2, payload_hash: 'zz' })).toBe(false)
  })
})
