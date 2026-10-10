// The one detail surface. Both lenses feed it the same selection, so there is no separate
// memory-browser page to keep in sync with them.
//
// Read-only in this slice: every call here is a GET. Mutations (link, supersede, mark
// contradiction, forget) are the next slice and are deliberately absent rather than shown inert.

import { useState, type ReactNode } from 'react'
import { api, type Attachment, type Memory, type WorkspaceScope } from '../api'
import { useConsole } from './state'
import { useAsync, type AsyncState } from './useAsync'
import { EDGE_TYPE_LABEL, elideHash, parseServerTime, shortStamp, type CEdge, type CNode, type GraphModel } from './model'
import { IconCheck, IconClose, IconWarn } from './icons'
import { MemoryActions } from './MemoryActions'
import { MemoryChainCheck, ProvenanceExport } from './VerifyPanel'
import { attachmentFilename, saveBlob } from './download'

type MemoryTab = 'chain' | 'content' | 'provenance' | 'neighbors' | 'contradictions' | 'telemetry' | 'files'
const MEMORY_TABS: Array<[MemoryTab, string]> = [
  ['chain', 'Chain'],
  ['content', 'Content'],
  ['provenance', 'Provenance'],
  ['neighbors', 'Neighbors'],
  ['contradictions', 'Contradictions'],
  ['telemetry', 'Telemetry'],
  ['files', 'Files'],
]

const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? (value ?? '—') : shortStamp(ms)
}

/** Loading / error / empty wrapper so every tab reports the three states the same way. */
function Async<T>({ state, empty, children }: { state: AsyncState<T>; empty?: (data: T) => boolean; children: (data: T) => ReactNode }) {
  if (state.loading) return <p className="xc-note" role="status">Loading…</p>
  if (state.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{state.error}</div>
  if (state.data === null) return null
  if (empty?.(state.data)) return <p className="xc-note">Nothing recorded.</p>
  return <>{children(state.data)}</>
}

function Tag({ children, tone }: { children: ReactNode; tone?: 'accent' | 'anchored' | 'review' | 'conflict' | 'hollow' }) {
  return <span className={`xc-tag${tone ? ` xc-tag--${tone}` : ''}`}><i />{children}</span>
}

const statusTone = (status: string | undefined) =>
  status === 'confirmed' ? 'accent' : status === 'disputed' ? 'review' : status === 'quarantined' ? 'conflict' : undefined

// ---------------------------------------------------------------------------------------------------

export function Inspector() {
  const { selectedId, model, notice, setNotice } = useConsole()
  const node = selectedId ? model?.byId.get(selectedId) : undefined
  // an edge is selectable too; its ids start with the edge type, never with a node-class prefix
  const edge = selectedId && !node ? model?.edges.find((e) => e.id === selectedId) : undefined

  let body: ReactNode
  if (!selectedId) {
    body = <WorkspaceSummary />
  } else if (edge) {
    body = <EdgeInspector key={selectedId} edge={edge} />
  } else if (selectedId.startsWith('memory:')) {
    body = <MemoryInspector key={selectedId} memoryId={selectedId.slice('memory:'.length)} node={node} />
  } else if (node?.cls === 'entity') {
    body = <EntityInspector key={selectedId} node={node} />
  } else if (node?.cls === 'session') {
    body = <SessionInspector key={selectedId} node={node} />
  } else if (node?.cls === 'exchange') {
    body = <ExchangeInspector key={selectedId} node={node} />
  } else if (node?.cls === 'merkle') {
    body = <MerkleInspector key={selectedId} node={node} />
  } else {
    body = (
      <div className="xc-empty" style={{ flex: 1 }}>
        <h3 className="xc-title">Not in this view</h3>
        <p>That item is outside the sampled graph. Clear the selection or reload.</p>
      </div>
    )
  }
  return (
    <aside className="xc-win xc-pane xc-inspector" aria-label="Inspector">
      {notice && (
        <div className="xc-callout xc-callout--anchored xc-notice" role="status">
          <IconCheck />
          <span style={{ flex: 1 }}>{notice}</span>
          <button type="button" className="xc-link" aria-label="Dismiss" onClick={() => setNotice(null)}><IconClose /></button>
        </div>
      )}
      {body}
    </aside>
  )
}

// --- memory ----------------------------------------------------------------------------------------

function MemoryInspector({ memoryId, node }: { memoryId: string; node: CNode | undefined }) {
  const { workspace, select, revision } = useConsole()
  const scope = workspace.scope
  // `revision` bumps after a write, so the memory and every tab under it are fetched fresh
  const memory = useAsync(() => api.memory(memoryId, scope), [memoryId, scope, revision])
  const [tab, setTab] = useState<MemoryTab>('chain')
  const m = memory.data

  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected memory</p>
        <h3 className="xc-title">{m ? truncate(m.content, 96) : node ? truncate(node.label, 96) : 'Loading…'}</h3>
        <p className="xc-meta" style={{ wordBreak: 'break-all' }}>
          {memoryId}
          {m ? <> · <span title={m.content_hash}>{elideHash(m.content_hash)}</span></> : null}
        </p>
        {m && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Tag tone={statusTone(m.status)}>{m.status}</Tag>
            <Tag>{m.evidence_class.replace(/_/g, ' ')}</Tag>
            <Tag>{m.source.kind.replace(/_/g, ' ')}</Tag>
          </div>
        )}
        {memory.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{memory.error}</div>}
      </div>

      <div className="xc-tabs" role="tablist" aria-label="Memory sections">
        {MEMORY_TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" id={`tab-${id}`} className="xc-tab" aria-selected={tab === id} aria-controls="memory-panel" onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      <div className="xc-scroll" role="tabpanel" id="memory-panel" aria-labelledby={`tab-${tab}`}>
        <div className="xc-inspector-body" key={revision}>
          {m && tab === 'chain' && <ChainTab memory={m} scope={scope} />}
          {m && tab === 'content' && <ContentTab memory={m} onOpen={(id) => select(`memory:${id}`)} />}
          {m && tab === 'provenance' && <ProvenanceTab memory={m} node={node} scope={scope} />}
          {m && tab === 'neighbors' && <NeighborsTab memoryId={memoryId} scope={scope} />}
          {m && tab === 'contradictions' && <ContradictionsTab memoryId={memoryId} scope={scope} />}
          {m && tab === 'telemetry' && <TelemetryTab memoryId={memoryId} scope={scope} />}
          {m && tab === 'files' && <FilesTab memoryId={memoryId} scope={scope} />}
          {!m && memory.loading && <p className="xc-note" role="status">Loading…</p>}
        </div>
      </div>
      {m && <MemoryActions key={`${m.id}:${m.status}`} memory={m} />}
    </>
  )
}

