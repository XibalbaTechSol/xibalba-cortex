// Sessions: every session in the workspace, and for the selected one its exchanges, replay,
// telemetry, decision trace and kernel intents. Also the cross-session invocation list.
//
// Everything here is read from the store. Recording an exchange and building exchanges from
// telemetry are the two writes, offered only in a writable workspace. Chain verification lives in
// the Integrity drawer; this page links to it rather than repeating it.

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api, type Exchange, type Session } from '../../api'
import { useConsole } from '../state'
import { useAsync, type AsyncState } from '../useAsync'
import { buildExchange } from '../actions'
import { elideHash, parseServerTime, shortStamp } from '../model'
import { INVOCATION_STATUS, describeKernelDecision, exchangeSummary, type Tone } from '../sessions'
import { kindCounts, metricRows } from '../verify'
import { IconWarn } from '../icons'
import { useMediaQuery } from '../useMediaQuery'
import { Page } from './Page'

const PAGE_SIZE = 30
type Tab = 'exchanges' | 'memories' | 'replay' | 'telemetry' | 'trace' | 'kernel'
const TABS: Array<[Tab, string]> = [['exchanges', 'Exchanges'], ['memories', 'Memories'], ['replay', 'Replay'], ['telemetry', 'Telemetry'], ['trace', 'Decision trace'], ['kernel', 'Kernel intents']]

const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? (value ?? '—') : shortStamp(ms)
}
const truncate = (value: string, max: number): string => (value.length > max ? `${value.slice(0, max - 1)}…` : value)

