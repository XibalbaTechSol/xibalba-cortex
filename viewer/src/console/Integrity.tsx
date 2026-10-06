// Integrity drawer: what can be checked about the memory store's own history, and where the check
// happens.
//
// Three tabs. Sessions fetches an inclusion proof for every exchange and verifies it in this
// browser. Checkpoints shows each projection's latest Merkle checkpoint and recomputes its root from
// its own leaf hashes here. Links shows the integrity-link verification states the server holds.
//
// Wording rule: say what was checked and by whom. "Server reports" for anything the server computed;
// "verified in this browser" only for hashes this page recomputed. Neither is a claim about truth,
// authorization or external anchoring, and the drawer says so.
//
// Projection checkpoints cover the whole store, not the selected agent workspace, so creating,
// reconciling or rebuilding one is labelled store-wide and needs a writable workspace.

import { useEffect, useId, useRef, useState } from 'react'
import { api, type ProjectionCheckpoint, type ProjectionReconciliation, type Session } from '../api'
import { useConsole } from './state'
import { loadMemoryIndex } from './data'
import { useAsync } from './useAsync'
import { useDialog } from './useDialog'
import { describeBatch, isProblemState, orderStates, verifyCheckpoint, verifySessionBatch, type CheckpointCheck, type SessionBatchResult } from './integrity'
import { elideHash, parseServerTime, shortStamp } from './model'
import { IconCheck, IconClose, IconWarn } from './icons'

type Tab = 'sessions' | 'checkpoints' | 'links'
const PROJECTIONS = ['memories', 'entities', 'relations'] as const

const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? (value ?? '—') : shortStamp(ms)
}

