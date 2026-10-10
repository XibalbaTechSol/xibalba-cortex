// Operations: whether the store is healthy and ready, what is queued, how well embedding covers it,
// which features and connectors are on, and what stands between this profile and production.
//
// All read-only, from /api/operations plus /readyz and /metrics. The snapshot's own disclaimer is
// shown as given: this is local evidence, not a deployment, SLA or compliance claim.

import { useState, type ReactNode } from 'react'
import { api } from '../../api'
import { useAsync } from '../useAsync'
import { describeCoverage, labelText, parsePrometheus, sum } from '../ops'
import { IconWarn } from '../icons'
import { Page } from './Page'

const tone = (ok: boolean) => (ok ? 'xc-tag--anchored' : 'xc-tag--conflict')
const state = (value: string) => (/^(healthy|ok|ready|implemented|active)$/i.test(value) ? 'xc-tag--anchored' : /^(degraded|local_only|planned)$/i.test(value) ? 'xc-tag--review' : '')

function Card({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="xc-win xc-opscard" aria-label={title}>
      <p className="xc-eyebrow">{title}</p>
      {note && <p className="xc-note">{note}</p>}
      {children}
    </section>
  )
}

function Counts({ counts, empty }: { counts: Record<string, number> | undefined; empty: string }) {
  const entries = Object.entries(counts ?? {})
  if (entries.length === 0) return <p className="xc-note">{empty}</p>
  return <dl className="xc-kv">{entries.map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{v.toLocaleString()}</dd></div>)}</dl>
}

