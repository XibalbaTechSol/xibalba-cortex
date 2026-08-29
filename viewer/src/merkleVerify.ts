// Client-side reimplementation of xibalba_cortex.events's domain-separated Merkle proof
// verification (domain_leaf / merkle_parent / _wrap_domain_root in events.py). Deliberately
// independent of the server: the whole point of a Merkle inclusion proof is that the caller can
// check it themselves without trusting whatever the server says about it.

const DOMAIN_TAGS: Record<string, Uint8Array> = {
  projection_checkpoint: new TextEncoder().encode('xibalba.projection_checkpoint.v1'),
  retrieval_trace: new TextEncoder().encode('xibalba.retrieval_trace.v1'),
}

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.startsWith('sha256:') ? hex.slice(7) : hex
  const bytes = new Uint8Array(clean.length / 2)
  for (let i = 0; i < clean.length; i += 2) {
    bytes[i / 2] = parseInt(clean.slice(i, i + 2), 16)
  }
  return bytes
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')
}

function concatBytes(...arrays: Uint8Array[]): Uint8Array {
  const total = arrays.reduce((sum, a) => sum + a.length, 0)
  const result = new Uint8Array(total)
  let offset = 0
  for (const arr of arrays) {
    result.set(arr, offset)
    offset += arr.length
  }
  return result
}

async function sha256(bytes: Uint8Array): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as BufferSource)
  return new Uint8Array(digest)
}

function u64be(n: number): Uint8Array {
  const buf = new ArrayBuffer(8)
  new DataView(buf).setBigUint64(0, BigInt(n), false)
  return new Uint8Array(buf)
}

async function domainLeaf(domain: string, index: number, payloadHash: string): Promise<Uint8Array> {
  const tag = DOMAIN_TAGS[domain]
  if (!tag) throw new Error(`unknown Merkle domain: ${domain}`)
  const marker = new TextEncoder().encode('\x00leaf\x00')
  return sha256(concatBytes(tag, marker, u64be(index), hexToBytes(payloadHash)))
}

async function merkleParent(left: Uint8Array, right: Uint8Array): Promise<Uint8Array> {
  const [a, b] = [bytesToHex(left), bytesToHex(right)].sort()
  return sha256(concatBytes(hexToBytes(a), hexToBytes(b)))
}

async function wrapDomainRoot(domain: string, innerRoot: Uint8Array): Promise<Uint8Array> {
  const tag = DOMAIN_TAGS[domain]
  const marker = new TextEncoder().encode('\x00root\x00')
  return sha256(concatBytes(tag, marker, innerRoot))
}

export interface MerkleInclusionProofLike {
  domain: string
  index: number
  payload_hash: string
  siblings: Array<{ hash: string }>
  root: string
}

export async function verifyDomainMerkleProof(proof: MerkleInclusionProofLike): Promise<boolean> {
  try {
    let current = await domainLeaf(proof.domain, proof.index, proof.payload_hash)
    for (const sibling of proof.siblings) {
      current = await merkleParent(current, hexToBytes(sibling.hash))
    }
    const wrapped = await wrapDomainRoot(proof.domain, current)
    return `sha256:${bytesToHex(wrapped)}` === proof.root
  } catch {
    return false
  }
}
