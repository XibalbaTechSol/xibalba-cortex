// Memories: browse, search and filter every memory in the workspace, and add one. The graph and
// timeline show a sample; this is the complete, paged listing, with the same inspector beside it.
//
// Search is the store's full-text index (not semantic); Recall is where hybrid retrieval lives.
// Adding is offered only in a writable workspace and writes into the selected agent workspace.

import { useState, type FormEvent } from 'react'
import { api } from '../../api'
import { useConsole } from '../state'
import { useAsync } from '../useAsync'
import { Inspector } from '../Inspector'
import { elideHash, parseServerTime, shortStamp } from '../model'
import { NEW_MEMORY_CLASSES, NEW_MEMORY_STATUSES, buildNewMemory, type NewMemoryClass, type NewMemoryStatus } from '../actions'
import { IconSearch, IconWarn } from '../icons'
import { Page } from './Page'

const PAGE_SIZE = 40
const ALL_STATUSES = ['active', 'confirmed', 'candidate', 'disputed', 'quarantined', 'superseded', 'forgotten'] as const
const DEFAULT_STATUSES: readonly string[] = ['active', 'confirmed']

const truncate = (value: string, max: number): string => (value.length > max ? `${value.slice(0, max - 1)}…` : value)
const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? '—' : shortStamp(ms)
}

export function MemoriesPage() {
  const { workspace, selectedId, select, reload, revision, setNotice } = useConsole()
  const scope = workspace.scope
  const [statuses, setStatuses] = useState<string[]>([...DEFAULT_STATUSES])
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [adding, setAdding] = useState(false)

  const list = useAsync(
    () => api.memories({ limit: PAGE_SIZE, offset, statuses, agentId: scope.agentId, storeId: scope.storeId, query }),
    [scope, statuses, query, offset, revision],
    { keepData: true },
  )
  const rows = list.data?.memories ?? []

  const toggleStatus = (status: string) => {
    setOffset(0)
    setStatuses((prev) => {
      const next = prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status]
      return next.length === 0 ? prev : next // at least one: an empty filter would silently mean "the defaults"
    })
  }
  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    setOffset(0)
    setQuery(draft.trim())
  }

  return (
    <Page
      eyebrow="Explore"
      title="Memories"
      note="Every memory in this workspace, newest first. Search uses the store’s full-text index; use Recall for semantic and graph retrieval."
      actions={workspace.canWrite && <button type="button" className="xc-btn xc-btn--primary" onClick={() => setAdding((v) => !v)} aria-expanded={adding}>New memory</button>}
    >
      {adding && workspace.canWrite && (
        <NewMemory
          agentId={workspace.selected?.agentId}
          onDone={(id) => {
            setAdding(false)
            setNotice(`Memory ${id.slice(0, 8)}… added to ${workspace.selected ? 'this workspace' : 'the primary profile'}.`)
            reload()
            select(`memory:${id}`)
          }}
          onCancel={() => setAdding(false)}
        />
      )}

      <div className="xc-memories">
        <section className="xc-win xc-pane xc-memories-list" aria-label="Memory list">
          <form className="xc-memories-filters" onSubmit={submitSearch} role="search">
            <div className="xc-memories-search">
              <IconSearch />
              <input className="xc-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Search memory text…" aria-label="Search memory text" />
              <button type="submit" className="xc-btn">Search</button>
              {query && <button type="button" className="xc-btn" onClick={() => { setDraft(''); setQuery(''); setOffset(0) }}>Clear</button>}
            </div>
            <div className="xc-chips" role="group" aria-label="Status filter">
              {ALL_STATUSES.map((s) => (
                <button key={s} type="button" className="xc-chip" aria-pressed={statuses.includes(s)} onClick={() => toggleStatus(s)}>{s}</button>
              ))}
            </div>
          </form>

          {list.error && <div className="xc-callout xc-callout--conflict" role="alert" style={{ margin: 16 }}><IconWarn />{list.error}</div>}
          <div className="xc-scroll">
            <table className="xc-table xc-memories-table">
              <thead>
                <tr><th>Recorded</th><th>Status</th><th>Memory</th><th>Source</th><th>Evidence</th></tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.id} data-selected={selectedId === `memory:${m.id}`} onClick={() => select(`memory:${m.id}`)}>
                    <td className="xc-mono">{stamp(m.created_at)}</td>
                    <td><span className="xc-tag"><i />{m.status}</span></td>
                    <td>
                      <button type="button" className="xc-link xc-memories-open" aria-pressed={selectedId === `memory:${m.id}`} onClick={(e) => { e.stopPropagation(); select(`memory:${m.id}`) }}>
                        {truncate(m.content, 140)}
                      </button>
                      <span className="xc-meta xc-hash" title={m.content_hash}>{elideHash(m.content_hash)}</span>
                    </td>
                    <td>{m.source.kind.replace(/_/g, ' ')}</td>
                    <td>{m.evidence_class.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.loading && rows.length === 0 && <p className="xc-note" role="status" style={{ padding: 20 }}>Loading…</p>}
            {!list.loading && !list.error && rows.length === 0 && (
              <div className="xc-empty"><h3 className="xc-title">No memories match</h3><p>{query ? 'Nothing in this workspace matches that text with these statuses.' : 'This workspace has no memories with these statuses.'}</p></div>
            )}
          </div>

          <div className="xc-pager">
            <span className="xc-note" aria-live="polite">{rows.length > 0 ? `${offset + 1}–${offset + rows.length}` : '0'}{list.data?.has_more ? ' · more available' : ''}</span>
            <span className="xc-spacer" />
            <button type="button" className="xc-btn" disabled={offset === 0 || list.loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
            <button type="button" className="xc-btn" disabled={!list.data?.has_more || list.loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
          </div>
        </section>

        <div className="xc-memories-detail"><Inspector /></div>
      </div>
    </Page>
  )
}

function NewMemory({ agentId, onDone, onCancel }: { agentId: string | undefined; onDone: (id: string) => void; onCancel: () => void }) {
  const [content, setContent] = useState('')
  const [status, setStatus] = useState<NewMemoryStatus>('candidate')
  const [evidenceClass, setEvidenceClass] = useState<NewMemoryClass>('declared_intent')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const built = buildNewMemory({ content, status, evidenceClass }, agentId)
    if (!built.ok) { setError(built.error); return }
    setBusy(true)
    setError(null)
    try {
      const created = await api.createProposition(built.payload)
      onDone(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <form className="xc-win xc-newmemory" onSubmit={submit} aria-label="New memory">
      <p className="xc-eyebrow">New memory</p>
      <label className="xc-field">Text
        <textarea className="xc-input" rows={4} value={content} onChange={(e) => setContent(e.target.value)} autoFocus />
      </label>
      <div className="xc-newmemory-row">
        <label className="xc-field">Status
          <select className="xc-input" value={status} onChange={(e) => setStatus(e.target.value as NewMemoryStatus)}>
            {NEW_MEMORY_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="xc-field">Evidence class
          <select className="xc-input" value={evidenceClass} onChange={(e) => setEvidenceClass(e.target.value as NewMemoryClass)}>
            {NEW_MEMORY_CLASSES.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
          </select>
        </label>
      </div>
      <p className="xc-note">Recorded as a direct user statement from the console{agentId ? ', in the selected agent workspace' : ', in the primary profile'}. The store screens it like any other write.</p>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      <div className="xc-actions-row">
        <button type="button" className="xc-btn" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add memory'}</button>
      </div>
    </form>
  )
}
