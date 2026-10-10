// Shared pieces for the server-side verification and export routes: the verdict callout every one
// of them renders through, the on-demand memory-chain check, and the provenance download.
//
// Everything here is the server's own report. The wording lives in ./verify (tested); nothing in
// this file is allowed to upgrade "the server recomputed it" into "verified" or "anchored".

import { useState } from 'react'
import { api, type ChainVerification, type Memory, type ProvenanceBundle, type WorkspaceScope } from '../api'
import { elideHash } from './model'
import { IconCheck, IconWarn } from './icons'
import { describeMemoryChain, provenanceFilename, type Verdict } from './verify'
import { saveBlob } from './download'

export function VerdictCallout({ verdict, hash, hashLabel = 'head' }: { verdict: Verdict; hash?: string | null; hashLabel?: string }) {
  const tone = verdict.tone === 'ok' ? 'anchored' : verdict.tone === 'bad' ? 'conflict' : 'review'
  return (
    <div className={`xc-callout xc-callout--${tone}`} role={verdict.tone === 'bad' ? 'alert' : 'status'}>
      {verdict.tone === 'ok' ? <IconCheck /> : <IconWarn />}
      <div style={{ minWidth: 0 }}>
        <b>{verdict.headline}</b>
        <div className="xc-note" style={{ marginTop: 4 }}>{verdict.detail}</div>
        {hash && <div className="xc-hash xc-hash--anchored" title={hash}>{hashLabel} {elideHash(hash)}</div>}
      </div>
    </div>
  )
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e))

/** Ask the server to recompute one memory's event chain, on demand (it is a read, but not free). */
export function MemoryChainCheck({ memoryId, scope }: { memoryId: string; scope: WorkspaceScope }) {
  const [result, setResult] = useState<ChainVerification | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.memoryVerifyChain(memoryId, scope))
    } catch (e) {
      setResult(null)
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Verify this history</p>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {result && <VerdictCallout verdict={describeMemoryChain(result)} hash={result.head_node_id} />}
      <div className="xc-actions-row" style={{ marginTop: 8 }}>
        <button type="button" className="xc-btn" disabled={busy} onClick={() => void run()}>{busy ? 'Verifying…' : result ? 'Verify again' : 'Ask the server to verify'}</button>
      </div>
    </section>
  )
}

/** Hand `data` to the browser as a JSON file. */
export function downloadJson(filename: string, data: unknown): void {
  saveBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
}

/** Fetch one memory's provenance bundle and save it, showing the commitment the server computed. */
export function ProvenanceExport({ memory, scope }: { memory: Memory; scope: WorkspaceScope }) {
  const [bundle, setBundle] = useState<ProvenanceBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      // a forgotten memory exports empty unless asked for, so ask for it when that is what was selected
      const b = await api.memoryProvenance(memory.id, memory.status === 'forgotten', scope)
      setBundle(b)
      downloadJson(provenanceFilename(memory.id), b)
    } catch (e) {
      setBundle(null)
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Export provenance</p>
      <p className="xc-note">Downloads this memory with a Merkle commitment the server computed over it. The commitment shows what was exported, not that it is true or externally anchored.</p>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {bundle && (
        <dl className="xc-kv" style={{ marginTop: 8 }}>
          <div><dt>Memories in bundle</dt><dd>{bundle.count}</dd></div>
          <div><dt>Root hash</dt><dd className="xc-hash" title={bundle.root_hash}>{elideHash(bundle.root_hash)}</dd></div>
          <div><dt>Schema</dt><dd>{bundle.schema_version}</dd></div>
        </dl>
      )}
      <div className="xc-actions-row" style={{ marginTop: 8 }}>
        <button type="button" className="xc-btn" disabled={busy} onClick={() => void run()}>{busy ? 'Exporting…' : bundle ? 'Export again' : 'Export bundle (JSON)'}</button>
      </div>
    </section>
  )
}
