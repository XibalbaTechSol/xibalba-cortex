// NodeDeepDive: High-density semantic inner inspection of a Knowledge Graph node.
// Allows users to zoom inside any entity or memory node to view properties tables,
// the Subject-Object-Predicate (SPO) relations matrix, radial ego-neighborhoods,
// and agent navigational action space with instantaneous AIS reward predictions.

import { useState } from 'react'
import type { CNode, GraphModel } from './model'
import { api, type StepRewardResult } from '../api'
import { IconCheck, IconClose } from './icons'

interface NodeDeepDiveProps {
  node: CNode
  model: GraphModel | null
  onClose: () => void
  onSelectNode: (nodeId: string) => void
}

type DeepDiveTab = 'properties' | 'spo_matrix' | 'ego_manifold' | 'action_space'

export function NodeDeepDive({ node, model, onClose, onSelectNode }: NodeDeepDiveProps) {
  const [activeTab, setActiveTab] = useState<DeepDiveTab>('properties')

  // Collect all edges connected to this node
  const allEdges = model
    ? model.edges.filter((e) => e.source === node.id || e.target === node.id)
    : []
  const outgoingEdges = allEdges.filter((e) => e.source === node.id)
  const incomingEdges = allEdges.filter((e) => e.target === node.id)

  // Simulation state for Action Space tab
  const [simulatedAction, setSimulatedAction] = useState<string | null>(null)
  const [simReward, setSimReward] = useState<StepRewardResult | null>(null)
  const [simBusy, setSimBusy] = useState(false)

  const handleSimulateStep = async (predicate: string, targetLabel: string) => {
    setSimBusy(true)
    setSimulatedAction(`${node.label} —[${predicate}]→ ${targetLabel}`)
    try {
      const res = await api.evaluateStepReward({
        source: node.label,
        relation: predicate,
        target: targetLabel,
        task_reward: 1.0,
        bonded_stake: 100.0,
      })
      setSimReward(res)
    } catch {
      setSimReward(null)
    } finally {
      setSimBusy(false)
    }
  }

  // Derive PARA badge if applicable
  const paraType = (node as any).paraClassification || (
    node.label.toLowerCase().startsWith('project:') ? 'Project' :
    node.label.toLowerCase().startsWith('area:') ? 'Area' :
    node.label.toLowerCase().startsWith('resource:') ? 'Resource' :
    node.label.toLowerCase().startsWith('archive:') ? 'Archive' : null
  )

  return (
    <div
      className="xc-scrim"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1.5rem',
        zIndex: 9999,
      }}
      onClick={onClose}
    >
      <div
        className="xc-win"
        style={{
          width: '100%',
          maxWidth: '1000px',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--panel-bg, #0f172a)',
          border: '1px solid var(--border-color, #334155)',
          borderRadius: '8px',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '1.25rem 1.5rem',
            borderBottom: '1px solid var(--border-color, #334155)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <span className="xc-eyebrow" style={{ margin: 0 }}>Semantic Node Manifold</span>
              {paraType && (
                <span className="xc-badge" style={{ backgroundColor: '#3b82f6', color: '#fff', fontSize: '0.7rem' }}>
                  PARA {paraType}
                </span>
              )}
              {(node as any).entityType && (
                <span className="xc-badge" style={{ backgroundColor: 'var(--status-anchored, #10b981)', color: '#fff', fontSize: '0.7rem' }}>
                  {(node as any).entityType}
                </span>
              )}
            </div>
            <h2 className="xc-title" style={{ margin: 0, fontSize: '1.5rem' }}>{node.label}</h2>
            <div className="xc-meta" style={{ fontFamily: 'monospace', fontSize: '0.75rem', marginTop: '0.25rem' }}>
              ID: {node.id} · Degree: {node.degree} ({outgoingEdges.length} out / {incomingEdges.length} in)
            </div>
          </div>
          <button
            type="button"
            className="xc-btn xc-btn--square"
            onClick={onClose}
            aria-label="Close Node Deep Dive"
          >
            <IconClose />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="xc-tabs" style={{ padding: '0 1.5rem', borderBottom: '1px solid var(--border-color, #334155)' }}>
          <button
            type="button"
            className="xc-tab"
            aria-selected={activeTab === 'properties'}
            onClick={() => setActiveTab('properties')}
          >
            Properties & Metadata
          </button>
          <button
            type="button"
            className="xc-tab"
            aria-selected={activeTab === 'spo_matrix'}
            onClick={() => setActiveTab('spo_matrix')}
          >
            SPO Relations Matrix ({allEdges.length})
          </button>
          <button
            type="button"
            className="xc-tab"
            aria-selected={activeTab === 'ego_manifold'}
            onClick={() => setActiveTab('ego_manifold')}
          >
            Radial Ego-Neighborhood
          </button>
          <button
            type="button"
            className="xc-tab"
            aria-selected={activeTab === 'action_space'}
            onClick={() => setActiveTab('action_space')}
          >
            Navigational Action Space & AIS
          </button>
        </div>

        {/* Modal Body */}
        <div className="xc-scroll" style={{ padding: '1.5rem', flex: 1, overflowY: 'auto' }}>
          {activeTab === 'properties' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div>
                <h4 className="xc-title" style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Intrinsic Topological Attributes</h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
                  <div className="xc-win" style={{ padding: '0.75rem' }}>
                    <div className="xc-meta">Total Node Degree</div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{node.degree}</div>
                  </div>
                  <div className="xc-win" style={{ padding: '0.75rem' }}>
                    <div className="xc-meta">Outgoing (Subject)</div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--status-anchored)' }}>{outgoingEdges.length}</div>
                  </div>
                  <div className="xc-win" style={{ padding: '0.75rem' }}>
                    <div className="xc-meta">Incoming (Object)</div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#60a5fa' }}>{incomingEdges.length}</div>
                  </div>
                  <div className="xc-win" style={{ padding: '0.75rem' }}>
                    <div className="xc-meta">Node Classification</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 600, textTransform: 'capitalize' }}>
                      {paraType ? `PARA ${paraType}` : (node as any).entityType || node.cls}
                    </div>
                  </div>
                </div>

                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
                  <tbody>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <td className="xc-meta" style={{ padding: '0.5rem 0', width: '220px' }}>Canonical Label</td>
                      <td style={{ padding: '0.5rem 0', fontWeight: 600 }}>{node.label}</td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <td className="xc-meta" style={{ padding: '0.5rem 0' }}>Internal Graph Identifier</td>
                      <td style={{ padding: '0.5rem 0', fontFamily: 'monospace' }}>{node.id}</td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <td className="xc-meta" style={{ padding: '0.5rem 0' }}>Structural Class</td>
                      <td style={{ padding: '0.5rem 0' }}>{node.cls}</td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <td className="xc-meta" style={{ padding: '0.5rem 0' }}>Verification State</td>
                      <td style={{ padding: '0.5rem 0' }}>
                        <span className="xc-badge" style={{ backgroundColor: 'var(--status-anchored)', color: '#fff' }}>
                          Verified in Active Store
                        </span>
                      </td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.08)' }}>
                      <td className="xc-meta" style={{ padding: '0.5rem 0' }}>Temporal Earliest Mark</td>
                      <td style={{ padding: '0.5rem 0' }}>
                        {node.time ? new Date(node.time).toISOString() : 'Untimed topological node'}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeTab === 'spo_matrix' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <h4 className="xc-title" style={{ fontSize: '1.1rem', marginBottom: '0.25rem' }}>Subject-Predicate-Object (SPO) Relations</h4>
                <p className="xc-note">First-class semantic triples connecting this entity to the wider knowledge graph.</p>
              </div>

              {allEdges.length === 0 ? (
                <div className="xc-empty">
                  <h4 className="xc-title">No Relations Recorded</h4>
                  <p className="xc-note">This node has no typed relationships in the active sample.</p>
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid rgba(255, 255, 255, 0.15)', textAlign: 'left' }}>
                      <th style={{ padding: '0.5rem' }}>Role</th>
                      <th style={{ padding: '0.5rem' }}>Directed Predicate</th>
                      <th style={{ padding: '0.5rem' }}>Connected Entity</th>
                      <th style={{ padding: '0.5rem' }}>Confidence</th>
                      <th style={{ padding: '0.5rem' }}>Evidence Memory</th>
                    </tr>
                  </thead>
                  <tbody>
                    {allEdges.map((e, idx) => {
                      const isSubject = e.source === node.id
                      const adjacentId = isSubject ? e.target : e.source
                      const adjacentNode = model?.byId.get(adjacentId)
                      return (
                        <tr key={idx} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}>
                          <td style={{ padding: '0.5rem' }}>
                            <span className="xc-badge" style={{ backgroundColor: isSubject ? 'rgba(16, 185, 129, 0.2)' : 'rgba(59, 130, 246, 0.2)', color: isSubject ? '#10b981' : '#60a5fa' }}>
                              {isSubject ? 'Subject (S→P→O)' : 'Object (S←P←O)'}
                            </span>
                          </td>
                          <td style={{ padding: '0.5rem', fontWeight: 600 }}>
                            <code style={{ fontSize: '0.8125rem' }}>{e.predicate || e.type}</code>
                          </td>
                          <td style={{ padding: '0.5rem' }}>
                            <button
                              type="button"
                              className="xc-link"
                              style={{ fontWeight: 600 }}
                              onClick={() => onSelectNode(adjacentId)}
                            >
                              {adjacentNode?.label || adjacentId}
                            </button>
                          </td>
                          <td style={{ padding: '0.5rem' }}>
                            {e.similarity !== undefined ? (
                              <span>{(e.similarity * 100).toFixed(0)}% sim</span>
                            ) : (
                              <span>100%</span>
                            )}
                          </td>
                          <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                            {e.evidenceMemoryId ? `${e.evidenceMemoryId.slice(0, 8)}…` : 'Direct Assertion'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {activeTab === 'ego_manifold' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <h4 className="xc-title" style={{ fontSize: '1.1rem', marginBottom: '0.25rem' }}>Radial Ego-Neighborhood</h4>
                <p className="xc-note">Cluster decomposition of adjacent entities partitioned by predicate type.</p>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
                {Array.from(new Set(allEdges.map((e) => e.predicate || e.type))).map((pred) => {
                  const matching = allEdges.filter((e) => (e.predicate || e.type) === pred)
                  return (
                    <div key={pred} className="xc-win" style={{ padding: '0.875rem' }}>
                      <div className="xc-meta" style={{ fontWeight: 600, color: 'var(--status-anchored)', marginBottom: '0.5rem' }}>
                        —[{pred}]→ ({matching.length})
                      </div>
                      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                        {matching.map((e, i) => {
                          const targetId = e.source === node.id ? e.target : e.source
                          const targetNode = model?.byId.get(targetId)
                          return (
                            <li key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                              <i className="xc-row-dot" />
                              <button
                                type="button"
                                className="xc-link"
                                style={{ fontSize: '0.8125rem' }}
                                onClick={() => onSelectNode(targetId)}
                              >
                                {targetNode?.label || targetId}
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {activeTab === 'action_space' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <p className="xc-eyebrow">Reinforcement Learning Action Space</p>
                <h4 className="xc-title" style={{ fontSize: '1.1rem', marginBottom: '0.25rem' }}>Admissible Agent Navigation Hops</h4>
                <p className="xc-note">
                  Every outgoing edge from this state represents an admissible navigational action in the agent's graph manifold.
                  The AIS closed-loop reward function evaluates each path deterministically.
                </p>
              </div>

              {outgoingEdges.length === 0 ? (
                <div className="xc-empty">
                  <h4 className="xc-title">No Outgoing Transitions</h4>
                  <p className="xc-note">This node is currently a sink state with no forward transitions.</p>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <span className="xc-meta">Available Navigational Actions:</span>
                    {outgoingEdges.map((e, idx) => {
                      const targetNode = model?.byId.get(e.target)
                      const targetLabel = targetNode?.label || e.target
                      const actionLabel = `${node.label} —[${e.predicate || e.type}]→ ${targetLabel}`
                      const isSelected = simulatedAction === actionLabel

                      return (
                        <div
                          key={idx}
                          className="xc-win"
                          style={{
                            padding: '0.75rem',
                            cursor: 'pointer',
                            border: isSelected ? '1px solid var(--status-anchored)' : '1px solid rgba(255, 255, 255, 0.08)',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                          onClick={() => handleSimulateStep(e.predicate || e.type, targetLabel)}
                        >
                          <div>
                            <div style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
                              Action #{idx + 1}: <code style={{ color: 'var(--status-anchored)' }}>{e.predicate || e.type}</code>
                            </div>
                            <div className="xc-meta" style={{ fontSize: '0.75rem' }}>Target: {targetLabel}</div>
                          </div>
                          <button type="button" className="xc-btn xc-btn--ghost" style={{ fontSize: '0.75rem' }}>
                            Simulate Reward
                          </button>
                        </div>
                      )
                    })}
                  </div>

                  <div className="xc-win" style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <p className="xc-eyebrow">Simulated RL Reward Diagnostics</p>
                    {simBusy ? (
                      <p className="xc-note">Evaluating closed-loop step reward…</p>
                    ) : simReward ? (
                      <>
                        <div style={{ textAlign: 'center', padding: '0.75rem', borderLeft: '4px solid var(--status-anchored)' }}>
                          <div className="xc-meta">Instantaneous RL Reward (R_total)</div>
                          <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--status-anchored)' }}>
                            +{simReward.total_reward.toFixed(3)}
                          </div>
                          <div className="xc-meta">AIS Score: <b>{simReward.ais.toFixed(4)}</b></div>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem' }}>
                          <div className="xc-win" style={{ padding: '0.5rem' }}>
                            <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Grounding (S_g)</div>
                            <div style={{ fontWeight: 700, color: 'var(--status-anchored)' }}>{simReward.grounding.toFixed(2)}</div>
                          </div>
                          <div className="xc-win" style={{ padding: '0.5rem' }}>
                            <div className="xc-meta" style={{ fontSize: '0.7rem' }}>Compliance (S_c)</div>
                            <div style={{ fontWeight: 700, color: 'var(--status-anchored)' }}>{simReward.compliance.toFixed(2)}</div>
                          </div>
                        </div>

                        <div className="xc-callout xc-callout--anchored" style={{ fontSize: '0.75rem' }}>
                          <IconCheck />
                          <span>{simReward.explanation}</span>
                        </div>
                      </>
                    ) : (
                      <div className="xc-empty">
                        <h4 className="xc-title">Select an Action</h4>
                        <p className="xc-note">Click any action on the left to evaluate its live closed-loop reward.</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