export function OperationsPage() {
  const [rev, setRev] = useState(0)
  const ops = useAsync(() => api.operations(), [rev], { keepData: true })
  const metrics = useAsync(() => api.metrics().then(parsePrometheus), [rev], { keepData: true })
  const [ready, setReady] = useState<{ ready: boolean; checks: Record<string, boolean | string> } | null>(null)
  const [readyError, setReadyError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const runReadiness = async () => {
    setChecking(true)
    setReadyError(null)
    try {
      setReady(await api.readiness())
    } catch (e) {
      setReadyError(e instanceof Error ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }

  const d = ops.data
  const coverage = d ? describeCoverage(d.embedding_coverage) : null

  return (
    <Page
      eyebrow="System"
      title="Operations"
      note={d?.disclaimer ?? 'Health, queues and readiness for this profile.'}
      actions={<button type="button" className="xc-btn" onClick={() => setRev((n) => n + 1)} disabled={ops.loading}>Refresh</button>}
    >
      {ops.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{ops.error}</div>}
      {ops.loading && !d && <p className="xc-note" role="status">Loading…</p>}
      {d && coverage && (
        <div className="xc-opsgrid">
          <Card title="Health">
            <p><span className={`xc-tag ${state(d.health.state)}`}><i />{d.health.state}</span> <span className="xc-meta">profile {d.profile_id}</span></p>
            <dl className="xc-kv">
              <div><dt>Schema</dt><dd>v{d.health.status.schema_version}</dd></div>
              <div><dt>Journal</dt><dd>{d.health.status.journal_mode}</dd></div>
              <div><dt>Identity mode</dt><dd>{d.health.status.identity_mode}</dd></div>
              <div><dt>Memories</dt><dd>{d.health.status.memory_count.toLocaleString()}</dd></div>
              <div><dt>Backup</dt><dd>{d.health.status.backup_ready ? d.health.status.backup_method.replace(/_/g, ' ') : 'not ready'}</dd></div>
              <div><dt>Integrity check</dt><dd>{d.health.status.integrity_check}</dd></div>
            </dl>
          </Card>

          <Card title="Readiness" note="The snapshot below is the fast check. The full check runs the store’s complete integrity check and can take a while on a large profile.">
            <p><span className={`xc-tag ${state(d.readiness.state)}`}><i />{d.readiness.state}</span></p>
            <ul className="xc-checks">
              {Object.entries(d.readiness.checks).map(([k, v]) => <li key={k}><span className={`xc-tag ${tone(v)}`}><i />{v ? 'pass' : 'fail'}</span> {k.replace(/_/g, ' ')}</li>)}
            </ul>
            <div className="xc-actions-row"><button type="button" className="xc-btn" onClick={runReadiness} disabled={checking}>{checking ? 'Checking…' : 'Run full readiness check'}</button></div>
            {readyError && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{readyError}</div>}
            {ready && (
              <div className={`xc-callout ${ready.ready ? 'xc-callout--anchored' : 'xc-callout--conflict'}`} role="status">
                <div>
                  <b>{ready.ready ? 'Ready' : 'Not ready'}</b>
                  <ul className="xc-checks">{Object.entries(ready.checks).map(([k, v]) => <li key={k}>{k.replace(/_/g, ' ')}: <b>{String(v)}</b></li>)}</ul>
                </div>
              </div>
            )}
          </Card>

          <Card title="Queues" note="Work waiting on a worker. Nothing here moves until a worker claims it.">
            <p className="xc-eyebrow xc-eyebrow--dim">Inference tasks · {sum(d.audit.inference_task_states).toLocaleString()}</p>
            <Counts counts={d.audit.inference_task_states} empty="No tasks." />
            <p className="xc-eyebrow xc-eyebrow--dim">Extraction proposals</p>
            <Counts counts={d.audit.proposal_states} empty="No proposals." />
          </Card>

          <Card title="Embeddings" note={d.embedding_coverage.model ? `${d.embedding_coverage.model.model_id} · ${d.embedding_coverage.model.dimension} dimensions · ${d.embedding_coverage.model.state}` : 'No embedding model registered.'}>
            <p><span className={`xc-tag ${coverage.tone === 'ok' ? 'xc-tag--anchored' : coverage.tone === 'conflict' ? 'xc-tag--conflict' : coverage.tone === 'review' ? 'xc-tag--review' : ''}`}><i />{coverage.percent} covered</span></p>
            <div className="xc-meter" role="img" aria-label={`Embedding coverage ${coverage.percent}`}><i style={{ width: `${Math.round(d.embedding_coverage.coverage_ratio * 100)}%` }} /></div>
            <p className="xc-note">{coverage.summary}</p>
            <dl className="xc-kv">
              <div><dt>Eligible</dt><dd>{d.embedding_coverage.eligible}</dd></div>
              <div><dt>Current</dt><dd>{d.embedding_coverage.current}</dd></div>
              <div><dt>Missing</dt><dd>{d.embedding_coverage.missing}</dd></div>
              <div><dt>Stale</dt><dd>{d.embedding_coverage.stale}</dd></div>
              <div><dt>Failed</dt><dd>{d.embedding_coverage.failed}</dd></div>
            </dl>
          </Card>

          <Card title="Audit" note="Counts of what the store has recorded.">
            <Counts counts={d.audit.memory_event_counts} empty="No events." />
            <dl className="xc-kv">
              <div><dt>Sessions</dt><dd>{d.audit.session_count}</dd></div>
              <div><dt>Forgotten memories</dt><dd>{d.audit.forgotten_memory_count}</dd></div>
              <div><dt>Linked to the Integrity DAG</dt><dd>{d.audit.integrity_links.linked_records} of {d.audit.integrity_links.total_memories}</dd></div>
            </dl>
          </Card>

          <Card title="Features">
            <ul className="xc-checks">{Object.entries(d.features).map(([k, on]) => <li key={k}><span className={`xc-tag ${on ? 'xc-tag--anchored' : ''}`}><i />{on ? 'on' : 'off'}</span> {k.replace(/_/g, ' ')}</li>)}</ul>
            <dl className="xc-kv">{Object.entries(d.quotas).map(([k, v]) => <div key={k}><dt>Quota · {k.replace(/_/g, ' ')}</dt><dd>{v === null ? 'unlimited' : v.toLocaleString()}</dd></div>)}</dl>
          </Card>

          <Card title="Connectors" note="Entry points that bring outside events into the store.">
            <ul className="xc-checks">
              {Object.entries(d.connectors).map(([k, c]) => (
                <li key={k}><span className={`xc-tag ${state(c.state)}`}><i />{c.state}</span> <b>{k.replace(/_/g, ' ')}</b> <span className="xc-meta xc-mono">{c.entrypoint}</span></li>
              ))}
            </ul>
          </Card>

          <Card title="Production" note="What this profile does not yet claim.">
            <p><span className={`xc-tag ${state(d.production.state)}`}><i />{d.production.state.replace(/_/g, ' ')}</span></p>
            <dl className="xc-kv">
              <div><dt>Active tokens</dt><dd>{d.production.active_tokens}</dd></div>
              <div><dt>Isolation</dt><dd>{d.production.isolation_model}</dd></div>
            </dl>
            <p className="xc-eyebrow xc-eyebrow--dim">Open gates</p>
            <ul className="xc-checks">{d.production.open_gates.map((g) => <li key={g}><span className="xc-tag xc-tag--review"><i />open</span> {g}</li>)}</ul>
          </Card>

          <Card title="Request metrics" note="Counters since this API process started.">
            {metrics.error && <p className="xc-note">Metrics unavailable: {metrics.error}</p>}
            <table className="xc-table">
              <tbody>
                {(metrics.data ?? []).map((m, i) => <tr key={i}><td className="xc-mono">{m.name.replace(/^xibalba_cortex_/, '')}{Object.keys(m.labels).length ? <span className="xc-meta"> {labelText(m.labels)}</span> : null}</td><td className="xc-mono" style={{ textAlign: 'right' }}>{m.value.toLocaleString()}</td></tr>)}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </Page>
  )
}
