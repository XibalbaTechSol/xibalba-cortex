// Settings → Inference: how the background worker turns memories into extraction proposals.
//
// GET/POST /api/settings/inference. The POST merges the body over config.yaml's `inference` block
// and re-validates the whole config before replacing the file, so a refused save changes nothing.
// The daemon picks the new policy up on its next cycle, not instantly; the server's own message
// says so and is shown verbatim. `provider` is fixed at native_harness: it is the only value the
// server accepts, so the form does not pretend there is a choice.

import { useEffect, useState } from 'react'
import { api, type InferenceSettings } from '../../../api'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'
import { PROMOTION_POLICIES, TASK_TYPES, THRESHOLD_TASKS, isDirty, toDraft, validateDraft, type InferenceDraft } from '../../inferenceForm'

const label = (task: string) => task.replace(/_/g, ' ')

export function InferenceSection() {
  const [rev, setRev] = useState(0)
  const saved = useAsync(() => api.inferenceSettings(), [rev])
  const [draft, setDraft] = useState<InferenceDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ tone: 'anchored' | 'conflict'; text: string } | null>(null)
  // set only after Save is pressed, so a half-typed field is not flagged before the user is done
  const [showErrors, setShowErrors] = useState(false)

  // a fresh server copy resets the draft: first load, and after a successful save
  useEffect(() => {
    if (saved.data) setDraft(toDraft(saved.data))
  }, [saved.data])

  if (saved.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{saved.error}</div>
  if (!draft || !saved.data) return <p className="xc-note" role="status">Loading…</p>

  const server: InferenceSettings = saved.data
  const { errors, payload } = validateDraft(draft, server.provider)
  const dirty = isDirty(draft, server)
  const set = <K extends keyof InferenceDraft>(key: K, value: InferenceDraft[K]) => {
    setDraft({ ...draft, [key]: value })
    setMessage(null)
  }
  const err = (key: string) => (showErrors ? errors[key] : undefined)

  const save = async () => {
    setShowErrors(true)
    if (!payload) return
    setBusy(true)
    setMessage(null)
    try {
      const result = await api.updateInferenceSettings(payload)
      setMessage({ tone: 'anchored', text: result.message })
      setShowErrors(false)
      setRev((n) => n + 1)
    } catch (e) {
      // the server's refusal is the authority: shown as given, and nothing was written
      setMessage({ tone: 'conflict', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const number = (key: keyof InferenceDraft & string, text: string, hint?: string) => (
    <label className="xc-field" key={key}>
      {text}
      <input className="xc-input xc-input--mono" inputMode="decimal" value={draft[key] as string} onChange={(e) => set(key, e.target.value as never)} aria-invalid={Boolean(err(key))} />
      {hint && <span className="xc-note">{hint}</span>}
      {err(key) && <span className="xc-field-error" role="alert">{err(key)}</span>}
    </label>
  )

  return (
    <form className="xc-form xc-settings-form" onSubmit={(e) => { e.preventDefault(); void save() }} aria-label="Inference settings">
      <p className="xc-note">
        Controls the extraction worker that proposes entities, relations and PARA labels from memories. Proposals are never written to the
        graph by themselves: they wait in Review unless this policy lets a confident one through.
      </p>

      <fieldset className="xc-fieldset">
        <legend className="xc-eyebrow">Worker</legend>
        <label className="xc-check xc-settings-row"><input type="checkbox" checked={draft.enabled} onChange={(e) => set('enabled', e.target.checked)} /><span>Inference enabled</span></label>
        <div className="xc-formgrid">
          <label className="xc-field">Harness<input className="xc-input" value={draft.harness} onChange={(e) => set('harness', e.target.value)} aria-invalid={Boolean(err('harness'))} />{err('harness') && <span className="xc-field-error" role="alert">{err('harness')}</span>}</label>
          <label className="xc-field">Profile name<input className="xc-input" value={draft.profile_name} onChange={(e) => set('profile_name', e.target.value)} aria-invalid={Boolean(err('profile_name'))} />{err('profile_name') && <span className="xc-field-error" role="alert">{err('profile_name')}</span>}</label>
        </div>
        <p className="xc-meta">Provider <b>{server.provider}</b> — the only provider this version accepts.</p>
        <label className="xc-check xc-settings-row"><input type="checkbox" checked={draft.allow_fallback} onChange={(e) => set('allow_fallback', e.target.checked)} /><span>Allow fallback when the harness is unavailable</span></label>
      </fieldset>

      <fieldset className="xc-fieldset">
        <legend className="xc-eyebrow">Tasks</legend>
        <div className="xc-taskgrid" role="group" aria-label="Task types">
          {TASK_TYPES.map((task) => (
            <label key={task} className="xc-check">
              <input type="checkbox" checked={draft.task_types.includes(task)} onChange={(e) => set('task_types', e.target.checked ? [...draft.task_types, task] : draft.task_types.filter((t) => t !== task))} />
              <span>{label(task)}</span>
            </label>
          ))}
        </div>
        {err('task_types') && <span className="xc-field-error" role="alert">{err('task_types')}</span>}
      </fieldset>

      <fieldset className="xc-fieldset">
        <legend className="xc-eyebrow">Throughput</legend>
        <div className="xc-formgrid">
          {number('batch_size', 'Batch size')}
          {number('interval_seconds', 'Interval (seconds)', 'At least 0.25.')}
          {number('max_attempts', 'Max attempts')}
          {number('timeout_seconds', 'Timeout (seconds)')}
          {number('max_parallel_families', 'Parallel families', '1 to 3.')}
          {number('max_evidence_chars_per_memory', 'Evidence characters per memory', 'At least 256.')}
          {number('max_items_per_type', 'Items per type', '1 to 100.')}
        </div>
        <label className="xc-check xc-settings-row"><input type="checkbox" checked={draft.combined_batching} onChange={(e) => set('combined_batching', e.target.checked)} /><span>Combine task types into one request where possible</span></label>
      </fieldset>

      <fieldset className="xc-fieldset">
        <legend className="xc-eyebrow">Promotion</legend>
        <label className="xc-field">Policy
          <select className="xc-input" value={draft.promotion_policy} onChange={(e) => set('promotion_policy', e.target.value as InferenceDraft['promotion_policy'])}>
            {PROMOTION_POLICIES.map((p) => <option key={p} value={p}>{p === 'confidence_gated' ? 'Confidence gated — confident proposals may be promoted' : 'Review required — every proposal waits for a person'}</option>)}
          </select>
        </label>
        <div className="xc-formgrid">
          {number('human_review_confidence_threshold', 'Review confidence threshold', 'Proposals below this confidence always go to Review. 0 to 1.')}
        </div>
        <p className="xc-note">Per-task thresholds override the default above. Leave empty to use it.</p>
        <div className="xc-formgrid">
          {THRESHOLD_TASKS.map((task) => (
            <label className="xc-field" key={task}>{label(task)} threshold
              <input className="xc-input xc-input--mono" inputMode="decimal" placeholder={String(draft.human_review_confidence_threshold)} value={draft.task_confidence_thresholds[task] ?? ''} onChange={(e) => set('task_confidence_thresholds', { ...draft.task_confidence_thresholds, [task]: e.target.value })} aria-invalid={Boolean(err(`threshold:${task}`))} />
              {err(`threshold:${task}`) && <span className="xc-field-error" role="alert">{err(`threshold:${task}`)}</span>}
            </label>
          ))}
        </div>
        <label className="xc-check xc-settings-row"><input type="checkbox" checked={draft.contradictions_require_review} onChange={(e) => set('contradictions_require_review', e.target.checked)} /><span>Contradictions always require review</span></label>
      </fieldset>

      {message && <div className={`xc-callout xc-callout--${message.tone}`} role={message.tone === 'conflict' ? 'alert' : 'status'}>{message.tone === 'conflict' && <IconWarn />}{message.text}</div>}
      {showErrors && !payload && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />Fix the highlighted fields to save.</div>}

      <div className="xc-actions-row">
        <button type="submit" className="xc-btn xc-btn--primary" disabled={busy || !dirty}>{busy ? 'Saving…' : 'Save inference policy'}</button>
        <button type="button" className="xc-btn" disabled={busy || !dirty} onClick={() => { setDraft(toDraft(server)); setShowErrors(false); setMessage(null) }}>Discard changes</button>
      </div>
    </form>
  )
}
