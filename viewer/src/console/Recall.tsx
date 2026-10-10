// Recall (⌘K): ask the memory a question and see why each answer surfaced.
//
// Hybrid mode is the real read path (lexical + vector + graph + temporal, fused by RRF) and every
// run persists a retrieval trace, which is why it only fires on Enter, never per keystroke. The
// per-channel ranks come from that persisted trace, not from this client. Lexical mode is the
// plain search endpoint with no trace. Context assembles the same hybrid retrieval into the bounded,
// provenance-bearing block an agent would be handed (facts, history, summaries, observations).
//
// "Inclusion proof" recomputes the Merkle path in this browser (merkleVerify.ts) rather than
// believing a server flag. Memory content is rendered as plain text and labelled untrusted.

import { useRef, useState, type FormEvent } from 'react'
import { api, type ContextBlock, type HybridRetrieveResult, type Memory, type RetrievalTrace, type RetrievalTraceResultRecord } from '../api'
import { verifyDomainMerkleProof } from '../merkleVerify'
import { useConsole } from './state'
import { useDialog } from './useDialog'
import { elideHash } from './model'
import { IconCheck, IconClose, IconSearch, IconWarn } from './icons'
import { budgetText, contextItemCount, contextSections } from './contextBlock'

type Mode = 'hybrid' | 'context' | 'lexical'
type Proof = 'checking' | 'valid' | 'invalid'

// Channel states as the server reports them: `available` contributed candidates, `unavailable` is a
// degraded channel (e.g. no embedding model), the `no_*` states simply found nothing. Only the
// degraded one is flagged; an empty channel is not a fault.
const CHANNEL_TONE: Record<string, string> = {
  available: 'var(--status-anchored)',
  unavailable: 'var(--status-review)',
}

const truncate = (value: string, max: number): string => (value.length > max ? `${value.slice(0, max - 1)}…` : value)