function Loading<T>({ state, empty, children }: { state: AsyncState<T>; empty?: (data: T) => boolean; children: (data: T) => React.ReactNode }) {
  if (state.loading && state.data === null) return <p className="xc-note" role="status">Loading…</p>
  if (state.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{state.error}</div>
  if (state.data === null) return null
  if (empty?.(state.data)) return <p className="xc-note">Nothing recorded.</p>
  return <>{children(state.data)}</>
}

const toneClass = (tone: Tone) => (tone === 'ok' ? 'xc-tag--anchored' : tone === 'review' ? 'xc-tag--review' : tone === 'conflict' ? 'xc-tag--conflict' : '')

export function SessionsPage() {
  const [view, setView] = useState<'sessions' | 'invocations'>('sessions')
  return (
    <Page eyebrow="Explore" title="Sessions" note="A session is one agent run: its exchanges form a hash chain, and its telemetry and decisions hang off it.">
      <div className="xc-tabs" role="tablist" aria-label="Sessions views">
        <button type="button" role="tab" className="xc-tab" aria-selected={view === 'sessions'} onClick={() => setView('sessions')}>Sessions</button>
        <button type="button" role="tab" className="xc-tab" aria-selected={view === 'invocations'} onClick={() => setView('invocations')}>Invocations</button>
      </div>
      {view === 'sessions' ? <SessionList /> : <Invocations />}
    </Page>
  )
}

// --- sessions ---------------------------------------------------------------------------------------

function SessionList() {
  const { workspace, revision, go, pageArg } = useConsole()
  const scope = workspace.scope
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(pageArg?.page === 'sessions' ? pageArg.arg : null)
  // opened from a session in the lens: aim at that one (the list shows the newest page first)
  useEffect(() => {
    if (pageArg?.page === 'sessions') { setSelected(pageArg.arg); setOffset(0) }
  }, [pageArg])
  const list = useAsync(() => api.sessionsPage(PAGE_SIZE, offset, scope), [scope, offset, revision], { keepData: true })
  const sessions = list.data?.sessions ?? []
  const current = sessions.find((s) => s.external_session_id === selected) ?? null
  // On a phone the list and the detail take turns: choosing a session opens it, Back returns to the list.
  const phone = useMediaQuery('(max-width: 760px)')
  const showList = !phone || !current
  const showDetail = !phone || current !== null

  return (
    <div className="xc-sessions">
      {showList && (
      <section className="xc-win xc-pane xc-sessions-list" aria-label="Session list">
        {list.error && <div className="xc-callout xc-callout--conflict" role="alert" style={{ margin: 16 }}><IconWarn />{list.error}</div>}
        <div className="xc-scroll">
          <ul className="xc-rows" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {sessions.map((s) => (
              <li key={s.id}>
                <button type="button" className="xc-session-row" aria-pressed={selected === s.external_session_id} onClick={() => setSelected(s.external_session_id)}>
                  <b className="xc-mono" title={s.external_session_id}>{s.external_session_id}</b>
                  <span className="xc-meta">{stamp(s.started_at)} · {s.ended_at ? `ended ${stamp(s.ended_at)}` : 'open'} · {s.retention_tier}</span>
                </button>
              </li>
            ))}
          </ul>
          {list.loading && sessions.length === 0 && <p className="xc-note" role="status" style={{ padding: 20 }}>Loading…</p>}
          {!list.loading && !list.error && sessions.length === 0 && <div className="xc-empty"><h3 className="xc-title">No sessions</h3><p>This workspace has not opened a session.</p></div>}
        </div>
        <div className="xc-pager">
          <span className="xc-note">{sessions.length > 0 ? `${offset + 1}–${offset + sessions.length}` : '0'}</span>
          <span className="xc-spacer" />
          <button type="button" className="xc-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
          <button type="button" className="xc-btn" disabled={!list.data?.has_more} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
        </div>
      </section>
      )}

      {showDetail && (
      <section className="xc-win xc-pane xc-sessions-detail" aria-label="Session detail">
        {current ? <SessionDetail session={current} onVerify={() => go('integrity')} onBack={phone ? () => setSelected(null) : undefined} /> : <div className="xc-empty"><h3 className="xc-title">Select a session</h3><p>Pick one on the left to see its exchanges, replay and telemetry.</p></div>}
      </section>
      )}
    </div>
  )
}

function SessionDetail({ session, onVerify, onBack }: { session: Session; onVerify: () => void; onBack?: () => void }) {
  const { workspace, reload, setNotice } = useConsole()
  const [tab, setTab] = useState<Tab>('exchanges')
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const id = session.external_session_id

  const build = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.buildSessionExchanges(id)
      setNotice(`Exchanges rebuilt from ${id}’s telemetry.`)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="xc-inspector-head">
        {onBack && <div><button type="button" className="xc-btn" onClick={onBack}>← All sessions</button></div>}
        <p className="xc-eyebrow">Session</p>
        <h3 className="xc-title xc-mono" style={{ wordBreak: 'break-all' }}>{id}</h3>
        <p className="xc-meta">{stamp(session.started_at)} → {session.ended_at ? stamp(session.ended_at) : 'open'} · {session.retention_tier} retention</p>
        <div className="xc-actions-row">
          <button type="button" className="xc-btn" onClick={onVerify}>Verify in Integrity</button>
          {workspace.canWrite && <button type="button" className="xc-btn" onClick={() => setRecording((v) => !v)} aria-expanded={recording}>Record exchange</button>}
          {workspace.canWrite && <button type="button" className="xc-btn" disabled={busy} onClick={build} title="Pairs this session’s tool-call telemetry with its memories to form exchanges">{busy ? 'Building…' : 'Build from telemetry'}</button>}
        </div>
        {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      </div>
      {recording && workspace.canWrite && <RecordExchange sessionId={id} onDone={() => { setRecording(false); setNotice('Exchange recorded.'); reload() }} />}
      <div className="xc-tabs" role="tablist" aria-label="Session sections">
        {TABS.map(([t, label]) => <button key={t} type="button" role="tab" className="xc-tab" aria-selected={tab === t} onClick={() => setTab(t)}>{label}</button>)}
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        {tab === 'exchanges' && <ExchangesTab id={id} />}
        {tab === 'memories' && <MemoriesTab id={id} />}
        {tab === 'replay' && <ReplayTab id={id} />}
        {tab === 'telemetry' && <TelemetryTab id={id} />}
        {tab === 'trace' && <TraceTab id={id} />}
        {tab === 'kernel' && <KernelTab id={id} />}
      </div></div>
    </>
  )
}

function RecordExchange({ sessionId, onDone }: { sessionId: string; onDone: () => void }) {
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const built = buildExchange({ sessionId, prompt, response })
    if (!built.ok) { setError(built.error); return }
    setBusy(true)
    setError(null)
    try {
      await api.recordModelExchange(built.payload)
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }
  return (
    <form className="xc-form xc-inspector-foot" onSubmit={submit} aria-label="Record exchange" style={{ maxHeight: 'none' }}>
      <p className="xc-note">Appends a prompt and response to this session’s hash chain. The prompt and response become memories.</p>
      <label className="xc-field">Prompt<textarea className="xc-input" rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} autoFocus /></label>
      <label className="xc-field">Model response<textarea className="xc-input" rows={3} value={response} onChange={(e) => setResponse(e.target.value)} /></label>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      <div className="xc-actions-row"><button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>{busy ? 'Recording…' : 'Record exchange'}</button></div>
    </form>
  )
}

