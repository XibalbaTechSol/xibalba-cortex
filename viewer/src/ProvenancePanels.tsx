import { useState } from 'react'
import {
  api,
  type ExtractionProposal,
  type HybridRetrieveResult,
  type ProjectionCheckpoint,
  type ProjectionReconciliation,
} from './api'
import { Badge, Hash } from './App'
import { verifyDomainMerkleProof } from './merkleVerify'

// Generalizes the ParaPanel accept/dismiss pattern (App.tsx) to every extraction_proposals
// task_type (extract_entities, extract_relations, detect_contradictions, ...), not just PARA.
export function ExtractionProposalsPanel({
  proposals,
  status,
  onStatusChange,
  onDecision,
  onSelectMemory,
}: {
  proposals: ExtractionProposal[]
  status: string
  onStatusChange: (status: string) => void
  onDecision: (proposalId: string, decision: 'accept' | 'dismiss') => void
  onSelectMemory: (memoryId: string) => void
}) {
  return (
    <section className="tab-panel">
      <div className="panel-header">
        <div>
          <h2>Extraction proposals</h2>
          <p>Reviewable output from extraction/classification workers. Nothing writes until you decide.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <select className="session-select" value={status} onChange={(e) => onStatusChange(e.target.value)}>
            <option value="proposed">Proposed</option>
            <option value="accepted">Accepted</option>
            <option value="dismissed">Dismissed</option>
            <option value="stale">Stale</option>
          </select>
          <Badge>{proposals.length} {status}</Badge>
        </div>
      </div>
      {proposals.length === 0 ? (
        <div className="empty-state">
          <h4>No {status} proposals</h4>
          <p>Extraction and contradiction-detection workers produce proposals here once they complete a task.</p>
        </div>
      ) : (
        <div className="item-list">
          {proposals.map((proposal) => (
            <article className="item" key={proposal.id}>
              <div className="item-head">
                <strong>{proposal.task_type}</strong>
                <Badge>{proposal.status}</Badge>
              </div>
              <pre className="small" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {JSON.stringify(proposal.payload, null, 2)}
              </pre>
              {proposal.evidence_quote && <p className="small muted">evidence: &ldquo;{proposal.evidence_quote}&rdquo;</p>}
              <p className="small muted">source hash <Hash value={proposal.source_content_hash} /></p>
              {proposal.decision_note && <p className="small muted">note: {proposal.decision_note}</p>}
              <div className="action-row">
                <button type="button" onClick={() => onSelectMemory(proposal.source_memory_id)}>Inspect source</button>
                {proposal.status === 'proposed' && (
                  <>
                    <button type="button" onClick={() => onDecision(proposal.id, 'accept')}>Accept</button>
                    <button type="button" onClick={() => onDecision(proposal.id, 'dismiss')}>Dismiss</button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

type ProofState = 'idle' | 'checking' | 'valid' | 'invalid'

// Runs a real hybrid_retrieve query and shows the full trace: per-channel ranks, RRF params,
// candidate pool sizes, graph edges, and a client-side-verified Merkle inclusion proof per
// result -- verification happens in the browser (merkleVerify.ts), not by trusting the server's
// own claim that a result belongs to the trace.
export function RetrievalTraceInspector({ onSelectMemory }: { onSelectMemory: (memoryId: string) => void }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<HybridRetrieveResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [proofStates, setProofStates] = useState<Record<number, ProofState>>({})

  const runQuery = async () => {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    setProofStates({})
    try {
      const response = await api.hybridRetrieve({ query, limit: 10 })
      setResult(response)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const verifyRank = async (rank: number) => {
    if (!result) return
    setProofStates((prev) => ({ ...prev, [rank]: 'checking' }))
    try {
      const proof = await api.retrievalTraceEvidence(result.trace_id, rank)
      const valid = await verifyDomainMerkleProof(proof)
      setProofStates((prev) => ({ ...prev, [rank]: valid ? 'valid' : 'invalid' }))
    } catch {
      setProofStates((prev) => ({ ...prev, [rank]: 'invalid' }))
    }
  }

  return (
    <section className="tab-panel">
      <div className="panel-header">
        <div>
          <h2>Retrieval trace inspector</h2>
          <p>Every query here persists a full, independently verifiable trace.</p>
        </div>
      </div>
      <form
        className="exchange-form"
        onSubmit={(e) => {
          e.preventDefault()
          runQuery()
        }}
      >
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Query text, a memory id, or a sha256: content hash" />
        <div className="form-footer">
          <button type="submit" disabled={loading}>{loading ? 'Searching…' : 'Search'}</button>
        </div>
      </form>
      {error && <p className="error-text">{error}</p>}
      {result && (
        <>
          <div className="panel-header">
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {Object.entries(result.channel_status).map(([channel, status]) => (
                <Badge key={channel}>{channel}: {status}</Badge>
              ))}
            </div>
            <Badge>root <Hash value={result.root_hash} /></Badge>
          </div>
          {result.degraded.length > 0 && (
            <p className="small muted">{result.degraded.length} result(s) dropped by diversity/budget controls.</p>
          )}
          <div className="item-list">
            {result.results.map((memory, i) => {
              const rank = i + 1
              const proofState = proofStates[rank] ?? 'idle'
              return (
                <article className="item" key={memory.id}>
                  <div className="item-head">
                    <strong>#{rank}</strong>
                    <Badge>{memory.evidence_class}</Badge>
                    {proofState === 'valid' && <Badge>✓ verified</Badge>}
                    {proofState === 'invalid' && <Badge>✗ verification failed</Badge>}
                  </div>
                  <p className="small">{memory.content.slice(0, 240)}</p>
                  <p className="small muted">content hash <Hash value={memory.content_hash} /></p>
                  <div className="action-row">
                    <button type="button" onClick={() => onSelectMemory(memory.id)}>Inspect</button>
                    <button type="button" disabled={proofState === 'checking'} onClick={() => verifyRank(rank)}>
                      {proofState === 'checking' ? 'Verifying…' : 'Verify inclusion proof'}
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}

// Projection checkpoint/reconciliation status -- recompute from canonical SQLite, compare
// against the last stored checkpoint, and show whether a projection is degraded, not just
// assert it's fine.
export function ProjectionHealthPanel() {
  const [projectionId, setProjectionId] = useState('memories')
  const [checkpoints, setCheckpoints] = useState<ProjectionCheckpoint[]>([])
  const [reconciliation, setReconciliation] = useState<ProjectionReconciliation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = async (id: string) => {
    try {
      const history = await api.projectionCheckpoints(id)
      setCheckpoints(history)
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }

  const runAction = async (action: 'checkpoint' | 'reconcile' | 'rebuild') => {
    setBusy(true)
    setError(null)
    try {
      if (action === 'checkpoint') await api.createProjectionCheckpoint(projectionId)
      if (action === 'rebuild') await api.rebuildProjectionCheckpoint(projectionId)
      if (action === 'reconcile') setReconciliation(await api.reconcileProjectionCheckpoint(projectionId))
      await refresh(projectionId)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="tab-panel">
      <div className="panel-header">
        <div>
          <h2>Projection health</h2>
          <p>Checkpoints recompute from canonical SQLite -- drift is flagged, not silently served.</p>
        </div>
        <select
          className="session-select"
          value={projectionId}
          onChange={(e) => {
            setProjectionId(e.target.value)
            refresh(e.target.value)
          }}
        >
          <option value="memories">memories</option>
          <option value="entities">entities</option>
          <option value="relations">relations</option>
        </select>
      </div>
      <div className="action-row">
        <button type="button" disabled={busy} onClick={() => runAction('checkpoint')}>Create checkpoint</button>
        <button type="button" disabled={busy} onClick={() => runAction('reconcile')}>Reconcile</button>
        <button type="button" disabled={busy} onClick={() => runAction('rebuild')}>Rebuild &amp; verify</button>
        <button type="button" disabled={busy} onClick={() => refresh(projectionId)}>Refresh</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {reconciliation && (
        <div className="item">
          <div className="item-head">
            <strong>Last reconciliation</strong>
            <Badge>{reconciliation.equal ? 'equal' : reconciliation.action}</Badge>
          </div>
          {!reconciliation.equal && (
            <p className="small muted">
              missing: {reconciliation.missing.length}, extra: {reconciliation.extra.length}, reordered: {String(reconciliation.reordered)}
            </p>
          )}
        </div>
      )}
      {checkpoints.length === 0 ? (
        <div className="empty-state"><h4>No checkpoints yet</h4><p>Create one to establish a baseline for this projection.</p></div>
      ) : (
        <div className="item-list">
          {checkpoints.map((checkpoint) => (
            <article className="item" key={checkpoint.id}>
              <div className="item-head">
                <strong>{checkpoint.leaf_count} leaves</strong>
                <Badge>{checkpoint.status}</Badge>
              </div>
              <p className="small muted">root <Hash value={checkpoint.root_hash} /></p>
              <p className="small muted">{checkpoint.created_at}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
