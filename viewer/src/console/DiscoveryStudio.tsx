// DiscoveryStudio: Interactive research & discovery workbench for Cortex Knowledge Graph.
//
// Unifies data ingestion connectors (triples, PubMed/biomedical, HL7 FHIR), active inference
// (multi-hop pathway tracing, topological link prediction, drug repurposing), and the closed-loop
// AIS reinforcement learning reward engine (R_total = R_task + lambda * AIS).

import { useState, type FormEvent } from 'react'
import {
  api,
  type ConnectorResult,
  type LinkPrediction,
  type MechanicPath,
  type RepurposingCandidate,
  type StepRewardResult,
} from '../api'
import { useConsole } from './state'
import { IconCheck, IconWarn } from './icons'

type StudioTab = 'connectors' | 'inference' | 'reward'
type ConnectorKind = 'csv' | 'biomedical' | 'fhir'
type InferenceKind = 'mechanisms' | 'predict' | 'repurposing'

export function DiscoveryStudio() {
  const { workspace } = useConsole()
  const [tab, setTab] = useState<StudioTab>('connectors')

  return (
    <div className="xc-discovery-studio" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', width: '100%' }}>
      <div className="xc-tabs" role="tablist" aria-label="Research and Discovery Modes">
        <button
          type="button"
          role="tab"
          className="xc-tab"
          aria-selected={tab === 'connectors'}
          onClick={() => setTab('connectors')}
        >
          Data Ingestion Connectors
        </button>
        <button
          type="button"
          role="tab"
          className="xc-tab"
          aria-selected={tab === 'inference'}
          onClick={() => setTab('inference')}
        >
          Active Inference & Discovery
        </button>
        <button
          type="button"
          role="tab"
          className="xc-tab"
          aria-selected={tab === 'reward'}
          onClick={() => setTab('reward')}
        >
          AIS Graph Reward Engine
        </button>
      </div>

      {tab === 'connectors' && <ConnectorsSection agentId={workspace.scope.agentId} />}
      {tab === 'inference' && <InferenceSection agentId={workspace.scope.agentId} />}
      {tab === 'reward' && <RewardSection agentId={workspace.scope.agentId} />}
    </div>
  )
}

// -------------------------------------------------------------------------------------------------
// 1. Data Ingestion Connectors
// -------------------------------------------------------------------------------------------------