function ExchangesTab({ id }: { id: string }) {
  const { workspace, revision, go, reveal } = useConsole()
  const list = useAsync(() => api.sessionExchanges(id, workspace.scope), [id, workspace.scope, revision])
  return (
    <Loading state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <ol className="xc-exchanges">
          {items.map((e: Exchange) => (
            <li key={e.id} className="xc-exchange">
              <div className="xc-card-top"><b className="xc-card-title">Exchange {e.sequence_number + 1}</b><span className="xc-meta">{stamp(e.prompt_time ?? e.response_time)}</span></div>
              {e.prompt_memories.map((m) => <p key={m.id} className="xc-turn"><span className="xc-meta">prompt</span> {truncate(m.content, 220)}</p>)}
              {e.response_memories.map((m) => <p key={m.id} className="xc-turn"><span className="xc-meta">response</span> {truncate(m.content, 220)}</p>)}
              <p className="xc-meta">{exchangeSummary(e)} · node <span className="xc-hash" title={e.node_id}>{elideHash(e.node_id)}</span></p>
              {e.context_contributions.length > 0 && (
                <details>
                  <summary className="xc-meta">Context memories</summary>
                  <ul className="xc-rows" style={{ listStyle: 'none', padding: 0, margin: '6px 0 0' }}>
                    {e.context_contributions.map((c) => (
                      <li key={c.contribution_id} className="xc-row"><i className="xc-row-dot" /><div className="xc-row-main">
                        <button type="button" className="xc-link" onClick={() => { go('graph'); reveal(`memory:${c.memory.id}`) }}>{truncate(c.memory.content, 110)}</button>
                        <p className="xc-meta">{c.context_kind.replace(/_/g, ' ')} · relevance {c.relevance ?? '—'}</p>
                      </div></li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </Loading>
  )
}

function ReplayTab({ id }: { id: string }) {
  const { workspace } = useConsole()
  const replay = useAsync(() => api.sessionReplay(id, workspace.scope), [id, workspace.scope])
  return (
    <Loading state={replay}>
      {(r) => (
        <>
          <div className={`xc-callout ${r.replayable ? 'xc-callout--anchored' : 'xc-callout--review'}`}>
            <div>
              <b>{r.replayable ? 'Replayable' : 'Not fully replayable'}</b>
              <div className="xc-note">{r.exchange_count} exchanges · {r.event_count} events · completeness: {r.completeness.status}{r.completeness.missing.length > 0 ? ` (${r.completeness.missing.length} gaps)` : ''}</div>
              <div className="xc-note">{r.disclaimer}</div>
            </div>
          </div>
          <ol className="xc-exchanges">
            {r.events.map((e) => (
              <li key={e.replay_index} className="xc-exchange">
                <div className="xc-card-top"><span className="xc-tag"><i />{e.event_type.replace(/_/g, ' ')}</span><span className="xc-meta">{stamp(e.timestamp)}</span></div>
                {e.content && <p className="xc-turn">{truncate(e.content, 260)}</p>}
                {e.tool_name && <p className="xc-meta xc-mono">{e.tool_name}</p>}
              </li>
            ))}
          </ol>
        </>
      )}
    </Loading>
  )
}

/** Every memory whose source cites this session, oldest first (GET /api/session/{id}/memories). */
function MemoriesTab({ id }: { id: string }) {
  const { workspace, revision, select, go } = useConsole()
  const list = useAsync(() => api.sessionMemories(id, workspace.scope), [id, workspace.scope, revision])
  return (
    <Loading state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <>
          <p className="xc-note">{items.length} memor{items.length === 1 ? 'y' : 'ies'} written under this session. Open one to see its history and provenance.</p>
          <div className="xc-rows">
            {items.map((m) => (
              <div className="xc-row" key={m.id}><i className="xc-row-dot" /><div className="xc-row-main">
                <div className="xc-row-top"><button type="button" className="xc-link" onClick={() => { select(`memory:${m.id}`); go('graph') }}>{truncate(m.content, 110)}</button></div>
                <p className="xc-meta">{m.status} · {m.evidence_class.replace(/_/g, ' ')} · {stamp(m.created_at)}</p>
              </div></div>
            ))}
          </div>
        </>
      )}
    </Loading>
  )
}

function TelemetryTab({ id }: { id: string }) {
  const { workspace, revision } = useConsole()
  const list = useAsync(() => api.sessionOtel(id, workspace.scope), [id, workspace.scope, revision])
  const summary = useAsync(() => api.sessionOtelSummary(id, workspace.scope), [id, workspace.scope, revision])
  return (
    <Loading state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <>
        {summary.data && (
          <section aria-label="Telemetry summary">
            <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Summary</p>
            <p className="xc-meta">{kindCounts(summary.data)}</p>
            {metricRows(summary.data).length > 0 && (
              <dl className="xc-kv" style={{ marginTop: 8 }}>
                {metricRows(summary.data).map((r) => <div key={r.name}><dt>{r.name}</dt><dd>{r.total} <span className="xc-meta">over {r.count}</span></dd></div>)}
              </dl>
            )}
          </section>
        )}
        <div className="xc-rows">
          {items.map((o) => (
            <div className="xc-row" key={o.id}><i className="xc-row-dot" /><div className="xc-row-main">
              <div className="xc-row-top"><span className="xc-mono">{o.name}</span><span className="xc-meta">{o.kind}{o.value !== null ? ` · ${o.value}${o.unit ? ` ${o.unit}` : ''}` : ''}</span></div>
              <p className="xc-meta">{stamp(o.created_at)}{o.trace_id ? ` · trace ${o.trace_id}` : ''}</p>
            </div></div>
          ))}
        </div>
        </>
      )}
    </Loading>
  )
}

function TraceTab({ id }: { id: string }) {
  const { workspace } = useConsole()
  const [draft, setDraft] = useState('')
  const [traceId, setTraceId] = useState('')
  const trace = useAsync(() => (traceId ? api.decisionTrace(id, traceId, workspace.scope) : Promise.resolve(null)), [id, traceId, workspace.scope])
  return (
    <>
      <form className="xc-memories-search" onSubmit={(e) => { e.preventDefault(); setTraceId(draft.trim()) }}>
        <input className="xc-input xc-input--mono" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Trace ID" aria-label="Trace ID" />
        <button type="submit" className="xc-btn" disabled={!draft.trim()}>Look up</button>
      </form>
      {!traceId && <p className="xc-note">Enter a decision trace ID for this session. Trace IDs are recorded by the runtime that wrote the decisions; this page cannot list them.</p>}
      {traceId && (
        <Loading state={trace}>
          {(t) => t === null ? null : t.events.length === 0 ? <p className="xc-note">No events for trace “{t.trace_id}” in this session.</p> : (
            <>
              <div className={`xc-callout ${t.valid ? 'xc-callout--anchored' : 'xc-callout--conflict'}`}>
                <div>
                  <b>Server reports the trace {t.valid ? 'valid' : 'INVALID'}</b>
                  <div className="xc-hash" title={t.root ?? undefined}>{t.root ? `root ${elideHash(t.root)}` : 'no root'}</div>
                  <div className="xc-note">{t.disclaimer}</div>
                </div>
              </div>
              <a className="xc-btn" href={api.decisionTraceHtmlUrl(id, t.trace_id, workspace.scope)} target="_blank" rel="noreferrer">Open the audit view</a>
              <ol className="xc-exchanges">
                {t.events.map((e) => (
                  <li key={e.event_id} className="xc-exchange">
                    <div className="xc-card-top"><b className="xc-card-title">#{e.sequence_number}</b><span className="xc-meta">{stamp(e.created_at)}</span></div>
                    <p className="xc-meta">event <span className="xc-hash" title={e.event_hash}>{elideHash(e.event_hash)}</span>{e.parent_event_hash ? <> · parent <span className="xc-hash" title={e.parent_event_hash}>{elideHash(e.parent_event_hash)}</span></> : ' · first event'}</p>
                    <details><summary className="xc-meta">Envelope</summary><pre className="xc-pre">{JSON.stringify(e.envelope, null, 2)}</pre></details>
                  </li>
                ))}
              </ol>
            </>
          )}
        </Loading>
      )}
    </>
  )
}

function KernelTab({ id }: { id: string }) {
  const { workspace, revision } = useConsole()
  const list = useAsync(() => api.kernelIntents(id, workspace.scope), [id, workspace.scope, revision])
  return (
    <>
      <p className="xc-note">Each row pairs what an agent declared it would do, the kernel’s decision, and what happened. Correlation only; it does not prove causality or execution.</p>
      <Loading state={list} empty={(l) => l.length === 0}>
        {(items) => (
          <ol className="xc-exchanges">
            {items.map((k) => {
              const d = describeKernelDecision(k.kernel_decision)
              return (
                <li key={`${k.invocation_id}-${k.tool_call_id}`} className="xc-exchange">
                  <div className="xc-card-top"><b className="xc-card-title xc-mono">{k.tool_name ?? 'tool'}</b><span className={`xc-tag ${toneClass(d.tone)}`}><i />{d.verdict}{d.detail ? ` · ${d.detail}` : ''}</span></div>
                  <p className="xc-turn"><span className="xc-meta">declared</span> {k.declared_intent.intent_rationale ?? '—'}</p>
                  <p className="xc-meta">outcome: {typeof k.actual_outcome?.outcome === 'string' ? k.actual_outcome.outcome : 'not yet recorded'} · correlated by {k.correlation_mode.replace(/_/g, ' ')}</p>
                </li>
              )
            })}
          </ol>
        )}
      </Loading>
    </>
  )
}

// --- invocations ------------------------------------------------------------------------------------

function Invocations() {
  const list = useAsync(() => api.invocations(100), [])
  const rows = useMemo(() => list.data ?? [], [list.data])
  return (
    <section className="xc-win xc-pane" aria-label="Invocations">
      <p className="xc-note" style={{ padding: '14px var(--window-padding) 0' }}>Recent runtime tool invocations across the store, correlated by invocation ID. This list is not scoped to one agent workspace.</p>
      <div className="xc-scroll">
        <Loading state={list} empty={(l) => l.length === 0}>
          {() => (
            <table className="xc-table xc-memories-table">
              <thead><tr><th>Last seen</th><th>Tool</th><th>Status</th><th>Kernel</th><th>Session</th></tr></thead>
              <tbody>
                {rows.map((i) => {
                  const st = INVOCATION_STATUS[i.runtime_status]
                  const d = describeKernelDecision(i.pre_tool?.kernel_decision)
                  return (
                    <tr key={i.invocation_id}>
                      <td className="xc-mono">{stamp(i.last_seen_at)}</td>
                      <td><b className="xc-mono">{i.tool_name ?? '—'}</b><span className="xc-meta xc-hash" title={i.invocation_id}>{elideHash(i.invocation_id, 8, 4)}</span></td>
                      <td><span className={`xc-tag ${toneClass(st.tone)}`} title={st.meaning}><i />{st.label}</span></td>
                      <td><span className={`xc-tag ${toneClass(d.tone)}`}><i />{d.verdict}</span></td>
                      <td className="xc-mono">{i.session_id}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Loading>
      </div>
    </section>
  )
}
