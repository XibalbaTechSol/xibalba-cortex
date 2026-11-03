import type { DecisionTrace, DecisionTraceEvent } from '../api'
import { elideHash, parseServerTime, shortStamp } from './model'

const EVENT_LABELS: Record<string, string> = {
  llm_call: 'LLM call',
  jev_assessment: 'Jev assessment',
  action_proposal: 'Action proposal',
  policy_decision: 'Policy decision',
  approval: 'Approval',
  tool_execution: 'Tool execution',
  outcome: 'Outcome',
  memory_effect: 'Memory effect',
  anchor_checkpoint: 'Anchor checkpoint',
}

function text(value: unknown, fallback = '—'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function eventType(event: DecisionTraceEvent): string {
  return text(event.envelope.event_type, 'event')
}

function eventTitle(event: DecisionTraceEvent): string {
  return text(
    event.envelope.policy_decision ?? event.envelope.outcome ?? event.envelope.action ?? event.envelope.event_type,
    'Observed transition',
  )
}

function timestamp(event: DecisionTraceEvent): string {
  const value = text(event.envelope.timestamp, event.created_at)
  const parsed = parseServerTime(value)
  return parsed === null ? value : shortStamp(parsed)
}

function probabilityRows(event: DecisionTraceEvent): Array<[string, number]> {
  const raw = event.advisory?.transition_probabilities
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
  return Object.entries(raw)
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([label, value]) => [label, Math.max(0, Math.min(1, value as number))] as [string, number])
    .sort((a, b) => b[1] - a[1])
}

function proofState(trace: DecisionTrace, event: DecisionTraceEvent): 'verified' | 'unverified' {
  const proof = trace.proofs?.[String(event.sequence_number)]
  return trace.valid && Array.isArray(proof) ? 'verified' : 'unverified'
}

export function DecisionTracePanel({ trace, auditUrl }: { trace: DecisionTrace; auditUrl: string }) {
  const available = trace.events.filter((event) => event.advisory?.status === 'available').length
  const unavailable = trace.events.filter((event) => event.advisory && event.advisory.status !== 'available').length
  const verified = trace.events.filter((event) => proofState(trace, event) === 'verified').length

  return (
    <div className="xc-trace-panel" aria-label="DecisionTrace details">
      <section className="xc-trace-summary" aria-label="Trace summary">
        <div><span className="xc-trace-label">Evidence</span><strong className={trace.valid ? 'xc-trace-good' : 'xc-trace-bad'}>{trace.valid ? 'Verified locally' : 'Verification failed'}</strong></div>
        <div><span className="xc-trace-label">Events</span><strong>{trace.events.length}</strong></div>
        <div><span className="xc-trace-label">Jev analysis</span><strong>{available} available{unavailable ? ` · ${unavailable} unavailable` : ''}</strong></div>
        <div><span className="xc-trace-label">Proofs</span><strong>{verified}/{trace.events.length} included</strong></div>
      </section>
      <div className="xc-trace-boundary">
        <strong>Correlation boundary</strong>
        <span>Observed sequence and advisory probabilities only. Jev cannot authorize, execute, sign, or prove causality. Shield/OPA/BCC remains authoritative.</span>
      </div>
      <div className="xc-trace-actions">
        <a className="xc-btn" href={auditUrl} target="_blank" rel="noreferrer">Open full audit view</a>
        <span className="xc-meta">root <span className="xc-hash" title={trace.root ?? undefined}>{trace.root ? elideHash(trace.root) : 'not available'}</span></span>
      </div>
      <ol className="xc-trace-events" aria-label="DecisionTrace event sequence">
        {trace.events.map((event) => {
          const probabilities = probabilityRows(event)
          const advisoryStatus = event.advisory?.status
          const proof = proofState(trace, event)
          return (
            <li key={event.event_id} className="xc-trace-event">
              <div className="xc-trace-event-marker" aria-hidden="true">{event.sequence_number + 1}</div>
              <article className="xc-trace-event-card">
                <div className="xc-card-top">
                  <span className="xc-tag"><i />{EVENT_LABELS[eventType(event)] ?? eventType(event).replace(/_/g, ' ')}</span>
                  <span className="xc-meta">{timestamp(event)}</span>
                </div>
                <h4 className="xc-trace-event-title">{eventTitle(event)}</h4>
                <div className="xc-trace-meta">
                  <span>event <code>{elideHash(event.event_hash)}</code></span>
                  <span>{event.parent_event_hash ? <>parent <code>{elideHash(event.parent_event_hash)}</code></> : 'first event'}</span>
                  <span className={proof === 'verified' ? 'xc-trace-good' : 'xc-trace-bad'}>{proof === 'verified' ? 'Merkle proof verified' : 'Merkle proof unavailable'}</span>
                </div>
                {event.advisory ? (
                  <div className="xc-trace-advisory">
                    <div className="xc-card-top"><strong>Jev advisory</strong><span className={advisoryStatus === 'available' ? 'xc-trace-good' : 'xc-trace-bad'}>{text(advisoryStatus, 'not requested')}</span></div>
                    <div className="xc-trace-advisory-grid">
                      <span>risk <b>{text(event.advisory.risk_category, 'not classified')}</b></span>
                      <span>escalation <b>{event.advisory.recommended_escalation === true ? 'recommended' : 'not recommended'}</b></span>
                    </div>
                    {probabilities.length > 0 ? (
                      <div className="xc-trace-probabilities" aria-label="Transition probabilities">
                        {probabilities.map(([label, value]) => <span key={label} className="xc-trace-probability"><b>{label.replace(/_/g, ' ')}</b><i><em style={{ width: `${value * 100}%` }} /></i>{Math.round(value * 100)}%</span>)}
                      </div>
                    ) : <span className="xc-meta">No transition probability was recorded.</span>}
                    <small>Model annotation only · causal claim: false</small>
                  </div>
                ) : <div className="xc-trace-advisory xc-trace-advisory--empty"><strong>No Jev advisory attached</strong><span className="xc-meta">The observed trace remains valid without provider analysis.</span></div>}
                <details className="xc-trace-envelope"><summary className="xc-meta">View redacted envelope</summary><pre className="xc-pre">{JSON.stringify(event.envelope, null, 2)}</pre></details>
              </article>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
