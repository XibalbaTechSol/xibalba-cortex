// Review drawer: the human gate in front of everything the extraction workers propose.
//
// Extraction is proposal-only by design. Nothing here is written to the graph until a person
// accepts it, and accepting is a two-step action that first says what it will do. Decisions are
// offered only in a writable workspace. The inference-task tab is read-only: workers claim and
// complete tasks, and the console does not fabricate task output on their behalf.

import { useCallback, useId, useRef, useState } from 'react'
import { api, type ExtractionProposal, type InferenceTask, type ParaClassification } from '../api'
import { useConsole } from './state'
import { useAsync } from './useAsync'
import { useDialog } from './useDialog'
import { TASK_STATUSES, loadReviewQueue, loadTasks, type ReviewQueue, type TaskStatus } from './reviewData'
import { PARA_LABEL, PARA_MEANING, describeProposal, percent } from './review'
import { elideHash, parseServerTime, shortStamp } from './model'
import { IconClose, IconWarn } from './icons'

type Tab = 'proposals' | 'para' | 'tasks'

const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? (value ?? '—') : shortStamp(ms)
}

export function Review() {
  const { workspace, setOverlay, reload } = useConsole()
  const scope = workspace.scope
  const [tab, setTab] = useState<Tab>('proposals')
  const [bump, setBump] = useState(0)
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const close = () => setOverlay(null)
  useDialog(dialogRef, close, closeRef)

  // keepData: a decision re-reads the queue, and the list should not blank out while it does
  const queue = useAsync(() => loadReviewQueue(scope), [scope, bump], { keepData: true })

  // after a decision the whole queue is re-read, and the graph too, because accepting writes records
  const decided = useCallback(() => {
    setBump((n) => n + 1)
    reload()
  }, [reload])

  const q = queue.data
  const counts = { proposals: q?.proposals.length, para: q?.para.length }

  return (
    <>
      <div className="xc-scrim" onClick={close} aria-hidden="true" />
      <aside ref={dialogRef} className="xc-win xc-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="xc-drawer-head">
          <div>
            <p className="xc-eyebrow">Review</p>
            <h2 className="xc-title" id={titleId}>What the workers proposed</h2>
          </div>
          <button ref={closeRef} type="button" className="xc-btn xc-btn--square" onClick={close} aria-label="Close Review"><IconClose /></button>
        </div>

        {!workspace.canWrite && (
          <p className="xc-note xc-drawer-note">Read-only workspace: you can inspect the queue but not decide on it.</p>
        )}

        <div className="xc-tabs" role="tablist" aria-label="Review sections">
          {([['proposals', 'Proposals', counts.proposals], ['para', 'PARA', counts.para], ['tasks', 'Tasks', undefined]] as const).map(([id, label, n]) => (
            <button key={id} type="button" role="tab" id={`rv-${id}`} className="xc-tab" aria-selected={tab === id} aria-controls="rv-panel" onClick={() => setTab(id)}>
              {label}{n !== undefined && <b>{n}</b>}
            </button>
          ))}
        </div>

        <div className="xc-scroll" role="tabpanel" id="rv-panel" aria-labelledby={`rv-${tab}`}>
          <div className="xc-drawer-body">
            {queue.loading && !q && <p className="xc-note" role="status">Loading…</p>}
            {queue.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{queue.error}</div>}
            {q && tab === 'proposals' && <ProposalList queue={q} canDecide={workspace.canWrite} onDecided={decided} />}
            {q && tab === 'para' && <ParaList queue={q} canDecide={workspace.canWrite} onDecided={decided} />}
            {tab === 'tasks' && <TaskList />}
          </div>
        </div>
      </aside>
    </>
  )
}

function Hidden({ count, complete }: { count: number; complete: boolean }) {
  if (count === 0) return null
  const many = count === 1 ? 'is' : 'are'
  return (
    <p className="xc-note">
      {count} item{count === 1 ? '' : 's'} in this store {many} not matched to this workspace and not shown
      {complete ? ' (they belong to other agent workspaces).' : '. Only this workspace’s newest memories are checked, so some of these may belong here.'}
    </p>
  )
}

function SourceLink({ memoryId }: { memoryId: string }) {
  const { reveal, setOverlay } = useConsole()
  return (
    <button type="button" className="xc-link xc-meta" onClick={() => { reveal(`memory:${memoryId}`); setOverlay(null) }} title={memoryId}>
      source {elideHash(memoryId, 8, 4)}
    </button>
  )
}

// --- extraction proposals ----------------------------------------------------------------------------

function ProposalList({ queue, canDecide, onDecided }: { queue: ReviewQueue; canDecide: boolean; onDecided: () => void }) {
  return (
    <>
      <Hidden count={queue.hiddenProposals} complete={queue.indexComplete} />
      {queue.proposals.length === 0 ? (
        <div className="xc-empty"><h3 className="xc-title">Nothing waiting</h3><p>No extraction proposals need a decision in this workspace.</p></div>
      ) : (
        <ul className="xc-cards">{queue.proposals.map((p) => <ProposalCard key={p.id} proposal={p} canDecide={canDecide} onDecided={onDecided} />)}</ul>
      )}
    </>
  )
}