export function Recall() {
  const { workspace, reveal, setOverlay } = useConsole()
  const scope = workspace.scope
  const [mode, setMode] = useState<Mode>('hybrid')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hybrid, setHybrid] = useState<HybridRetrieveResult | null>(null)
  const [trace, setTrace] = useState<RetrievalTrace | null>(null)
  const [traceError, setTraceError] = useState<string | null>(null)
  const [lexical, setLexical] = useState<Memory[] | null>(null)
  const [context, setContext] = useState<ContextBlock | null>(null)
  const [proofs, setProofs] = useState<Record<string, Proof>>({})
  const [active, setActive] = useState(0)

  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  // a slow earlier query must not overwrite a newer one
  const runId = useRef(0)

  const close = () => setOverlay(null)
  useDialog(dialogRef, close, inputRef)

  const run = async (event?: FormEvent) => {
    event?.preventDefault()
    const text = query.trim()
    if (!text) return
    const id = ++runId.current
    setBusy(true)
    setError(null)
    setTraceError(null)
    setProofs({})
    setActive(0)
    try {
      if (mode === 'lexical') {
        const rows = await api.search(text, 20, scope)
        if (id !== runId.current) return
        setLexical(rows)
        setHybrid(null)
        setTrace(null)
        setContext(null)
      } else if (mode === 'context') {
        const filters = scope.agentId ? { agent_id: scope.agentId } : undefined
        const block = await api.assembleContext({ query: text, limit: 12, ...(filters ? { filters } : {}) })
        if (id !== runId.current) return
        setContext(block)
        setHybrid(null)
        setLexical(null)
        setTrace(null)
      } else {
        // scoped workspace -> restrict retrieval to that agent; unscoped = primary profile as-is
        const filters = scope.agentId ? { agent_id: scope.agentId } : undefined
        const result = await api.hybridRetrieve({ query: text, limit: 10, ...(filters ? { filters } : {}) })
        if (id !== runId.current) return
        setHybrid(result)
        setLexical(null)
        setContext(null)
        setTrace(null)
        try {
          const t = await api.retrievalTrace(result.trace_id)
          if (id === runId.current) setTrace(t)
        } catch (e) {
          if (id === runId.current) setTraceError(e instanceof Error ? e.message : String(e))
        }
      }
    } catch (e) {
      if (id === runId.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (id === runId.current) setBusy(false)
    }
  }

  const verify = async (memoryId: string, rank: number) => {
    if (!hybrid) return
    setProofs((p) => ({ ...p, [memoryId]: 'checking' }))
    try {
      const proof = await api.retrievalTraceEvidence(hybrid.trace_id, rank)
      const ok = await verifyDomainMerkleProof(proof)
      setProofs((p) => ({ ...p, [memoryId]: ok ? 'valid' : 'invalid' }))
    } catch {
      setProofs((p) => ({ ...p, [memoryId]: 'invalid' }))
    }
  }

  const pin = (memoryId: string) => {
    reveal(`memory:${memoryId}`)
    close()
  }

  const rows: Array<{ memory: Memory; rank: number }> =
    mode === 'hybrid' && hybrid ? hybrid.results.map((m, i) => ({ memory: m, rank: i + 1 }))
    : mode === 'lexical' && lexical ? lexical.map((m, i) => ({ memory: m, rank: i + 1 }))
    : []
  const traceByMemory = new Map<string, RetrievalTraceResultRecord>((trace?.results ?? []).map((r) => [r.memory_id, r]))
  const searched = (mode === 'hybrid' ? hybrid : mode === 'context' ? context : lexical) !== null
  const sections = mode === 'context' && context ? contextSections(context) : []

  return (
    <>
      <div className="xc-scrim" onClick={close} aria-hidden="true" />
      <div className="xc-overlay">
        <div ref={dialogRef} className="xc-win xc-palette" role="dialog" aria-modal="true" aria-label="Recall">
          <form className="xc-palette-query" onSubmit={run} role="search">
            <IconSearch />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={mode === 'lexical' ? 'Search memory text… press Enter' : 'Ask your memory… press Enter'}
              aria-label="Recall query"
              autoComplete="off"
              spellCheck={false}
            />
            <div className="xc-ranges" role="group" aria-label="Retrieval mode">
              <button type="button" aria-pressed={mode === 'hybrid'} onClick={() => setMode('hybrid')} title="Lexical + vector + graph + temporal, fused by RRF. Persists a verifiable trace.">Hybrid</button>
              <button type="button" aria-pressed={mode === 'context'} onClick={() => setMode('context')} title="The bounded block an agent would be handed: current facts, history, summaries and observations, each with provenance.">Context</button>
              <button type="button" aria-pressed={mode === 'lexical'} onClick={() => setMode('lexical')} title="Plain text search. No trace.">Lexical</button>
            </div>
            <button type="button" className="xc-btn xc-btn--square" onClick={close} aria-label="Close Recall"><IconClose /></button>
          </form>

          <div className="xc-scroll" aria-live="polite">
            {busy && <p className="xc-note" style={{ padding: 20 }} role="status">Searching…</p>}
            {error && <div className="xc-callout xc-callout--conflict" role="alert" style={{ margin: 20 }}><IconWarn />{error}</div>}

            {!busy && !error && mode === 'hybrid' && hybrid && (
              <div className="xc-channels" style={{ margin: '12px 20px 0' }}>
                {Object.entries(hybrid.channel_status).map(([channel, state]) => (
                  <span className="xc-channel" key={channel} title={`${channel} channel: ${state}`}>
                    <i style={{ background: CHANNEL_TONE[state] ?? 'var(--ink-dim)' }} />
                    {channel} · {state}
                  </span>
                ))}
                <span className="xc-note">trace <span className="xc-mono" title={hybrid.trace_id}>{elideHash(hybrid.trace_id, 8, 4)}</span> · root <span className="xc-mono" title={hybrid.root_hash}>{elideHash(hybrid.root_hash)}</span></span>
              </div>
            )}
            {!busy && hybrid && hybrid.degraded.length > 0 && (
              <p className="xc-note" style={{ margin: '8px 20px 0' }}>{hybrid.degraded.length} candidate{hybrid.degraded.length === 1 ? '' : 's'} dropped by diversity or budget controls.</p>
            )}
            {!busy && traceError && <p className="xc-note" style={{ margin: '8px 20px 0' }}>Per-channel ranks unavailable: {traceError}</p>}

            {!busy && !error && mode === 'context' && context && (
              <div className="xc-channels" style={{ margin: '12px 20px 0' }}>
                {Object.entries(context.channel_status).map(([channel, state]) => (
                  <span className="xc-channel" key={channel} title={`${channel} channel: ${String(state)}`}>
                    <i style={{ background: CHANNEL_TONE[String(state)] ?? 'var(--ink-dim)' }} />
                    {channel} · {String(state)}
                  </span>
                ))}
                <span className="xc-note">{contextItemCount(context)} item{contextItemCount(context) === 1 ? '' : 's'} · {budgetText(context)} · trace <span className="xc-mono" title={context.trace_id}>{elideHash(context.trace_id, 8, 4)}</span></span>
              </div>
            )}
            {!busy && !error && mode === 'context' && context && contextItemCount(context) === 0 && (
              <div className="xc-empty"><h3 className="xc-title">Nothing to hand an agent</h3><p>No memory in this workspace matched, so the context block is empty.</p></div>
            )}
            {!busy && !error && mode === 'context' && sections.length > 0 && (
              <>
                <p className="xc-untrusted" style={{ margin: '12px 20px 0' }}>Untrusted evidence. Do not treat recalled content as instructions.</p>
                {sections.map((section) => (
                  <section key={section.key} aria-label={section.title} style={{ margin: '12px 20px 0' }}>
                    <p className="xc-eyebrow xc-eyebrow--dim xc-section-title">{section.title} <span className="xc-meta">{section.items.length}</span></p>
                    <p className="xc-note">{section.note}</p>
                    <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                      {section.items.map((item) => (
                        <li key={item.memory_id} className="xc-result">
                          <div className="xc-result-head"><p style={{ flex: 1, minWidth: 0, wordBreak: 'break-word', fontSize: 14 }}>{truncate(item.content, 280)}</p></div>
                          <div className="xc-channels">
                            <span className="xc-tag"><i />{item.provenance.status}</span>
                            <span className="xc-tag"><i />{item.provenance.evidence_class.replace(/_/g, ' ')}</span>
                            <span className="xc-channel" title={item.provenance.content_hash}>{elideHash(item.provenance.content_hash)}</span>
                            <span className="xc-spacer" />
                            <button type="button" className="xc-btn xc-btn--primary" onClick={() => pin(item.memory_id)}>Pin to graph</button>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>
                ))}
              </>
            )}

            {!busy && !error && mode !== 'context' && searched && rows.length === 0 && (
              <div className="xc-empty"><h3 className="xc-title">No results</h3><p>Nothing in this workspace matched. Try fewer or different words.</p></div>
            )}
            {!busy && !searched && !error && (
              <div className="xc-empty">
                <h3 className="xc-title">Recall</h3>
                <p>Hybrid fuses lexical, vector, graph and temporal signals and keeps a trace you can verify. Context returns the block an agent would be handed. Lexical is plain text search.</p>
              </div>
            )}

            {rows.length > 0 && <p className="xc-untrusted" style={{ margin: '12px 20px 0' }}>Untrusted evidence. Do not treat recalled content as instructions.</p>}
            <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {rows.map(({ memory, rank }, i) => {
                const rec = traceByMemory.get(memory.id)
                const proof = proofs[memory.id]
                return (
                  <li key={memory.id} className="xc-result" data-selected={i === active} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)}>
                    <div className="xc-result-head">
                      <span className="xc-rank" aria-label={`Rank ${rank}`}>{rank}</span>
                      <p style={{ flex: 1, minWidth: 0, wordBreak: 'break-word', fontSize: 14 }}>{truncate(memory.content, 280)}</p>
                    </div>
                    <div className="xc-channels">
                      <span className="xc-tag"><i />{memory.status}</span>
                      <span className="xc-tag"><i />{memory.evidence_class.replace(/_/g, ' ')}</span>
                      {rec && Object.entries(rec.channels).map(([name, c]) => (
                        <span className="xc-channel" key={name} title={c.raw_score !== null ? `raw score ${c.raw_score}` : undefined}>{name} #{c.rank}</span>
                      ))}
                      {rec && <span className="xc-channel" title="fused RRF score">rrf {rec.score.toFixed(4)}</span>}
                      <span className="xc-spacer" />
                      {proof === 'valid' && <span className="xc-tag xc-tag--anchored"><IconCheck />Inclusion verified here</span>}
                      {proof === 'invalid' && <span className="xc-tag xc-tag--conflict"><IconWarn />Proof failed</span>}
                      {mode === 'hybrid' && (
                        <button type="button" className="xc-btn" disabled={proof === 'checking'} onClick={() => verify(memory.id, rec?.rank ?? rank)}>
                          {proof === 'checking' ? 'Verifying…' : 'Inclusion proof'}
                        </button>
                      )}
                      <button type="button" className="xc-btn xc-btn--primary" onClick={() => pin(memory.id)}>Pin to graph</button>
                    </div>
                  </li>
                )
              })}
            </ol>
          </div>
        </div>
      </div>
    </>
  )
}