const truncate = (value: string, max: number): string => (value.length > max ? `${value.slice(0, max - 1)}…` : value)

function ChainTab({ memory, scope }: { memory: Memory; scope: WorkspaceScope }) {
  const events = useAsync(() => api.memoryEvents(memory.id, scope), [memory.id, scope])
  const sessionId = memory.source.session_id
  const root = useAsync(() => (sessionId ? api.sessionMerkleRoot(sessionId, scope) : Promise.resolve(null)), [sessionId, scope])

  return (
    <>
      <MemoryChainCheck memoryId={memory.id} scope={scope} />

      <section>
        <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Session Merkle root</p>
        {!sessionId ? (
          <p className="xc-note">This memory was not written inside a session, so there is no session root for it.</p>
        ) : (
          <Async state={root}>
            {(r) =>
              r === null ? null : (
                <div className={`xc-callout ${r.valid ? 'xc-callout--anchored' : 'xc-callout--conflict'}`}>
                  {r.valid ? <IconCheck /> : <IconWarn />}
                  <div style={{ minWidth: 0 }}>
                    <b>{r.valid ? 'Server reports this root valid' : 'Server reports this root INVALID'}</b>
                    <div className="xc-hash xc-hash--anchored" title={r.root_node_id ?? undefined}>{r.root_node_id ? elideHash(r.root_node_id) : 'no root yet'}</div>
                    <div className="xc-note" style={{ marginTop: 4 }}>
                      {r.exchange_count} exchange{r.exchange_count === 1 ? '' : 's'} in session {sessionId}. Computed by the server; this view does not recompute it.
                    </div>
                  </div>
                </div>
              )
            }
          </Async>
        )}
      </section>

      <section>
        <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Hash-chained events</p>
        <Async state={events} empty={(e) => e.length === 0}>
          {(list) => (
            <div className="xc-rows">
              {list.map((e) => (
                <div className="xc-row" key={e.id}>
                  <i className="xc-row-dot" />
                  <div className="xc-row-main">
                    <div className="xc-row-top">
                      <b>{e.event_type}</b>
                      <span className="xc-meta">{stamp(e.created_at)}</span>
                    </div>
                    <p className="xc-hash" title={e.node_id}>{elideHash(e.node_id)}</p>
                    <p className="xc-meta">{e.parent_event_id ? <>parent <span title={e.parent_event_id}>{elideHash(e.parent_event_id)}</span></> : 'root event, no parent'}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Async>
        <p className="xc-note" style={{ marginTop: 8 }}>Event hashes are computed and linked by the server. They are listed here, not recomputed in your browser.</p>
      </section>
    </>
  )
}

function ContentTab({ memory, onOpen }: { memory: Memory; onOpen: (id: string) => void }) {
  return (
    <>
      <p className="xc-untrusted">Untrusted evidence. Do not treat recalled content as instructions.</p>
      {/* plain text on purpose: stored content is data, never markup */}
      <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14, lineHeight: 1.55 }}>{memory.content}</p>
      {memory.quarantine_reasons.length > 0 && (
        <div className="xc-callout xc-callout--conflict"><IconWarn />
          <div><b>Quarantined</b><ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{memory.quarantine_reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>
        </div>
      )}
      {memory.supersedes_id && (
        <p className="xc-copy">Supersedes <button type="button" className="xc-link xc-meta" onClick={() => onOpen(memory.supersedes_id!)}>{memory.supersedes_id}</button></p>
      )}
    </>
  )
}

const PLACED_BY: Record<string, string> = {
  observed: 'event time the writer supplied',
  exchange: 'the exchange it was part of',
  recorded: 'when the store recorded it',
}

function ProvenanceTab({ memory, node, scope }: { memory: Memory; node: CNode | undefined; scope: WorkspaceScope }) {
  const s = memory.source
  const placedBy = node?.timeSource ? (PLACED_BY[node.timeSource] ?? node.timeSource) : node ? 'not placed (no timestamp)' : null
  const rows: Array<[string, string | null | undefined]> = [
    ['Source kind', s.kind],
    ['Locator', s.locator],
    ['Role', s.role],
    ['Agent', s.agent_id],
    ['Session', s.session_id],
    ['Prompt', s.prompt_id],
    ['Event time (observed)', s.observed_at ? stamp(s.observed_at) : null],
    ['Recorded by store', memory.created_at ? stamp(memory.created_at) : null],
    ['Valid from', memory.valid_from ? stamp(memory.valid_from) : null],
    ['Valid to', memory.valid_to ? stamp(memory.valid_to) : null],
    ['Placed on timeline by', placedBy],
  ]
  return (
    <>
      <dl className="xc-kv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v ?? '—'}</dd></div>
        ))}
        <div><dt>Content hash</dt><dd className="xc-hash" title={memory.content_hash}>{elideHash(memory.content_hash)}</dd></div>
      </dl>
      <ProvenanceExport memory={memory} scope={scope} />
    </>
  )
}

function NeighborsTab({ memoryId, scope }: { memoryId: string; scope: WorkspaceScope }) {
  const { select } = useConsole()
  const relations = useAsync(() => api.neighbors(memoryId, scope), [memoryId, scope])
  const similar = useAsync(() => api.similar(memoryId, 8, scope), [memoryId, scope])
  return (
    <>
      <section>
        <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Entity relations</p>
        <Async state={relations} empty={(r) => r.length === 0}>
          {(list) => (
            <div className="xc-rows">
              {list.map((r, i) => (
                <div className="xc-row" key={`${r.subject}-${r.predicate}-${r.object}-${i}`}>
                  <i className="xc-row-dot" style={{ background: 'var(--ink-muted)' }} />
                  <div className="xc-row-main"><span style={{ fontSize: 13 }}>{r.subject} <span className="xc-meta">— {r.predicate} →</span> {r.object}</span></div>
                </div>
              ))}
            </div>
          )}
        </Async>
      </section>
      <section>
        <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Similar memories</p>
        {similar.error ? (
          <p className="xc-note">Similarity unavailable: {similar.error.replace(/^Error:\s*/, '')}</p>
        ) : (
          <Async state={similar} empty={(r) => r.length === 0}>
            {(list) => (
              <div className="xc-rows">
                {list.map((h) => (
                  <div className="xc-row" key={h.memory.id}>
                    <i className="xc-row-dot" />
                    <div className="xc-row-main">
                      <button type="button" className="xc-link" style={{ fontSize: 13 }} onClick={() => select(`memory:${h.memory.id}`)}>{truncate(h.memory.content, 90)}</button>
                      <p className="xc-meta">cosine {h.cosine_similarity.toFixed(3)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Async>
        )}
      </section>
    </>
  )
}

function ContradictionsTab({ memoryId, scope }: { memoryId: string; scope: WorkspaceScope }) {
  const { select } = useConsole()
  const list = useAsync(() => api.contradictions(memoryId, scope), [memoryId, scope])
  return (
    <Async state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <>
          <div className="xc-callout xc-callout--review"><IconWarn /><span>{items.length} open. Contradictions are surfaced, never auto-resolved.</span></div>
          <div className="xc-rows">
            {items.map((c) => (
              <div className="xc-row" key={c.id}>
                <i className="xc-row-dot" style={{ background: 'var(--status-review)' }} />
                <div className="xc-row-main">
                  <button type="button" className="xc-link" style={{ fontSize: 13 }} onClick={() => select(`memory:${c.id}`)}>{truncate(c.content, 120)}</button>
                  <p className="xc-meta">{c.status} · {c.id}</p>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Async>
  )
}

function TelemetryTab({ memoryId, scope }: { memoryId: string; scope: WorkspaceScope }) {
  const list = useAsync(() => api.memoryOtel(memoryId, scope), [memoryId, scope])
  return (
    <Async state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <div className="xc-rows">
          {items.map((o) => (
            <div className="xc-row" key={o.id}>
              <i className="xc-row-dot" />
              <div className="xc-row-main">
                <div className="xc-row-top"><span className="xc-mono">{o.name}</span><span className="xc-meta">{o.value !== null ? `${o.value}${o.unit ? ` ${o.unit}` : ''}` : o.kind}</span></div>
                <p className="xc-meta">{stamp(o.created_at)}{o.trace_id ? ` · trace ${elideHash(o.trace_id, 6, 4)}` : ''}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Async>
  )
}

function FilesTab({ memoryId, scope }: { memoryId: string; scope: WorkspaceScope }) {
  const list = useAsync(() => api.attachments(memoryId, scope), [memoryId, scope])
  const [downloading, setDownloading] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  /** Fetch with the session credential (a plain link would not carry a bearer token) and hand the bytes to the browser. */
  const download = async (attachment: Attachment) => {
    setDownloading(attachment.id)
    setDownloadError(null)
    try {
      saveBlob(attachmentFilename(attachment), await api.attachmentFile(attachment.id, scope))
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : String(e))
    } finally {
      setDownloading(null)
    }
  }

  return (
    <Async state={list} empty={(l) => l.length === 0}>
      {(items) => (
        <div className="xc-rows">
          {items.map((a) => (
            <div className="xc-row" key={a.id}>
              <i className="xc-row-dot" style={{ background: 'var(--ink-muted)' }} />
              <div className="xc-row-main">
                <div className="xc-row-top"><span className="xc-mono">{a.media_type}</span><span className="xc-meta">{a.byte_size.toLocaleString()} B</span></div>
                <p className="xc-hash" title={a.content_hash}>{elideHash(a.content_hash)}</p>
                <div className="xc-actions-row" style={{ marginTop: 4 }}>
                  <button type="button" className="xc-btn" disabled={downloading === a.id} onClick={() => void download(a)}>{downloading === a.id ? 'Downloading…' : 'Download'}</button>
                </div>
              </div>
            </div>
          ))}
          {downloadError && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{downloadError}</div>}
        </div>
      )}
    </Async>
  )
}

// --- nothing selected: the workspace itself ---------------------------------------------------------------

/** What the inspector shows before anything is selected: the workspace, so the pane is never dead space. */
function WorkspaceSummary() {
  const { model, stats, status, sessions, select, workspace, go, setOverlay } = useConsole()
  const recent = sessions.slice(0, 4)
  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Workspace</p>
        <h3 className="xc-title">Nothing selected</h3>
        <p className="xc-note">Select a node or an edge on the graph, a mark on the timeline, or a Recall result to inspect it.</p>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">{workspace.selected ? workspace.selected.label : workspace.primary ? 'Primary profile' : 'Workspace'}{workspace.canWrite ? '' : ' · read only'}</p>
          <dl className="xc-kv">
            <div><dt>Memories</dt><dd>{stats?.memories == null ? '—' : stats.memories.toLocaleString()}</dd></div>
            <div><dt>Entities</dt><dd>{stats ? stats.entities.toLocaleString() : '—'}</dd></div>
            <div><dt>Sessions</dt><dd>{stats ? stats.sessions.toLocaleString() : '—'}</dd></div>
            <div><dt>Schema</dt><dd>{status ? `v${status.schema_version}` : '—'}</dd></div>
            <div><dt>Identity</dt><dd>{status?.identity_mode ?? '—'}</dd></div>
            <div><dt>Integrity check</dt><dd>{status?.integrity_check ?? '—'}</dd></div>
          </dl>
        </section>
        {recent.length > 0 && (
          <section>
            <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Latest sessions</p>
            <div className="xc-rows">
              {recent.map((row) => {
                const node = model?.nodes.find((n) => n.cls === 'session' && n.sessionId === row.external_session_id)
                return (
                  <div className="xc-row" key={row.id}>
                    <i className="xc-row-dot" style={{ background: 'var(--status-anchored)' }} />
                    <div className="xc-row-main">
                      {node
                        ? <button type="button" className="xc-link" onClick={() => select(node.id)}>{row.external_session_id}</button>
                        : <span style={{ fontSize: 13 }}>{row.external_session_id}</span>}
                      <p className="xc-meta">{stamp(row.started_at)} · {row.ended_at ? 'ended' : 'open'}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Go to</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <button type="button" className="xc-btn" onClick={() => setOverlay('recall')}>Recall</button>
            <button type="button" className="xc-btn" onClick={() => setOverlay('review')}>Review</button>
            <button type="button" className="xc-btn" onClick={() => setOverlay('integrity')}>Verify chains</button>
            <button type="button" className="xc-btn" onClick={() => go('sessions')}>All sessions</button>
          </div>
        </section>
      </div></div>
    </>
  )
}

// --- edge ------------------------------------------------------------------------------------------

/** What an edge of each kind means, said once, so the graph never has to explain itself in a tooltip. */
const EDGE_MEANING: Record<string, string> = {
  relation: 'A subject–predicate–object fact extracted from a memory. The arrow runs from subject to object.',
  contradiction: 'Two memories that disagree. It stays on the graph until one is superseded or the dispute is resolved.',
  similarity: 'Two memories whose embeddings are close. The server computes the score; the slider only sets the cut-off.',
  contains: 'The session this exchange belongs to.',
  prompt: 'The memory written from the prompt of this exchange.',
  response: 'The memory written from the response of this exchange.',
  context: 'Context the exchange drew on.',
  merkle_root: 'The Merkle root the session committed to.',
}

function EdgeInspector({ edge }: { edge: CEdge }) {
  const { model, select, reveal } = useConsole()
  const end = (id: string) => model?.byId.get(id)
  const row = (label: string, id: string) => {
    const n = end(id)
    return (
      <div><dt>{label}</dt><dd>{n ? <button type="button" className="xc-link" onClick={() => (id.startsWith('memory:') ? reveal(id) : select(id))}>{n.label}</button> : id}</dd></div>
    )
  }
  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected edge</p>
        <h3 className="xc-title">{EDGE_TYPE_LABEL[edge.type] ?? edge.type}{edge.predicate ? ` · ${edge.predicate}` : ''}</h3>
        <p className="xc-meta" style={{ wordBreak: 'break-all' }}>{edge.id}</p>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Ends</p>
          <dl className="xc-kv">
            {row(edge.type === 'relation' ? 'Subject' : 'From', edge.source)}
            {row(edge.type === 'relation' ? 'Object' : 'To', edge.target)}
            {edge.predicate && <div><dt>Predicate</dt><dd>{edge.predicate}</dd></div>}
            {edge.similarity !== undefined && <div><dt>Similarity</dt><dd>{edge.similarity.toFixed(3)}</dd></div>}
            {edge.reason && <div><dt>Reason</dt><dd>{edge.reason}</dd></div>}
            {edge.evidenceMemoryId && (
              <div><dt>Evidence</dt><dd><button type="button" className="xc-link" onClick={() => reveal(`memory:${edge.evidenceMemoryId}`)}>{edge.evidenceMemoryId.slice(0, 8)}…</button></dd></div>
            )}
          </dl>
        </section>
        <p className="xc-note">{EDGE_MEANING[edge.type] ?? 'An edge in the projected graph.'}</p>
      </div></div>
    </>
  )
}

// --- entity ----------------------------------------------------------------------------------------

function exchangeTimes(model: GraphModel | null, sessionNodeId: string): number[] {
  if (!model) return []
  return model.edges
    .filter((e) => e.type === 'contains' && e.source === sessionNodeId)
    .map((e) => model.byId.get(e.target)?.time)
    .filter((t): t is number => typeof t === 'number')
}

function edgesOf(edges: CEdge[], id: string): CEdge[] {
  return edges.filter((e) => e.source === id || e.target === id)
}

function EntityInspector({ node }: { node: CNode }) {
  const { model, select, reveal } = useConsole()
  const relations = model ? edgesOf(model.edges, node.id).filter((e) => e.type === 'relation') : []
  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected entity</p>
        <h3 className="xc-title">{node.label}</h3>
        <p className="xc-meta" style={{ wordBreak: 'break-all' }}>{node.id}</p>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Relations</p>
          {relations.length === 0 ? <p className="xc-note">No relations in this sample.</p> : (
            <div className="xc-rows">
              {relations.map((e) => {
                const outgoing = e.source === node.id
                const other = model!.byId.get(outgoing ? e.target : e.source)
                return (
                  <div className="xc-row" key={e.id}>
                    <i className="xc-row-dot" style={{ background: 'var(--ink-muted)' }} />
                    <div className="xc-row-main">
                      <span style={{ fontSize: 13 }}>
                        <span className="xc-meta">{outgoing ? `— ${e.predicate} →` : `← ${e.predicate} —`}</span>{' '}
                        {other ? <button type="button" className="xc-link" onClick={() => select(other.id)}>{other.label}</button> : '—'}
                      </span>
                      {e.evidenceMemoryId && (
                        <p className="xc-meta">evidence <button type="button" className="xc-link xc-meta" onClick={() => reveal(`memory:${e.evidenceMemoryId}`)}>{e.evidenceMemoryId.slice(0, 8)}…</button></p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>
        <p className="xc-note">{node.time === null ? 'No timestamp: none of this entity’s evidence is placed in time.' : `Placed at ${shortStamp(node.time)} by its earliest evidence memory.`}</p>
      </div></div>
    </>
  )
}

// --- session ---------------------------------------------------------------------------------------

function SessionInspector({ node }: { node: CNode }) {
  const { model, sessions, workspace, select, setWindow } = useConsole()
  const row = sessions.find((s) => s.external_session_id === node.sessionId)
  const root = useAsync(() => (node.sessionId ? api.sessionMerkleRoot(node.sessionId, workspace.scope) : Promise.resolve(null)), [node.sessionId, workspace.scope])
  // span of this session in time, padded so its first and last marks are not on the border
  const startMs = parseServerTime(row?.started_at) ?? node.time
  const endMs = parseServerTime(row?.ended_at) ?? null
  const sessionSpan = startMs === null ? null : (() => {
    const last = Math.max(startMs, endMs ?? 0, ...exchangeTimes(model, node.id))
    const pad = Math.max(60_000, (last - startMs) * 0.05)
    return { from: startMs - pad, to: last + pad }
  })()
  const exchanges = model ? edgesOf(model.edges, node.id).filter((e) => e.type === 'contains').map((e) => model.byId.get(e.target)).filter((n): n is CNode => !!n) : []

  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected session</p>
        <h3 className="xc-title">{node.sessionId}</h3>
        <p className="xc-meta">{row ? `${row.retention_tier} retention` : '—'}</p>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        <dl className="xc-kv">
          <div><dt>Started</dt><dd>{row ? stamp(row.started_at) : node.time ? shortStamp(node.time) : '—'}</dd></div>
          <div><dt>Ended</dt><dd>{row ? (row.ended_at ? stamp(row.ended_at) : 'open') : '—'}</dd></div>
          <div><dt>Exchanges</dt><dd>{exchanges.length}</dd></div>
        </dl>
        {sessionSpan && (
          <div>
            <button type="button" className="xc-btn" onClick={() => setWindow(sessionSpan, 'custom')}>Window both lenses to this session</button>
          </div>
        )}
        <Async state={root}>
          {(r) => r === null ? null : (
            <div className={`xc-callout ${r.valid ? 'xc-callout--anchored' : 'xc-callout--conflict'}`}>
              {r.valid ? <IconCheck /> : <IconWarn />}
              <div style={{ minWidth: 0 }}>
                <b>{r.valid ? 'Server reports this root valid' : 'Server reports this root INVALID'}</b>
                <div className="xc-hash xc-hash--anchored" title={r.root_node_id ?? undefined}>{r.root_node_id ? elideHash(r.root_node_id) : 'no root yet'}</div>
                <div className="xc-note" style={{ marginTop: 4 }}>{r.root_kind}. Computed by the server.</div>
              </div>
            </div>
          )}
        </Async>
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Exchanges</p>
          {exchanges.length === 0 ? <p className="xc-note">None in this sample.</p> : (
            <div className="xc-rows">
              {[...exchanges].sort((a, b) => (a.time ?? 0) - (b.time ?? 0)).map((x) => (
                <div className="xc-row" key={x.id}>
                  <i className="xc-row-dot" style={{ background: 'var(--ink-muted)' }} />
                  <div className="xc-row-main"><button type="button" className="xc-link" onClick={() => select(x.id)}>{x.label}</button><p className="xc-meta">{x.time ? shortStamp(x.time) : 'untimed'}</p></div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div></div>
    </>
  )
}

// --- exchange --------------------------------------------------------------------------------------

function ExchangeInspector({ node }: { node: CNode }) {
  const { model, reveal, select } = useConsole()
  const edges = model ? edgesOf(model.edges, node.id) : []
  const group = (type: string) => edges.filter((e) => e.type === type && e.source === node.id).map((e) => model!.byId.get(e.target)).filter((n): n is CNode => !!n)
  const session = edges.find((e) => e.type === 'contains')
  const sessionNode = session ? model?.byId.get(session.source) : undefined
  const sections: Array<[string, CNode[]]> = [['Prompt', group('prompt')], ['Response', group('response')], ['Context', group('context')]]
  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected exchange</p>
        <h3 className="xc-title">{node.label}</h3>
        <p className="xc-meta">{node.time ? shortStamp(node.time) : 'untimed'}{sessionNode ? <> · session <button type="button" className="xc-link xc-meta" onClick={() => select(sessionNode.id)}>{sessionNode.sessionId}</button></> : null}</p>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        {sections.map(([title, items]) => (
          <section key={title}>
            <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">{title}</p>
            {items.length === 0 ? <p className="xc-note">None.</p> : (
              <div className="xc-rows">
                {items.map((m) => (
                  <div className="xc-row" key={m.id}>
                    <i className="xc-row-dot" />
                    <div className="xc-row-main"><button type="button" className="xc-link" style={{ fontSize: 13 }} onClick={() => reveal(m.id)}>{truncate(m.label, 100)}</button>{m.status && <p className="xc-meta">{m.status}</p>}</div>
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}
      </div></div>
    </>
  )
}

// --- merkle root -----------------------------------------------------------------------------------

function MerkleInspector({ node }: { node: CNode }) {
  const { model, select } = useConsole()
  const hash = node.id.replace(/^merkle:/, '')
  const link = model?.edges.find((e) => e.type === 'merkle_root' && e.target === node.id)
  const session = link ? model?.byId.get(link.source) : undefined
  return (
    <>
      <div className="xc-inspector-head">
        <p className="xc-eyebrow">Selected Merkle root</p>
        <h3 className="xc-title">{session?.sessionId ?? 'Session root'}</h3>
      </div>
      <div className="xc-scroll"><div className="xc-inspector-body">
        <div className={`xc-callout ${node.valid === false ? 'xc-callout--conflict' : 'xc-callout--anchored'}`}>
          {node.valid === false ? <IconWarn /> : <IconCheck />}
          <div><b>Server reports this root {node.valid === false ? 'INVALID' : 'valid'}</b><div className="xc-note" style={{ marginTop: 4 }}>Computed by the server from the session’s exchange chain; not recomputed here.</div></div>
        </div>
        <section>
          <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">Root</p>
          <p className="xc-hash xc-hash--anchored" style={{ userSelect: 'all' }}>{hash}</p>
        </section>
        {session && <p className="xc-copy">Session <button type="button" className="xc-link" onClick={() => select(session.id)}>{session.sessionId}</button></p>}
      </div></div>
    </>
  )
}