export function Integrity() {
  const { setOverlay } = useConsole()
  const [tab, setTab] = useState<Tab>('sessions')
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const close = () => setOverlay(null)
  useDialog(dialogRef, close, closeRef)

  return (
    <>
      <div className="xc-scrim" onClick={close} aria-hidden="true" />
      <aside ref={dialogRef} className="xc-win xc-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="xc-drawer-head">
          <div>
            <p className="xc-eyebrow">Integrity</p>
            <h2 className="xc-title" id={titleId}>What can be checked</h2>
          </div>
          <button ref={closeRef} type="button" className="xc-btn xc-btn--square" onClick={close} aria-label="Close Integrity"><IconClose /></button>
        </div>
        <p className="xc-note xc-drawer-note">
          Checks show hashes are consistent under the declared Merkle construction. They do not show that content is true, authorized, complete or externally anchored.
        </p>
        <div className="xc-tabs" role="tablist" aria-label="Integrity sections">
          {([['sessions', 'Sessions'], ['checkpoints', 'Checkpoints'], ['links', 'Links']] as const).map(([id, label]) => (
            <button key={id} type="button" role="tab" id={`ig-${id}`} className="xc-tab" aria-selected={tab === id} aria-controls="ig-panel" onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div className="xc-scroll" role="tabpanel" id="ig-panel" aria-labelledby={`ig-${tab}`}>
          <div className="xc-drawer-body">
            {tab === 'sessions' && <SessionsTab />}
            {tab === 'checkpoints' && <CheckpointsTab />}
            {tab === 'links' && <LinksTab />}
          </div>
        </div>
      </aside>
    </>
  )
}

// --- sessions ----------------------------------------------------------------------------------------

interface SessionState {
  busy: boolean
  error: string | null
  serverValid: boolean | null
  head: string | null
  batch: SessionBatchResult | null
}

function SessionsTab() {
  const { sessions, workspace } = useConsole()
  const [state, setState] = useState<Record<string, SessionState>>({})
  const scope = workspace.scope

  const verify = async (session: Session) => {
    const id = session.external_session_id
    setState((s) => ({ ...s, [id]: { busy: true, error: null, serverValid: null, head: null, batch: null } }))
    try {
      const root = await api.sessionMerkleRoot(id, scope)
      const batch = await verifySessionBatch(root.exchange_count, async (i) => (await api.sessionMerkleProof(id, i, scope)).proof)
      setState((s) => ({ ...s, [id]: { busy: false, error: null, serverValid: root.valid, head: root.root_node_id, batch } }))
    } catch (e) {
      setState((s) => ({ ...s, [id]: { busy: false, error: e instanceof Error ? e.message : String(e), serverValid: null, head: null, batch: null } }))
    }
  }

  if (sessions.length === 0) return <div className="xc-empty"><h3 className="xc-title">No sessions</h3><p>This workspace has no sessions to verify.</p></div>

  return (
    <ul className="xc-cards">
      {sessions.map((session) => {
        const st = state[session.external_session_id]
        const outcome = st?.batch ? describeBatch(st.batch) : null
        return (
          <li className="xc-card" key={session.id}>
            <div className="xc-card-top">
              <b className="xc-card-title xc-mono" title={session.external_session_id}>{session.external_session_id}</b>
              <span className="xc-meta">{stamp(session.started_at)}{session.ended_at ? '' : ' · open'}</span>
            </div>
            {st?.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{st.error}</div>}
            {st && st.serverValid !== null && (
              <div className={`xc-callout ${st.serverValid ? 'xc-callout--anchored' : 'xc-callout--conflict'}`}>
                {st.serverValid ? <IconCheck /> : <IconWarn />}
                <div style={{ minWidth: 0 }}>
                  <b>Server reports the exchange chain {st.serverValid ? 'valid' : 'INVALID'}</b>
                  <div className="xc-hash" title={st.head ?? undefined}>{st.head ? `head ${elideHash(st.head)}` : 'no head yet'}</div>
                </div>
              </div>
            )}
            {outcome && (
              <div className={`xc-callout ${outcome.tone === 'ok' ? 'xc-callout--anchored' : outcome.tone === 'bad' ? 'xc-callout--conflict' : 'xc-callout--review'}`} role="status">
                {outcome.tone === 'ok' ? <IconCheck /> : <IconWarn />}
                <div style={{ minWidth: 0 }}>
                  <b>Verified in this browser</b>
                  <div className="xc-note">{outcome.text}</div>
                  {st?.batch?.root && <div className="xc-hash xc-hash--anchored" title={st.batch.root}>batch root {elideHash(st.batch.root)}</div>}
                </div>
              </div>
            )}
            <div className="xc-actions-row">
              <button type="button" className="xc-btn" disabled={st?.busy} onClick={() => verify(session)}>{st?.busy ? 'Verifying…' : st?.batch ? 'Verify again' : 'Verify exchanges'}</button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

// --- checkpoints -------------------------------------------------------------------------------------

function CheckpointsTab() {
  return (
    <>
      <p className="xc-note">Projection checkpoints cover the whole store, not only the selected agent workspace.</p>
      <ul className="xc-cards">
        {PROJECTIONS.map((id) => <ProjectionCard key={id} projectionId={id} />)}
      </ul>
    </>
  )
}

function ProjectionCard({ projectionId }: { projectionId: (typeof PROJECTIONS)[number] }) {
  const { workspace } = useConsole()
  const canWrite = workspace.canWrite
  const [rev, setRev] = useState(0)
  // newest first; "latest" is its head. The list endpoint answers 200 with [] when there is none,
  // where the /latest endpoint answers 404, so this avoids a failed request as normal control flow.
  const history = useAsync(() => api.projectionCheckpoints(projectionId, 8), [projectionId, rev], { keepData: true })
  const [check, setCheck] = useState<CheckpointCheck | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recon, setRecon] = useState<ProjectionReconciliation | null>(null)
  const [confirmRebuild, setConfirmRebuild] = useState(false)

  const cp = history.data?.[0] ?? null
  useEffect(() => {
    setCheck(null)
    if (!cp) return
    let live = true
    verifyCheckpoint(cp).then((r) => { if (live) setCheck(r) })
    return () => { live = false }
  }, [cp])

  const act = async (name: 'checkpoint' | 'reconcile' | 'rebuild') => {
    setBusy(name)
    setError(null)
    try {
      if (name === 'checkpoint') await api.createProjectionCheckpoint(projectionId)
      if (name === 'reconcile') setRecon(await api.reconcileProjectionCheckpoint(projectionId))
      if (name === 'rebuild') { await api.rebuildProjectionCheckpoint(projectionId); setConfirmRebuild(false) }
      setRev((n) => n + 1)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const none = history.data !== null && history.data.length === 0
  return (
    <li className="xc-card">
      <div className="xc-card-top">
        <b className="xc-card-title">{projectionId}</b>
        {cp && <span className="xc-meta">{stamp(cp.created_at)}</span>}
      </div>
      {history.loading && !history.data && <p className="xc-note" role="status">Loading…</p>}
      {none && <p className="xc-note">No checkpoint recorded yet for this projection.</p>}
      {history.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{history.error}</div>}
      {cp && (
        <>
          <div className="xc-card-facts">
            <span className="xc-tag"><i />{cp.status}</span>
            <span className="xc-meta">{cp.leaf_count.toLocaleString()} leaves</span>
          </div>
          <div className="xc-hash" title={cp.root_hash}>root {elideHash(cp.root_hash)}</div>
          {check?.state === 'match' && <div className="xc-callout xc-callout--anchored"><IconCheck /><span>Root recomputed from its leaf hashes in this browser and it matches.</span></div>}
          {check?.state === 'mismatch' && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn /><span>The stored root does not match the root recomputed from its own leaf hashes{check.recomputed ? ` (${elideHash(check.recomputed)})` : ''}.</span></div>}
          {check?.state === 'unverifiable' && <div className="xc-callout xc-callout--review"><IconWarn /><span>Not verified here: {check.reason}.</span></div>}
          {cp.status !== 'active' && <p className="xc-note" style={{ color: 'var(--status-review)' }}>Server marks this checkpoint {cp.status}.</p>}
        </>
      )}
      {recon && (
        <div className={`xc-callout ${recon.equal ? 'xc-callout--anchored' : 'xc-callout--review'}`} role="status">
          {recon.equal ? <IconCheck /> : <IconWarn />}
          <div>
            <b>{recon.equal ? 'Live data matches the checkpoint' : 'Live data differs from the checkpoint'}</b>
            <div className="xc-note">
              {recon.reordered ? 'order changed · ' : ''}{recon.missing.length} missing · {recon.extra.length} extra · server suggests {recon.action.replace(/_/g, ' ')}
            </div>
          </div>
        </div>
      )}
      {history.data && history.data.length > 1 && (
        <details>
          <summary className="xc-meta">History ({history.data.length})</summary>
          <ul className="xc-rows" style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
            {history.data.map((h: ProjectionCheckpoint) => (
              <li className="xc-row" key={h.id}><i className="xc-row-dot" /><div className="xc-row-main"><div className="xc-row-top"><span className="xc-hash" title={h.root_hash}>{elideHash(h.root_hash)}</span><span className="xc-meta">{stamp(h.created_at)}</span></div><p className="xc-meta">{h.leaf_count} leaves · {h.status}</p></div></li>
            ))}
          </ul>
        </details>
      )}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {canWrite ? (
        <div className="xc-actions-row">
          {confirmRebuild ? (
            <>
              <p className="xc-note" style={{ flexBasis: '100%' }}>Rebuild recomputes this projection from the canonical store, for the whole store, and writes a new checkpoint.</p>
              <button type="button" className="xc-btn" disabled={busy !== null} onClick={() => setConfirmRebuild(false)}>Cancel</button>
              <button type="button" className="xc-btn xc-btn--primary" disabled={busy !== null} onClick={() => act('rebuild')}>{busy === 'rebuild' ? 'Rebuilding…' : 'Rebuild projection'}</button>
            </>
          ) : (
            <>
              <button type="button" className="xc-btn" disabled={busy !== null} onClick={() => act('checkpoint')}>{busy === 'checkpoint' ? 'Working…' : 'New checkpoint'}</button>
              <button type="button" className="xc-btn" disabled={busy !== null || !cp} onClick={() => act('reconcile')} title={cp ? undefined : 'Needs a checkpoint to compare against'}>{busy === 'reconcile' ? 'Working…' : 'Reconcile'}</button>
              <button type="button" className="xc-btn" disabled={busy !== null || !cp} onClick={() => setConfirmRebuild(true)}>Rebuild…</button>
            </>
          )}
        </div>
      ) : (
        <p className="xc-note">Read-only workspace: checkpoints can be inspected, not created.</p>
      )}
    </li>
  )
}

// --- integrity links ---------------------------------------------------------------------------------

function LinksTab() {
  const { reveal, setOverlay, workspace } = useConsole()
  const scope = workspace.scope
  // The endpoint is store-wide and takes no agent scope, so the sample is matched against this
  // workspace's own memory listing (same rule as Review) and the counts are labelled store-wide.
  const links = useAsync(async () => {
    const [status, index] = await Promise.all([api.integrityLinks(100), loadMemoryIndex(scope)])
    const sample = status.sample.filter((r) => index.info.has(r.memory_id))
    return { status, sample, hidden: status.sample.length - sample.length, complete: index.complete }
  }, [scope])
  if (links.loading) return <p className="xc-note" role="status">Loading…</p>
  if (links.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{links.error}</div>
  if (!links.data) return null
  const { status: d, sample, hidden, complete } = links.data
  return (
    <>
      <p className="xc-note">Integrity links tie a memory to a node on the Integrity DAG. States are the server’s own; this view does not re-verify them. Counts are for the whole store.</p>
      <dl className="xc-kv">
        <div><dt>Memories</dt><dd>{d.total_memories.toLocaleString()}</dd></div>
        <div><dt>Linked</dt><dd>{d.linked_records.toLocaleString()}</dd></div>
      </dl>
      <div className="xc-card-facts">
        {orderStates(d.states).map(([name, n]) => (
          <span key={name} className="xc-tag" style={isProblemState(name) ? { color: 'var(--status-conflict)' } : undefined}><i />{name.replace(/_/g, ' ')} · {n}</span>
        ))}
        {Object.keys(d.states).length === 0 && <span className="xc-note">No link states recorded.</span>}
      </div>
      {hidden > 0 && (
        <p className="xc-note">{hidden} sampled record{hidden === 1 ? '' : 's'} not matched to this workspace and not shown{complete ? '' : ' (only its newest memories are checked)'}.</p>
      )}
      {sample.length > 0 && (
        <ul className="xc-cards">
          {sample.map((r) => (
            <li className="xc-card" key={r.memory_id}>
              <div className="xc-card-top">
                <button type="button" className="xc-link xc-mono" onClick={() => { reveal(`memory:${r.memory_id}`); setOverlay(null) }} title={r.memory_id}>{elideHash(r.memory_id, 8, 4)}</button>
                <span className="xc-tag" style={isProblemState(r.verification_state) ? { color: 'var(--status-conflict)' } : undefined}><i />{r.verification_state.replace(/_/g, ' ')}</span>
              </div>
              {r.failure_reason && <p className="xc-note" style={{ color: 'var(--status-conflict)' }}>{r.failure_reason}</p>}
              {r.node_id && <div className="xc-hash" title={r.node_id}>node {elideHash(r.node_id)}</div>}
              {r.verified_at && <p className="xc-meta">verified {stamp(r.verified_at)}</p>}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
