// Operations: agent runtimes, workers and connectors. Three read-only cards.
//
// They report what the store knows and lead back to the lenses; none of them starts, stops or drives
// anything (a person must not be able to impersonate a worker, and connector ingest is a machine
// protocol). Each says how it knows: a worker's state is derived from its queue, not a heartbeat.
// These are store-wide views, so they need an unbound operator credential; for anyone else the card
// says so instead of showing an error.

import { useState, type ReactNode } from 'react'
import { ApiError, api } from '../../api'
import { useConsole } from '../state'
import { useAsync } from '../useAsync'
import { IconWarn } from '../icons'
import { ago, coverageSentence, onlySource, runtimeSentence, workerSentence, workerTone } from '../status'
import { describeIntervention, type Intervention } from '../runtime'
import { parseServerTime } from '../model'
import { ConfirmPanel } from '../ConfirmPanel'
import { BACKUP_CONFIRMATION, describeBackup, formatBytes, reconciliationLine, type Verdict } from '../workspaceActions'

function Card({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="xc-win xc-opscard" aria-label={title}>
      <p className="xc-eyebrow">{title}</p>
      {note && <p className="xc-note">{note}</p>}
      {children}
    </section>
  )
}

const tagClass = (tone: string) => (tone === 'none' ? '' : `xc-tag--${tone}`)

/** Store-wide views are refused (403) for an agent-bound or non-operator credential: say that plainly. */
function Refused({ error }: { error: string }) {
  return /operator or admin|agent-bound|store-wide/i.test(error)
    ? <p className="xc-note" role="status">This view covers the whole store, so it needs an operator credential that is not bound to one agent.</p>
    : <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>
}