function ConnectorsSection({ agentId }: { agentId?: string }) {
  const [kind, setKind] = useState<ConnectorKind>('csv')
  const [sourceName, setSourceName] = useState('biomedical_connectors')
  const [isShared, setIsShared] = useState(true)

  // CSV State
  const [csvText, setCsvText] = useState(
    'head,relation,tail,confidence\nImatinib,inhibits,BCR-ABL1,0.99\nBCR-ABL1,associated_with,Chronic Myeloid Leukemia,0.95\nImatinib,inhibits,c-KIT,0.94\nc-KIT,associated_with,Gastrointestinal Stromal Tumor,0.91'
  )

  // Biomedical Article State
  const [bioTitle, setBioTitle] = useState('Tyrosine Kinase Inhibition Mechanisms in Gastrointestinal Tumors')
  const [bioAbstract, setBioAbstract] = useState(
    'Imatinib mesylate demonstrates targeted inhibition of BCR-ABL1 and c-KIT receptor tyrosine kinases. In patients with Gastrointestinal Stromal Tumor (GIST) harboring activating KIT mutations, Imatinib induces apoptotic regression. Furthermore, Pembrolizumab targets PD-1, modulating T-Cell Activation in Non-Small Cell Lung Cancer.'
  )
  const [bioPmid, setBioPmid] = useState('38912044')
  const [bioDoi, setBioDoi] = useState('10.1016/j.cortex.2026.04.012')

  // FHIR State
  const [fhirJson, setFhirJson] = useState(
    JSON.stringify(
      {
        resourceType: 'Bundle',
        entry: [
          {
            resource: {
              resourceType: 'Patient',
              id: 'pat-xibalba-881',
              gender: 'male',
              birthDate: '1975-08-20',
            },
          },
          {
            resource: {
              resourceType: 'Condition',
              id: 'cond-901',
              subject: { reference: 'Patient/pat-xibalba-881' },
              code: {
                text: 'Chronic Myeloid Leukemia',
                coding: [{ system: 'http://hl7.org/fhir/sid/icd-10', code: 'C92.1' }],
              },
            },
          },
          {
            resource: {
              resourceType: 'MedicationRequest',
              id: 'med-401',
              subject: { reference: 'Patient/pat-xibalba-881' },
              medicationCodeableConcept: {
                text: 'Imatinib',
                coding: [{ system: 'http://www.nlm.nih.gov/research/umls/rxnorm', code: '282388' }],
              },
            },
          },
        ],
      },
      null,
      2
    )
  )
  const [deidentify, setDeidentify] = useState(true)

  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ConnectorResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleIngest = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      if (kind === 'csv') {
        const res = await api.ingestCSV({
          csv_text: csvText,
          source_name: sourceName || 'csv_import',
          agent_id: agentId,
          shared: isShared,
        })
        setResult(res)
      } else if (kind === 'biomedical') {
        const res = await api.ingestBiomedical({
          title: bioTitle,
          abstract: bioAbstract,
          pmid: bioPmid || undefined,
          doi: bioDoi || undefined,
          agent_id: agentId,
          shared: isShared,
        })
        setResult(res)
      } else if (kind === 'fhir') {
        const parsedBundle = JSON.parse(fhirJson)
        const res = await api.ingestFHIR({
          bundle: parsedBundle,
          source_name: sourceName || 'fhir_sync',
          deidentify,
          agent_id: agentId,
          shared: isShared,
        })
        setResult(res)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(320px, 1fr)', gap: '1.25rem' }}>
      <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div>
          <p className="xc-eyebrow">Connectors & Pipeline Ingestion</p>
          <h3 className="xc-title">Ingest Custom Knowledge Datasets</h3>
          <p className="xc-note">
            Ingest structured triples, peer-reviewed biomedical literature, or HL7 FHIR clinical EHR records directly
            into Cortex's knowledge graph.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            className={`xc-btn ${kind === 'csv' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('csv')}
          >
            CSV / TSV Triples
          </button>
          <button
            type="button"
            className={`xc-btn ${kind === 'biomedical' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('biomedical')}
          >
            PubMed Literature
          </button>
          <button
            type="button"
            className={`xc-btn ${kind === 'fhir' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('fhir')}
          >
            HL7 FHIR Clinical
          </button>
        </div>

        <form onSubmit={handleIngest} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div>
            <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Source / Collection Name</label>
            <input
              className="xc-input"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              placeholder="e.g. oncology_trial_dataset"
            />
          </div>

          <label className="xc-inline" style={{ fontSize: '0.8125rem' }}>
            <input type="checkbox" checked={isShared} onChange={(e) => setIsShared(e.target.checked)} />
            <span>Shared across research workspace (uncheck for agent-isolated partition)</span>
          </label>

          {kind === 'csv' && (
            <div>
              <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>CSV / TSV Content (head,relation,tail,confidence)</label>
              <textarea
                className="xc-input"
                style={{ fontFamily: 'monospace', fontSize: '0.8125rem', height: '140px', resize: 'vertical' }}
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
              />
            </div>
          )}

          {kind === 'biomedical' && (
            <>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Publication Title</label>
                <input
                  className="xc-input"
                  value={bioTitle}
                  onChange={(e) => setBioTitle(e.target.value)}
                  placeholder="Article Title"
                />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                <div>
                  <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>PMID (optional)</label>
                  <input
                    className="xc-input"
                    value={bioPmid}
                    onChange={(e) => setBioPmid(e.target.value)}
                    placeholder="e.g. 12345678"
                  />
                </div>
                <div>
                  <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>DOI (optional)</label>
                  <input
                    className="xc-input"
                    value={bioDoi}
                    onChange={(e) => setBioDoi(e.target.value)}
                    placeholder="10.1016/..."
                  />
                </div>
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Abstract & Findings (Auto-entity & Relation Extraction)</label>
                <textarea
                  className="xc-input"
                  style={{ fontSize: '0.8125rem', height: '120px', resize: 'vertical' }}
                  value={bioAbstract}
                  onChange={(e) => setBioAbstract(e.target.value)}
                />
              </div>
            </>
          )}

          {kind === 'fhir' && (
            <>
              <label className="xc-inline" style={{ fontSize: '0.8125rem' }}>
                <input type="checkbox" checked={deidentify} onChange={(e) => setDeidentify(e.target.checked)} />
                <span>Cryptographic PHI Gating & Anonymization (SHA-256 salted patient hashing)</span>
              </label>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>FHIR R4 Bundle JSON</label>
                <textarea
                  className="xc-input"
                  style={{ fontFamily: 'monospace', fontSize: '0.8125rem', height: '140px', resize: 'vertical' }}
                  value={fhirJson}
                  onChange={(e) => setFhirJson(e.target.value)}
                />
              </div>
            </>
          )}

          <button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>
            {busy ? 'Processing Ingestion…' : 'Ingest into Knowledge Graph'}
          </button>
        </form>
      </section>

      <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div>
          <p className="xc-eyebrow">Ingestion Audit & Lineage</p>
          <h3 className="xc-title">Ingest Result</h3>
        </div>

        {error && (
          <div className="xc-callout xc-callout--conflict">
            <IconWarn />
            <span>Ingestion failed: {error}</span>
          </div>
        )}

        {result && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div
              className={`xc-callout ${result.success ? 'xc-callout--anchored' : 'xc-callout--conflict'}`}
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
            >
              {result.success ? <IconCheck /> : <IconWarn />}
              <b>{result.success ? 'Dataset Successfully Ingested' : 'Ingestion Completed with Errors'}</b>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
              <div className="xc-win" style={{ padding: '0.75rem', textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{result.entities_created}</div>
                <div className="xc-meta">Entities Created</div>
              </div>
              <div className="xc-win" style={{ padding: '0.75rem', textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{result.relations_created}</div>
                <div className="xc-meta">Relations Created</div>
              </div>
              <div className="xc-win" style={{ padding: '0.75rem', textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{result.memories_created}</div>
                <div className="xc-meta">Evidential Memories</div>
              </div>
            </div>

            <div className="xc-win" style={{ padding: '0.75rem' }}>
              <div className="xc-meta" style={{ marginBottom: '0.25rem' }}>Source Identifier</div>
              <div style={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>{result.source_name}</div>
            </div>

            {result.metadata && Object.keys(result.metadata).length > 0 && (
              <div className="xc-win" style={{ padding: '0.75rem' }}>
                <div className="xc-meta" style={{ marginBottom: '0.25rem' }}>Metadata & Provenance</div>
                <pre style={{ margin: 0, fontSize: '0.75rem', overflowX: 'auto' }}>
                  {JSON.stringify(result.metadata, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {!result && !error && (
          <div className="xc-empty">
            <h4 className="xc-title">Ready for Ingestion</h4>
            <p className="xc-note">Select a dataset format, adjust fields, and execute pipeline ingestion.</p>
          </div>
        )}
      </section>
    </div>
  )
}

// -------------------------------------------------------------------------------------------------
// 2. Active Inference & Link Prediction
// -------------------------------------------------------------------------------------------------

function InferenceSection({ agentId }: { agentId?: string }) {
  const [kind, setKind] = useState<InferenceKind>('mechanisms')

  // Mechanisms
  const [sourceEntity, setSourceEntity] = useState('Imatinib')
  const [targetEntity, setTargetEntity] = useState('Chronic Myeloid Leukemia')
  const [depth, setDepth] = useState(4)
  const [mechanisms, setMechanisms] = useState<MechanicPath[] | null>(null)

  // Link Prediction
  const [predSource, setPredSource] = useState('Imatinib')
  const [predTarget, setPredTarget] = useState('Gastrointestinal Stromal Tumor')
  const [prediction, setPrediction] = useState<LinkPrediction | null>(null)

  // Repurposing
  const [disease, setDisease] = useState('Gastrointestinal Stromal Tumor')
  const [topK, setTopK] = useState(5)
  const [repurposing, setRepurposing] = useState<RepurposingCandidate[] | null>(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleRunInference = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (kind === 'mechanisms') {
        const res = await api.traceMechanisms(sourceEntity, targetEntity, depth, agentId)
        setMechanisms(res)
      } else if (kind === 'predict') {
        const res = await api.predictLinks(predSource, predTarget, 'associated_with', agentId)
        setPrediction(res)
      } else if (kind === 'repurposing') {
        const res = await api.suggestRepurposing(disease, topK, agentId)
        setRepurposing(res)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(320px, 1fr)', gap: '1.25rem' }}>
      <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div>
          <p className="xc-eyebrow">Active Inference & Discovery</p>
          <h3 className="xc-title">Trace Pathways & Discover Latent Links</h3>
          <p className="xc-note">
            Navigate beyond static retrieval: discover multi-hop mechanistic pathways and score hidden relationships
            using graph topology.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            className={`xc-btn ${kind === 'mechanisms' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('mechanisms')}
          >
            Trace Mechanisms
          </button>
          <button
            type="button"
            className={`xc-btn ${kind === 'predict' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('predict')}
          >
            Predict Hidden Links
          </button>
          <button
            type="button"
            className={`xc-btn ${kind === 'repurposing' ? 'xc-btn--primary' : 'xc-btn--ghost'}`}
            onClick={() => setKind('repurposing')}
          >
            Drug Repurposing
          </button>
        </div>

        <form onSubmit={handleRunInference} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {kind === 'mechanisms' && (
            <>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Source Molecule / Drug</label>
                <input
                  className="xc-input"
                  value={sourceEntity}
                  onChange={(e) => setSourceEntity(e.target.value)}
                  placeholder="e.g. Imatinib"
                />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Target Disease / Endpoint</label>
                <input
                  className="xc-input"
                  value={targetEntity}
                  onChange={(e) => setTargetEntity(e.target.value)}
                  placeholder="e.g. Chronic Myeloid Leukemia"
                />
              </div>
              <label className="xc-inline">
                <span>Maximum Traversal Depth:</span>
                <select className="xc-input" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
                  {[2, 3, 4, 5, 6].map((d) => (
                    <option key={d} value={d}>
                      {d} hops
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          {kind === 'predict' && (
            <>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Source Node</label>
                <input
                  className="xc-input"
                  value={predSource}
                  onChange={(e) => setPredSource(e.target.value)}
                  placeholder="e.g. Imatinib"
                />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Candidate Node</label>
                <input
                  className="xc-input"
                  value={predTarget}
                  onChange={(e) => setPredTarget(e.target.value)}
                  placeholder="e.g. Gastrointestinal Stromal Tumor"
                />
              </div>
            </>
          )}

          {kind === 'repurposing' && (
            <>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Target Disease Phenotype</label>
                <input
                  className="xc-input"
                  value={disease}
                  onChange={(e) => setDisease(e.target.value)}
                  placeholder="e.g. Gastrointestinal Stromal Tumor"
                />
              </div>
              <label className="xc-inline">
                <span>Candidate Ranking Limit (Top K):</span>
                <select className="xc-input" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                  {[3, 5, 10].map((k) => (
                    <option key={k} value={k}>
                      {k} candidates
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          <button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>
            {busy ? 'Running Inference…' : 'Execute Graph Inference'}
          </button>
        </form>
      </section>

      <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div>
          <p className="xc-eyebrow">Mechanistic Proof & Link Geometry</p>
          <h3 className="xc-title">Inference Results</h3>
        </div>

        {error && (
          <div className="xc-callout xc-callout--conflict">
            <IconWarn />
            <span>Inference error: {error}</span>
          </div>
        )}

        {kind === 'mechanisms' && mechanisms && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {mechanisms.length === 0 ? (
              <div className="xc-empty">
                <h4 className="xc-title">No Mechanistic Pathways Found</h4>
                <p className="xc-note">No continuous biological path connects these entities within {depth} hops.</p>
              </div>
            ) : (
              mechanisms.map((m, idx) => (
                <div key={idx} className="xc-win" style={{ padding: '0.75rem' }}>
                  <div className="xc-meta" style={{ marginBottom: '0.5rem' }}>
                    Pathway #{idx + 1} ({m.length} hops)
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {m.steps.map((s, stepIdx) => (
                      <span key={stepIdx} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span className="xc-badge" style={{ fontWeight: 600 }}>{s.subject}</span>
                        <span className="xc-meta" style={{ fontSize: '0.75rem' }}>—[{s.predicate}]→</span>
                        {stepIdx === m.steps.length - 1 && (
                          <span className="xc-badge" style={{ fontWeight: 600 }}>{s.object}</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {kind === 'predict' && prediction && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div className="xc-win" style={{ padding: '1rem', textAlign: 'center' }}>
              <div className="xc-meta">Predicted Link Probability</div>
              <div
                style={{
                  fontSize: '2rem',
                  fontWeight: 700,
                  color: prediction.probability > 0.4 ? 'var(--status-anchored)' : 'var(--status-review)',
                }}
              >
                {(prediction.probability * 100).toFixed(1)}%
              </div>
              <div className="xc-meta">
                Latent relation: <b>{prediction.source}</b> —[{prediction.relation}]→ <b>{prediction.target}</b>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
              <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                <div style={{ fontWeight: 600 }}>{prediction.metrics.jaccard.toFixed(3)}</div>
                <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Jaccard Index</div>
              </div>
              <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                <div style={{ fontWeight: 600 }}>{prediction.metrics.adamic_adar.toFixed(3)}</div>
                <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Adamic-Adar</div>
              </div>
              <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                <div style={{ fontWeight: 600 }}>{prediction.metrics.resource_allocation.toFixed(3)}</div>
                <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Resource Alloc</div>
              </div>
            </div>

            <div className="xc-win" style={{ padding: '0.75rem' }}>
              <div className="xc-meta" style={{ marginBottom: '0.25rem' }}>
                Shared Intermediate Neighbors ({prediction.common_neighbors.length})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                {prediction.common_neighbors.length === 0 ? (
                  <span className="xc-note">No direct topological overlap</span>
                ) : (
                  prediction.common_neighbors.map((n) => (
                    <span key={n} className="xc-badge">{n}</span>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {kind === 'repurposing' && repurposing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {repurposing.length === 0 ? (
              <div className="xc-empty">
                <h4 className="xc-title">No Repurposing Candidates Found</h4>
                <p className="xc-note">No compounds in graph exhibit pathway overlap with {disease}.</p>
              </div>
            ) : (
              repurposing.map((c, idx) => (
                <div key={idx} className="xc-win" style={{ padding: '0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.9375rem' }}>{c.drug}</div>
                    <div className="xc-meta" style={{ fontSize: '0.75rem' }}>
                      Via targets: {c.connecting_targets.join(', ') || 'topological overlap'}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span
                      className="xc-badge"
                      style={{
                        backgroundColor: 'var(--status-anchored)',
                        color: '#fff',
                        fontWeight: 600,
                      }}
                    >
                      Score: {(c.predicted_affinity * 100).toFixed(0)}%
                    </span>
                    <div className="xc-meta" style={{ fontSize: '0.7rem', marginTop: '0.25rem' }}>
                      {c.mechanisms_count} pathway{c.mechanisms_count === 1 ? '' : 's'}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {!mechanisms && !prediction && !repurposing && !error && (
          <div className="xc-empty">
            <h4 className="xc-title">Awaiting Inference Query</h4>
            <p className="xc-note">Select an inference modality and execute discovery.</p>
          </div>
        )}
      </section>
    </div>
  )
}

// -------------------------------------------------------------------------------------------------
// 3. AIS Graph Reward Engine Simulator
// -------------------------------------------------------------------------------------------------

function RewardSection({ agentId }: { agentId?: string }) {
  const [source, setSource] = useState('Imatinib')
  const [relation, setRelation] = useState('inhibits')
  const [target, setTarget] = useState('BCR-ABL1')
  const [taskReward, setTaskReward] = useState(1.0)
  const [bondedStake, setBondedStake] = useState(100.0)
  const [cost, setCost] = useState(0.01)

  const [stepResult, setStepResult] = useState<StepRewardResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const applyPreset = (preset: 'verified' | 'hallucination' | 'violation') => {
    if (preset === 'verified') {
      setSource('Imatinib')
      setRelation('inhibits')
      setTarget('BCR-ABL1')
      setTaskReward(1.0)
      setBondedStake(100.0)
    } else if (preset === 'hallucination') {
      setSource('Imatinib')
      setRelation('cures')
      setTarget('CompletelyFictitiousDiseaseXYZ')
      setTaskReward(5.0) // Agent aggressively claims task completion
      setBondedStake(100.0)
    } else if (preset === 'violation') {
      setSource('Imatinib')
      setRelation('leak_phi')
      setTarget('Patient_SSN_99182')
      setTaskReward(2.0)
      setBondedStake(100.0)
    }
  }

  const handleEvaluate = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api.evaluateStepReward({
        source,
        relation,
        target,
        task_reward: taskReward,
        cost,
        bonded_stake: bondedStake,
        agent_id: agentId,
      })
      setStepResult(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="xc-win xc-pane" style={{ padding: '1rem', borderLeft: '4px solid var(--status-anchored)' }}>
        <p className="xc-eyebrow">Closed-Loop Reinforcement Learning Foundation</p>
        <h3 className="xc-title" style={{ marginBottom: '0.25rem' }}>
          R_total = R_task + λ · AIS
        </h3>
        <p className="xc-note" style={{ margin: 0 }}>
          <b>Zero Tolerance for Hallucination:</b> By taking the geometric mean{' '}
          <code style={{ fontSize: '0.8125rem' }}>(S_g^0.35 · S_c^0.30 · S_s^0.20 · S_e^0.15)</code>, any ungrounded step
          causes <code style={{ fontSize: '0.8125rem' }}>S_grounding = 0.0</code>, annihilating AIS to 0.0 and imposing
          negative return and collateral slashing. Unwanted behaviors become economically prohibitive.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(320px, 1.2fr)', gap: '1.25rem' }}>
        <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <p className="xc-eyebrow">Graph Navigation Step Evaluation</p>
            <h3 className="xc-title">Configure Step Parameters</h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <span className="xc-meta">Quick Simulation Scenarios:</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
              <button
                type="button"
                className="xc-btn xc-btn--ghost"
                onClick={() => applyPreset('verified')}
                title="Verified biologically grounded step"
              >
                1. Verified Grounding
              </button>
              <button
                type="button"
                className="xc-btn xc-btn--ghost"
                onClick={() => applyPreset('hallucination')}
                title="Ungrounded fictitious claim"
              >
                2. Hallucinated Step
              </button>
              <button
                type="button"
                className="xc-btn xc-btn--danger-quiet"
                onClick={() => applyPreset('violation')}
                title="Prohibited policy/PHI breach"
              >
                3. Policy Violation
              </button>
            </div>
          </div>

          <form onSubmit={handleEvaluate} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem' }}>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Source Node</label>
                <input className="xc-input" value={source} onChange={(e) => setSource(e.target.value)} />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Relation</label>
                <input className="xc-input" value={relation} onChange={(e) => setRelation(e.target.value)} />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Target Node</label>
                <input className="xc-input" value={target} onChange={(e) => setTarget(e.target.value)} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem' }}>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Claimed Task Reward</label>
                <input
                  type="number"
                  step="0.1"
                  className="xc-input"
                  value={taskReward}
                  onChange={(e) => setTaskReward(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Bonded Collateral Stake</label>
                <input
                  type="number"
                  step="1"
                  className="xc-input"
                  value={bondedStake}
                  onChange={(e) => setBondedStake(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="xc-meta" style={{ display: 'block', marginBottom: '0.25rem' }}>Cost Friction (λ)</label>
                <input
                  type="number"
                  step="0.005"
                  className="xc-input"
                  value={cost}
                  onChange={(e) => setCost(Number(e.target.value))}
                />
              </div>
            </div>

            <button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>
              {busy ? 'Evaluating Mathematical Reward…' : 'Evaluate Closed-Loop RL Reward'}
            </button>
          </form>
        </section>

        <section className="xc-win xc-pane" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <p className="xc-eyebrow">RL Signal & Economic Verification</p>
            <h3 className="xc-title">Reward Diagnostics</h3>
          </div>

          {error && (
            <div className="xc-callout xc-callout--conflict">
              <IconWarn />
              <span>Evaluation error: {error}</span>
            </div>
          )}

          {stepResult && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div
                className="xc-win"
                style={{
                  padding: '1.25rem',
                  textAlign: 'center',
                  borderLeft: `6px solid ${
                    stepResult.total_reward > 0 ? 'var(--status-anchored)' : 'var(--status-conflict)'
                  }`,
                }}
              >
                <div className="xc-meta">Instantaneous Total RL Reward (R_total)</div>
                <div
                  style={{
                    fontSize: '2.5rem',
                    fontWeight: 800,
                    color: stepResult.total_reward > 0 ? 'var(--status-anchored)' : 'var(--status-conflict)',
                  }}
                >
                  {stepResult.total_reward > 0 ? `+${stepResult.total_reward.toFixed(3)}` : stepResult.total_reward.toFixed(3)}
                </div>
                <div className="xc-meta" style={{ marginTop: '0.25rem' }}>
                  Composite AIS: <b>{stepResult.ais.toFixed(4)}</b> (Scale: 0.0 — 1.0)
                </div>
              </div>

              {/* 4 Pillars Breakdown */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                  <div
                    style={{
                      fontWeight: 700,
                      color: stepResult.grounding > 0 ? 'var(--status-anchored)' : 'var(--status-conflict)',
                    }}
                  >
                    {stepResult.grounding.toFixed(2)}
                  </div>
                  <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Grounding (S_g)</div>
                </div>

                <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                  <div
                    style={{
                      fontWeight: 700,
                      color: stepResult.compliance > 0 ? 'var(--status-anchored)' : 'var(--status-conflict)',
                    }}
                  >
                    {stepResult.compliance.toFixed(2)}
                  </div>
                  <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Compliance (S_c)</div>
                </div>

                <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                  <div style={{ fontWeight: 700 }}>{stepResult.sacrifice.toFixed(2)}</div>
                  <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Sacrifice (S_s)</div>
                </div>

                <div className="xc-win" style={{ padding: '0.5rem', textAlign: 'center' }}>
                  <div style={{ fontWeight: 700 }}>{stepResult.entropy.toFixed(2)}</div>
                  <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Entropy (S_e)</div>
                </div>
              </div>

              {/* Slashing & Stake Consequences */}
              <div
                className={`xc-callout ${
                  stepResult.slashing_penalty > 0 ? 'xc-callout--conflict' : 'xc-callout--anchored'
                }`}
                style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span><b>Slashing Penalty:</b> -{stepResult.slashing_penalty.toFixed(1)} stake</span>
                  <span><b>Remaining Collateral:</b> {stepResult.remaining_bonded_stake.toFixed(1)}</span>
                </div>
                <div style={{ fontSize: '0.8125rem' }}>{stepResult.explanation}</div>
              </div>
            </div>
          )}

          {!stepResult && !error && (
            <div className="xc-empty">
              <h4 className="xc-title">Ready for Reward Evaluation</h4>
              <p className="xc-note">Execute a step evaluation to inspect mathematical reward and collateral dynamics.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
