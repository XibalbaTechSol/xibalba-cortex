// Write actions for one memory: supersede, link entities, mark a contradiction, forget.
//
// Only offered in a verified, writable {store, agent} workspace (`workspace.canWrite`); anywhere
// else the footer says why there are no buttons rather than showing dead ones. Every action goes
// through the same store methods the legacy viewer used, and the server re-checks scope. Nothing
// here is optimistic: the UI changes only after the server confirms, then the graph is reloaded.
//
// Forget is two steps (describe, then confirm). Contradictions are recorded, never resolved: the
// console does not pick a winner.

import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { api, type Memory } from '../api'
import { useConsole } from './state'
import {
  SUPERSEDE_STATUSES,
  buildContradiction,
  buildLink,
  buildSupersede,
  canForget,
  canSupersede,
  type Built,
  type SupersedeStatus,
} from './actions'
import { elideHash } from './model'
import { IconWarn } from './icons'

type Mode = 'supersede' | 'link' | 'contradiction' | 'forget'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="xc-field"><span>{label}</span>{children}</label>
}

export function MemoryActions({ memory }: { memory: Memory }) {
  const { workspace, model, reload, select, setNotice } = useConsole()
  const [mode, setMode] = useState<Mode | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const formId = useId()

  // supersede
  const [content, setContent] = useState(memory.content)
  const [status, setStatus] = useState<SupersedeStatus>('confirmed')
  // link
  const [subject, setSubject] = useState('')
  const [predicate, setPredicate] = useState('')
  const [object, setObject] = useState('')
  const [confidence, setConfidence] = useState('')
  // contradiction
  const [otherId, setOtherId] = useState('')
  const [reason, setReason] = useState('')

  if (!workspace.canWrite) {
    return (
      <div className="xc-inspector-foot">
        <p className="xc-note">
          Read-only workspace. {workspace.selected ? 'This agent’s store is mounted read-only.' : 'The primary profile has no writable agent namespace selected.'} Writes are available in a writable agent workspace.
        </p>
      </div>
    )
  }

  const open = (next: Mode) => {
    setMode((current) => (current === next ? null : next))
    setError(null)
    setNotice(null)
  }

  const run = async <T,>(built: Built<T>, call: (payload: T) => Promise<string | void>) => {
    if (!built.ok) { setError(built.error); return }
    setBusy(true)
    setError(null)
    try {
      const message = await call(built.payload)
      if (message) setNotice(message)
      setMode(null)
      reload()
    } catch (e) {
      // the server's own words (scope, status, governance) are the useful ones
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const submitSupersede = (event: FormEvent) => {
    event.preventDefault()
    const built = buildSupersede(memory.id, memory.content, { content, status })
    return run(built, async (payload) => {
      const next = await api.supersedeMemory(memory.id, payload)
      select(`memory:${next.id}`)
      return `Superseded ${memory.id.slice(0, 8)}…. The replacement is ${next.id.slice(0, 8)}… and the old memory keeps its chain.`
    })
  }

  const submitLink = (event: FormEvent) => {
    event.preventDefault()
    const built = buildLink(memory.id, { subject, predicate, object, confidence })
    return run(built, async (payload) => {
      await api.linkEntities(payload)
      return `Linked ${subject.trim()} — ${predicate.trim()} → ${object.trim()}, evidenced by this memory.`
    })
  }

  const submitContradiction = (event: FormEvent) => {
    event.preventDefault()
    const built = buildContradiction(memory.id, { otherId, reason })
    return run(built, async (payload) => {
      await api.markContradiction(payload)
      return 'Contradiction recorded on both memories. Neither was changed or ranked.'
    })
  }

  const confirmForget = () =>
    run({ ok: true, payload: null }, async () => {
      const done = await api.forgetMemory(memory.id)
      const receipt = done.deletion_receipt as { receipt_hash?: string } | undefined
      return `Forgotten. Chain events and the content hash are retained; deletion receipt ${receipt?.receipt_hash ? elideHash(receipt.receipt_hash) : 'issued'}.`
    })

  // candidates for the contradiction picker: other memories currently in the graph sample
  const others = model ? model.nodes.filter((n) => n.cls === 'memory' && n.id !== `memory:${memory.id}`) : []

  return (
    <div className="xc-inspector-foot">
      {mode && (
        <form
          className="xc-form"
          aria-labelledby={`${formId}-title`}
          onSubmit={mode === 'supersede' ? submitSupersede : mode === 'link' ? submitLink : mode === 'contradiction' ? submitContradiction : (e) => { e.preventDefault(); confirmForget() }}
        >
          {mode === 'supersede' && (
            <>
              <p className="xc-eyebrow" id={`${formId}-title`}>Supersede memory</p>
              <p className="xc-note">Writes a replacement and marks this one superseded. The old text and its chain stay on record.</p>
              <Field label="Replacement text">
                <textarea className="xc-input" rows={5} value={content} onChange={(e) => setContent(e.target.value)} autoFocus />
              </Field>
              <Field label="Replacement status">
                <select className="xc-input" value={status} onChange={(e) => setStatus(e.target.value as SupersedeStatus)}>
                  {SUPERSEDE_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
            </>
          )}
          {mode === 'link' && (
            <>
              <p className="xc-eyebrow" id={`${formId}-title`}>Link entities</p>
              <p className="xc-note">Records a relation that this memory is the evidence for.</p>
              <Field label="Subject"><input className="xc-input" value={subject} onChange={(e) => setSubject(e.target.value)} autoFocus /></Field>
              <Field label="Relation"><input className="xc-input" value={predicate} onChange={(e) => setPredicate(e.target.value)} placeholder="computes, depends_on…" /></Field>
              <Field label="Object"><input className="xc-input" value={object} onChange={(e) => setObject(e.target.value)} /></Field>
              <Field label="Confidence (0 to 1, blank = 1)"><input className="xc-input xc-input--mono" inputMode="decimal" value={confidence} onChange={(e) => setConfidence(e.target.value)} /></Field>
            </>
          )}
          {mode === 'contradiction' && (
            <>
              <p className="xc-eyebrow" id={`${formId}-title`}>Mark contradiction</p>
              <p className="xc-note">Records that two memories conflict. It does not choose between them.</p>
              <Field label="Conflicting memory id">
                <input className="xc-input xc-input--mono" list={`${formId}-others`} value={otherId} onChange={(e) => setOtherId(e.target.value)} placeholder="paste an id, or pick one in the graph" autoFocus />
                <datalist id={`${formId}-others`}>
                  {others.slice(0, 80).map((n) => <option key={n.id} value={n.id.replace(/^memory:/, '')}>{n.label.slice(0, 70)}</option>)}
                </datalist>
              </Field>
              <Field label="Why they conflict"><input className="xc-input" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            </>
          )}
          {mode === 'forget' && (
            <>
              <p className="xc-eyebrow" id={`${formId}-title`}>Forget memory</p>
              <div className="xc-callout xc-callout--conflict">
                <IconWarn />
                <span>Marks this memory forgotten and issues a deletion receipt. Its chain events and content hash are kept so the chain still verifies. This cannot be undone from the console.</span>
              </div>
            </>
          )}
          {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
          <div className="xc-actions-row">
            <button type="button" className="xc-btn" onClick={() => setMode(null)} disabled={busy}>Cancel</button>
            <button type="submit" className={mode === 'forget' ? 'xc-btn xc-btn--danger' : 'xc-btn xc-btn--primary'} disabled={busy}>
              {busy ? 'Working…' : mode === 'forget' ? 'Forget this memory' : mode === 'supersede' ? 'Supersede' : mode === 'link' ? 'Link entities' : 'Record contradiction'}
            </button>
          </div>
        </form>
      )}
      {!mode && (
        <div className="xc-actions-row" role="group" aria-label="Memory actions">
          <button type="button" className="xc-btn" disabled={!canSupersede(memory.status)} onClick={() => open('supersede')} title={canSupersede(memory.status) ? undefined : `A ${memory.status} memory cannot be superseded`}>Supersede</button>
          <button type="button" className="xc-btn" onClick={() => open('link')}>Link entities</button>
          <button type="button" className="xc-btn" onClick={() => open('contradiction')}>Contradiction</button>
          <button type="button" className="xc-btn xc-btn--danger-quiet" disabled={!canForget(memory.status)} onClick={() => open('forget')}>Forget</button>
        </div>
      )}
    </div>
  )
}