function ProposalCard({ proposal, canDecide, onDecided }: { proposal: ExtractionProposal; canDecide: boolean; onDecided: () => void }) {
  const view = describeProposal(proposal)
  const [confirming, setConfirming] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const decide = async (decision: 'accept' | 'dismiss') => {
    setBusy(true)
    setError(null)
    try {
      await api.decideExtractionProposal(proposal.id, decision, undefined, note.trim() || undefined)
      onDecided()
    } catch (e) {
      // e.g. "stale because the source memory changed" -- the server's words are the useful ones
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <li className="xc-card">
      <div className="xc-card-top">
        <b className="xc-card-title">{view.title}</b>
        <span className="xc-meta">{stamp(proposal.created_at)}</span>
      </div>
      <div className="xc-card-facts">{view.facts.map((f) => <span key={f} className="xc-tag"><i />{f}</span>)}</div>
      {proposal.evidence_quote && <blockquote className="xc-quote">“{proposal.evidence_quote}”</blockquote>}
      <SourceLink memoryId={proposal.source_memory_id} />
      {confirming && <p className="xc-note xc-effect">{view.effect}</p>}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {canDecide && (
        <div className="xc-actions-row">
          {confirming ? (
            <>
              <input className="xc-input" aria-label="Decision note (optional)" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="button" className="xc-btn" disabled={busy} onClick={() => setConfirming(false)}>Back</button>
              <button type="button" className="xc-btn xc-btn--primary" disabled={busy} onClick={() => decide('accept')}>{busy ? 'Working…' : 'Confirm accept'}</button>
            </>
          ) : (
            <>
              <button type="button" className="xc-btn xc-btn--primary" disabled={busy} onClick={() => setConfirming(true)}>Accept…</button>
              <button type="button" className="xc-btn" disabled={busy} onClick={() => decide('dismiss')}>Dismiss</button>
            </>
          )}
        </div>
      )}
    </li>
  )
}

// --- PARA -------------------------------------------------------------------------------------------

function ParaList({ queue, canDecide, onDecided }: { queue: ReviewQueue; canDecide: boolean; onDecided: () => void }) {
  return (
    <>
      <Hidden count={queue.hiddenPara} complete={queue.indexComplete} />
      {queue.para.length === 0 ? (
        <div className="xc-empty"><h3 className="xc-title">Nothing waiting</h3><p>No PARA classifications need a decision in this workspace.</p></div>
      ) : (
        <ul className="xc-cards">{queue.para.map((c) => <ParaCard key={c.task_id} item={c} canDecide={canDecide} onDecided={onDecided} />)}</ul>
      )}
    </>
  )
}

function ParaCard({ item, canDecide, onDecided }: { item: ParaClassification; canDecide: boolean; onDecided: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const decide = async (decision: 'accept' | 'dismiss' | 'keep_original') => {
    setBusy(true)
    setError(null)
    try {
      await api.decidePara(item.task_id, decision)
      onDecided()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }
  return (
    <li className="xc-card">
      <div className="xc-card-top">
        <b className="xc-card-title">{PARA_LABEL[item.category]} <span className="xc-meta">· {PARA_MEANING[item.category]}</span></b>
        <span className="xc-meta">{percent(item.confidence)}</span>
      </div>
      <p className="xc-copy">{item.rationale}</p>
      <div className="xc-card-facts">
        {item.signals.map((s) => <span key={s} className="xc-tag"><i />{s}</span>)}
        {item.alternatives.length > 0 && <span className="xc-meta">also considered: {item.alternatives.join(', ')}</span>}
      </div>
      <SourceLink memoryId={item.memory_id} />
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {canDecide && (
        <div className="xc-actions-row">
          <button type="button" className="xc-btn xc-btn--primary" disabled={busy} onClick={() => decide('accept')} title="Records this category as the reviewed classification. The memory is not edited.">Accept</button>
          <button type="button" className="xc-btn" disabled={busy} onClick={() => decide('keep_original')}>Keep original</button>
          <button type="button" className="xc-btn" disabled={busy} onClick={() => decide('dismiss')}>Dismiss</button>
        </div>
      )}
    </li>
  )
}

// --- inference tasks (read-only) ----------------------------------------------------------------------

function TaskList() {
  const { workspace, reveal, setOverlay } = useConsole()
  const [status, setStatus] = useState<TaskStatus>('pending')
  const tasks = useAsync(() => loadTasks(status, workspace.scope), [status, workspace.scope])

  return (
    <>
      <div className="xc-ranges" role="group" aria-label="Task status">
        {TASK_STATUSES.map((s) => <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)}>{s}</button>)}
      </div>
      <p className="xc-note">Workers claim and complete these. The console only shows them; it does not write task output.</p>
      {tasks.loading && <p className="xc-note" role="status">Loading…</p>}
      {tasks.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{tasks.error}</div>}
      {tasks.data && tasks.data.length === 0 && <p className="xc-note">No {status} tasks.</p>}
      <ul className="xc-cards">
        {(tasks.data ?? []).map((t: InferenceTask) => (
          <li className="xc-card" key={t.id}>
            <div className="xc-card-top">
              <b className="xc-card-title">{t.task_type}</b>
              <span className="xc-meta">{stamp(t.updated_at)}</span>
            </div>
            <div className="xc-card-facts">
              <span className="xc-tag"><i />{t.status}</span>
              <span className="xc-meta">attempt {t.attempt_count}</span>
              {t.claim_owner && <span className="xc-meta">claimed by {t.claim_owner}</span>}
            </div>
            {(t.error || t.dead_letter_reason) && <p className="xc-note" style={{ color: 'var(--status-conflict)' }}>{t.failure_class ? `${t.failure_class}: ` : ''}{t.dead_letter_reason ?? t.error}</p>}
            {t.subject_type === 'memory' && (
              <button type="button" className="xc-link xc-meta" onClick={() => { reveal(`memory:${t.subject_id}`); setOverlay(null) }}>subject {elideHash(t.subject_id, 8, 4)}</button>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}