export function RuntimesCard() {
  const { go, select, model, openPage } = useConsole()
  const runtimes = useAsync(() => api.runtimes(), [])
  const rows = runtimes.data?.runtimes ?? []
  return (
    <Card title="Agent runtimes" note="Which runtimes have written to this store, and what the policy did with their tool calls. “Quiet” means it has not written lately; the store cannot tell quiet from down.">
      {runtimes.error ? <Refused error={runtimes.error} /> : runtimes.loading ? <p className="xc-note" role="status">Loading…</p> : rows.length === 0 ? (
        <p className="xc-note">No runtime has identified itself in this store yet.</p>
      ) : (
        <ul className="xc-list">
          {rows.map((r) => (
            <li key={r.runtime} className="xc-listrow xc-listrow--block">
              <span>
                <b>{r.runtime}</b> <span className={`xc-tag ${r.activity === 'recent' ? 'xc-tag--anchored' : ''}`}><i />{r.activity}</span>
                <br /><span className="xc-meta">{runtimeSentence(r)}</span>
                {r.interventions.slice(0, 3).map((i) => {
                  const node = model?.nodes.find((n) => n.cls === 'session' && n.sessionId === i.session_id)
                  const at = i.at ? parseServerTime(i.at) : null
                  const asIntervention: Intervention = { invocationId: i.invocation_id ?? '', sessionId: i.session_id ?? '', at: at ?? 0, verdict: i.verdict, tool: i.tool_name ?? 'a tool', reason: i.reason ?? 'no reason recorded', runtime: r.runtime }
                  return (
                    <span key={`${i.invocation_id}-${i.at}`} className="xc-meta xc-intervention">
                      <br />{describeIntervention(asIntervention)} {i.session_id && (
                        node
                          ? <button type="button" className="xc-link" onClick={() => { select(node.id); go('timeline') }}>Show on the Timeline</button>
                          : <button type="button" className="xc-link" onClick={() => openPage('sessions', i.session_id ?? undefined)}>Open the session</button>
                      )}
                    </span>
                  )
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function WorkersCard() {
  const workers = useAsync(() => api.workers(), [])
  const w = workers.data
  return (
    <Card title="Workers" note={w?.basis ?? 'The background workers that process queued tasks.'}>
      {workers.error ? <Refused error={workers.error} /> : workers.loading ? <p className="xc-note" role="status">Loading…</p> : (
        <ul className="xc-list">
          {(w?.workers ?? []).map((worker) => (
            <li key={worker.id} className="xc-listrow xc-listrow--block">
              <span>
                <b>{worker.label}</b> <span className={`xc-tag ${tagClass(workerTone(worker.state))}`}><i />{worker.state}</span>
                <br /><span className="xc-meta">{workerSentence(worker)}</span>
                {coverageSentence(worker) && <><br /><span className="xc-meta">{coverageSentence(worker)}</span></>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export function ConnectorsCard() {
  const { facets, setFacets, go } = useConsole()
  const connectors = useAsync(() => api.connectors(), [])
  const c = connectors.data
  const show = (kind: string) => { setFacets((prev) => (prev ? onlySource(prev, kind) : prev)); go('graph') }
  return (
    <Card title="Connectors and ingest" note={c?.basis ?? 'Entry points that bring outside events into the store.'}>
      {connectors.error ? <Refused error={connectors.error} /> : connectors.loading ? <p className="xc-note" role="status">Loading…</p> : (
        <>
          <ul className="xc-list">
            {(c?.connectors ?? []).map((k) => (
              <li key={k.name} className="xc-listrow">
                <span>
                  <b>{k.name.replace(/_/g, ' ')}</b> <span className={`xc-tag ${k.state === 'implemented' ? 'xc-tag--anchored' : ''}`}><i />{k.state ?? 'unknown'}</span>
                  <br /><span className="xc-meta xc-mono">{k.entrypoint}</span>
                  <br /><span className="xc-meta">
                    {k.evidence === null ? 'The store cannot attribute its memories to this connector, so no count is shown.'
                      : k.evidence.memories === 0 ? 'Nothing recorded from it yet.'
                      : `${k.evidence.memories} memor${k.evidence.memories === 1 ? 'y' : 'ies'}, last ${ago(k.evidence.last_at)}.`}
                  </span>
                </span>
                {k.evidence && k.evidence.memories > 0 && k.source_kind && facets && (
                  <button type="button" className="xc-btn" onClick={() => show(k.source_kind as string)}>Show these on the Graph</button>
                )}
              </li>
            ))}
          </ul>
          {(c?.webhook_senders ?? []).length > 0 && (
            <>
              <p className="xc-eyebrow xc-eyebrow--dim">Webhook senders</p>
              <dl className="xc-kv">{c!.webhook_senders.map((s) => <div key={s.connector}><dt>{s.connector}</dt><dd>{s.events} event{s.events === 1 ? '' : 's'}, last {ago(s.last_at)}</dd></div>)}</dl>
            </>
          )}
          {(c?.provider_telemetry ?? []).length > 0 && (
            <>
              <p className="xc-eyebrow xc-eyebrow--dim">Provider telemetry</p>
              <dl className="xc-kv">{c!.provider_telemetry.map((t) => <div key={t.provider}><dt>{t.provider}</dt><dd>{t.accepted} accepted · {t.duplicates} duplicate · {t.rejected} rejected{t.last_error ? ` · last error: ${t.last_error}` : ''}</dd></div>)}</dl>
            </>
          )}
        </>
      )}
    </Card>
  )
}




/**
 * Backup: write a verified copy of the whole store to the location the server is configured with, and
 * check a listed copy against the live store. The browser never chooses or sees a location: it asks, the
 * server names the file, and a check names a copy by the name the server listed. A complete copy is not
 * a restorable one, and the result says so.
 */
export function BackupCard() {
  const [rev, setRev] = useState(0)
  const backups = useAsync(() => api.backups(), [rev])
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Verdict | null>(null)
  const [checks, setChecks] = useState<Record<string, Verdict>>({})
  const [problem, setProblem] = useState<string | null>(null)

  const refuse = (e: unknown) => setProblem(e instanceof ApiError && e.status === 403 ? 'Backups cover the whole store, so they need an operator credential that is not bound to one agent.' : e instanceof Error ? e.message : String(e))

  const backUp = async () => {
    setBusy('backup'); setProblem(null); setOutcome(null)
    try {
      setOutcome(describeBackup(await api.backupNow()))
      setConfirming(false)
      setRev((n) => n + 1)
    } catch (e) {
      refuse(e)
    } finally {
      setBusy(null)
    }
  }
  const check = async (name: string) => {
    setBusy(name); setProblem(null)
    try {
      const r = await api.reconcileBackup(name)
      setChecks((c) => ({ ...c, [name]: { tone: r.reconciliation.equal ? 'anchored' : 'conflict', title: r.reconciliation.equal ? 'Matches the live store' : 'Differs from the live store', detail: reconciliationLine(r.reconciliation) } }))
    } catch (e) {
      refuse(e)
    } finally {
      setBusy(null)
    }
  }

  const list = backups.data
  return (
    <Card title="Backup" note="A verified copy of the whole store, written where this server is configured to put it. A copy that is complete is not shown to restore.">
      {backups.error ? <Refused error={backups.error} /> : backups.loading ? <p className="xc-note" role="status">Loading…</p> : !list?.configured ? (
        <p className="xc-note">No backup location is configured on this server, so no backup can be made. An administrator sets one (XIBALBA_BACKUP_DIR).</p>
      ) : (
        <>
          <div className="xc-actions-row">
            <button type="button" className="xc-btn xc-btn--primary" aria-expanded={confirming} onClick={() => setConfirming((v) => !v)} disabled={busy !== null}>Back up now</button>
          </div>
          {confirming && <ConfirmPanel title="Back up the store" lines={BACKUP_CONFIRMATION} confirmLabel="Write the backup" busy={busy === 'backup'} onConfirm={() => void backUp()} onCancel={() => setConfirming(false)} />}
          {problem && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{problem}</div>}
          {outcome && <BackupVerdict verdict={outcome} />}
          {list.backups.length === 0 ? <p className="xc-note">No backups have been made yet.</p> : (
            <ul className="xc-list">
              {list.backups.map((b) => (
                <li key={b.name} className="xc-listrow xc-listrow--block">
                  <span>
                    <b className="xc-mono">{b.name}</b>
                    <br /><span className="xc-meta">{formatBytes(b.bytes)} · {ago(b.modified_at)}</span>
                    {checks[b.name] && <><br /><BackupVerdict verdict={checks[b.name]} /></>}
                  </span>
                  <button type="button" className="xc-btn" disabled={busy !== null} onClick={() => void check(b.name)}>{busy === b.name ? 'Checking…' : 'Check against the live store'}</button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  )
}

function BackupVerdict({ verdict }: { verdict: Verdict }) {
  const cls = verdict.tone === 'anchored' ? 'xc-callout--anchored' : verdict.tone === 'conflict' ? 'xc-callout--conflict' : 'xc-callout--review'
  return <div className={`xc-callout ${cls}`} role="status"><div style={{ minWidth: 0 }}><b>{verdict.title}</b><div className="xc-note">{verdict.detail}</div></div></div>
}
