// Settings → Developer: connection facts and the trust vault lookup.
//
// The kernel-bridge self-test that used to live here was removed when the Phase I
// IntegrityKernel was archived in integrity-core (tag kernel-phase1-archive).

import { useState, type FormEvent } from 'react'
import { ApiError, api, getApiBaseUrl, type VaultLeafResult } from '../../../api'
import { describeVault, leafHashProblem } from '../../status'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'

export function DeveloperSection() {
  const health = useAsync(() => fetch(`${getApiBaseUrl()}/healthz`, { credentials: 'include' }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`healthz ${r.status}`)))), [])
  // Trust vault lookup: the vault is server configuration, so the browser sends only the hash.
  const [leaf, setLeaf] = useState('')
  const [looking, setLooking] = useState(false)
  const [vault, setVault] = useState<VaultLeafResult | null>(null)
  const [vaultProblem, setVaultProblem] = useState<string | null>(null)
  const lookUp = async (event: FormEvent) => {
    event.preventDefault()
    const bad = leafHashProblem(leaf)
    setVault(null)
    if (bad) { setVaultProblem(bad); return }
    setLooking(true); setVaultProblem(null)
    try {
      setVault(await api.vaultLeaf(leaf.trim()))
    } catch (e) {
      setVaultProblem(e instanceof ApiError && e.status === 503 ? 'No trust vault is configured on this server, so there is nothing to look up. An administrator sets XIBALBA_VAULT_DIR.' : e instanceof Error ? e.message : String(e))
    } finally {
      setLooking(false)
    }
  }
  const verdict = vault ? describeVault(vault) : null

  return (
    <div className="xc-form xc-settings-form">
      <section className="xc-win xc-opscard" aria-label="Connection">
        <p className="xc-eyebrow">Connection</p>
        <dl className="xc-kv">
          <div><dt>API base</dt><dd>{getApiBaseUrl() || 'this origin'}</dd></div>
          <div><dt>Liveness</dt><dd>{health.loading ? 'checking…' : health.error ? `unreachable — ${health.error}` : String((health.data as { status?: string } | null)?.status ?? 'unknown')}</dd></div>
          <div><dt>Profile</dt><dd>{String((health.data as { profile_id?: string } | null)?.profile_id ?? 'unknown')}</dd></div>
        </dl>
      </section>

      <form className="xc-win xc-opscard xc-form" aria-label="Trust vault lookup" onSubmit={(e) => void lookUp(e)}>
        <p className="xc-eyebrow">Trust vault lookup</p>
        <p className="xc-note">Looks a leaf hash up in the Integrity trust vault the server is configured with, and recomputes the hash from the leaf’s own fields. The vault records commit and test evidence for the protocol’s development: it holds nothing about a memory, so this cannot verify one.</p>
        <label className="xc-field">Leaf hash<input className="xc-input xc-input--mono" value={leaf} onChange={(e) => setLeaf(e.target.value)} placeholder={`0x${'…'.padEnd(8, '…')} (64 hexadecimal characters)`} spellCheck={false} autoComplete="off" /></label>
        <div className="xc-actions-row"><button type="submit" className="xc-btn xc-btn--primary" disabled={looking}>{looking ? 'Looking…' : 'Look up'}</button></div>
        {vaultProblem && <div className="xc-callout xc-callout--review" role="alert"><IconWarn />{vaultProblem}</div>}
        {verdict && (
          <div className={`xc-callout ${verdict.tone === 'anchored' ? 'xc-callout--anchored' : verdict.tone === 'conflict' ? 'xc-callout--conflict' : verdict.tone === 'review' ? 'xc-callout--review' : ''}`} role="status">
            <div style={{ minWidth: 0 }}>
              <b>{verdict.title}</b>
              <p className="xc-note">{verdict.detail}</p>
              {vault?.leaf && <dl className="xc-kv">{Object.entries(vault.leaf).map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd className="xc-mono">{String(v)}</dd></div>)}</dl>}
            </div>
          </div>
        )}
      </form>

    </div>
  )
}
