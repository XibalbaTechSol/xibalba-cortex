// InnerRoomCockpit: Multi-modal Holo-Cockpit for inside-node sanctum exploration.
// Features novel representations of High-D embedding tensors (starburst quivers),
// scalar physical monoliths (centrality obelisk, AIS gyroscope, Dirichlet ripple pool),
// and directional spatial relation portals with instant room-to-room teleportation.

import { useMemo, useState } from 'react'
import type { CNode, GraphModel } from './model'
import {
  computeDirichletEnergyEstimate,
  computeQuantileTier,
  generateLatentQuivers,
} from './zenControls'

interface InnerRoomCockpitProps {
  node: CNode
  model: GraphModel | null
  onAscend: () => void
  onAimTarget: (target: 'center' | 'obelisk' | 'gyro' | 'portal') => void
  onWarpToNode: (targetNodeId: string) => void
}

type RoomTab = 'chamber' | 'vectors' | 'scalars' | 'portals'

export function InnerRoomCockpit({
  node,
  model,
  onAscend,
  onAimTarget,
  onWarpToNode,
}: InnerRoomCockpitProps) {
  const [activeTab, setActiveTab] = useState<RoomTab>('chamber')

  // Incident edges & neighbor nodes
  const allEdges = useMemo(() => {
    if (!model) return []
    return model.edges.filter((e) => e.source === node.id || e.target === node.id)
  }, [model, node.id])

  const totalNodes = model ? model.nodes.length : 1
  const neighborDegrees = useMemo(() => {
    if (!model) return []
    const nIds = new Set(allEdges.map((e) => (e.source === node.id ? e.target : e.source)))
    return model.nodes.filter((n) => nIds.has(n.id)).map((n) => n.degree)
  }, [allEdges, model, node.id])

  // Novel Scalar Projections
  const centralityTier = useMemo(() => computeQuantileTier(node.degree, totalNodes), [node.degree, totalNodes])
  const dirichletEnergy = useMemo(() => computeDirichletEnergyEstimate(node.degree, neighborDegrees), [node.degree, neighborDegrees])

  // Novel Vector Projections: 16-D Latent Tensor Quivers
  const quivers = useMemo(() => generateLatentQuivers(node.id, 16), [node.id])

  // AIS State
  const aisState = node.valid === false ? 'CONFLICT' : node.status === 'candidate' ? 'CANDIDATE' : 'ANCHORED'

  return (
    <div className="xc-room-cockpit" role="region" aria-label="Inner Sanctum Node Room Cockpit">
      {/* Top Cockpit Header Strip */}
      <div className="xc-room-header">
        <div className="xc-room-title-group">
          <span className="xc-room-emblem" aria-hidden="true">🏛️</span>
          <div>
            <div className="xc-room-pretitle">INNER WORLD SANCTUM · NODE CHAMBER</div>
            <div className="xc-room-node-name">
              <span className="xc-room-cls-badge">[{node.cls.toUpperCase()}]</span>
              <span>{node.label}</span>
              <span className={`xc-room-status-badge xc-room-status-badge--${aisState.toLowerCase()}`}>
                {aisState}
              </span>
            </div>
          </div>
        </div>

        {/* Telemetry Quick Badges */}
        <div className="xc-room-metrics-strip">
          <div className="xc-room-metric-pill" title="Total incident relations manifested as dimensional perimeter portals">
            <span className="xc-room-metric-k">Portals:</span>
            <span className="xc-room-metric-v">{allEdges.length} Gateways</span>
          </div>
          <div className="xc-room-metric-pill" title="Normalized degree centrality visualized as stepped physical obelisk">
            <span className="xc-room-metric-k">Centrality:</span>
            <span className="xc-room-metric-v">{centralityTier.quantileName} Tier ({node.degree} deg)</span>
          </div>
          <div className="xc-room-metric-pill" title="Latent embedding tensor dimensions">
            <span className="xc-room-metric-k">Tensor:</span>
            <span className="xc-room-metric-v">16-D Starburst</span>
          </div>
        </div>

        {/* Ascend / Exit Button */}
        <button
          type="button"
          className="xc-room-ascend-btn"
          onClick={onAscend}
          title="Ascend through ceiling oculus back to global graph orbit (ESC)"
        >
          🚀 Ascend to Global Orbit (ESC)
        </button>
      </div>

      {/* Multi-modal Tabs Bar */}
      <div className="xc-room-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'chamber'}
          className={`xc-room-tab ${activeTab === 'chamber' ? 'xc-room-tab--active' : ''}`}
          onClick={() => setActiveTab('chamber')}
        >
          🌌 3D Sanctum Chamber
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'vectors'}
          className={`xc-room-tab ${activeTab === 'vectors' ? 'xc-room-tab--active' : ''}`}
          onClick={() => setActiveTab('vectors')}
        >
          ✨ Vectors & Latent Tensors
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'scalars'}
          className={`xc-room-tab ${activeTab === 'scalars' ? 'xc-room-tab--active' : ''}`}
          onClick={() => setActiveTab('scalars')}
        >
          🏛️ Scalar Monoliths
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'portals'}
          className={`xc-room-tab ${activeTab === 'portals' ? 'xc-room-tab--active' : ''}`}
          onClick={() => setActiveTab('portals')}
        >
          🚪 Spatial Portals (SPO Gateways · {allEdges.length})
        </button>
      </div>

      {/* Tab Panels */}
      <div className="xc-room-tab-body">
        {/* Tab 1: Chamber Overview & Camera Quick-Look */}
        {activeTab === 'chamber' && (
          <div className="xc-room-panel">
            <div className="xc-room-section-header">
              <span>CHAMBER CAMERA DIRECTIVES & ARCHITECTURE</span>
            </div>
            <p className="xc-room-desc">
              You are inside the inner world of <strong>{node.label}</strong>. Orbit around using mouse or arrow keys.
              Use the directive buttons below to aim your camera at specific physical monuments inside the room:
            </p>
            <div className="xc-room-aim-grid">
              <button
                type="button"
                className="xc-room-aim-btn"
                onClick={() => onAimTarget('center')}
                title="Aim camera at central high-dimensional embedding tensor starburst"
              >
                🎯 Aim Center Core (Tensor Starburst)
              </button>
              <button
                type="button"
                className="xc-room-aim-btn"
                onClick={() => onAimTarget('obelisk')}
                title="Aim camera at East stepped degree centrality obelisk"
              >
                🏛️ Aim East (Degree Obelisk)
              </button>
              <button
                type="button"
                className="xc-room-aim-btn"
                onClick={() => onAimTarget('gyro')}
                title="Aim camera at West anti-gravity AIS grounding gyroscope"
              >
                🧭 Aim West (AIS Gyroscope)
              </button>
              <button
                type="button"
                className="xc-room-aim-btn"
                onClick={() => onAimTarget('portal')}
                title="Aim camera at perimeter spatial relation gateways"
              >
                🚪 Aim Perimeter (Relation Portals)
              </button>
            </div>

            <div className="xc-room-arch-specs">
              <div className="xc-room-spec-card">
                <span className="xc-room-spec-title">Sanctum Geometry</span>
                <span className="xc-room-spec-val">Octagonal Dark Obsidian Chamber (Radius: 36m)</span>
              </div>
              <div className="xc-room-spec-card">
                <span className="xc-room-spec-title">Perimeter Colonnes</span>
                <span className="xc-room-spec-val">8 Hexagonal Crystalline Pillars with Beacon Caps</span>
              </div>
              <div className="xc-room-spec-card">
                <span className="xc-room-spec-title">Sky Aperture</span>
                <span className="xc-room-spec-val">Open Oculus to Global Graph Constellation Overhead</span>
              </div>
              <div className="xc-room-spec-card">
                <span className="xc-room-spec-title">Energy Conduit</span>
                <span className="xc-room-spec-val">Ascending Cosmic Laser Shaft + Floor Radial Conduits</span>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Novel Vector Representation */}
        {activeTab === 'vectors' && (
          <div className="xc-room-panel">
            <div className="xc-room-section-header">
              <span>NOVEL VECTOR REPRESENTATION: HIGH-DIMENSIONAL EMBEDDING TENSOR STARBURST</span>
            </div>
            <p className="xc-room-desc">
              High-dimensional latent embeddings $\vec&#123;v&#125; \in \mathbb&#123;R&#125;^&#123;16&#125;$ are physically manifested in 3D
              as the central floating polyhedral <strong>Tensor Starburst</strong>. Each latent component radiates outward in spherical
              coordinates, with length proportional to magnitude $|\vec&#123;v&#125;_k|$ and color-coded by polarity:
              <span style={{ color: '#06b6d4', fontWeight: 600, marginLeft: 6 }}>Electric Cyan (+)</span> vs
              <span style={{ color: '#f59e0b', fontWeight: 600, marginLeft: 6 }}>Radiant Amber (−)</span>.
            </p>

            <div className="xc-room-vector-grid">
              {quivers.map((q) => (
                <div key={q.index} className="xc-room-quiver-card">
                  <div className="xc-room-quiver-header">
                    <span className="xc-room-quiver-idx">dim d_{q.index}</span>
                    <span className={`xc-room-quiver-polarity xc-room-quiver-polarity--${q.polarity}`}>
                      {q.polarity === 'positive' ? '+ Pos' : '− Neg'}
                    </span>
                  </div>
                  <div className="xc-room-quiver-bar-track">
                    <div
                      className="xc-room-quiver-bar-fill"
                      style={{
                        width: `${Math.round(q.magnitude * 100)}%`,
                        backgroundColor: q.polarity === 'positive' ? '#06b6d4' : '#f59e0b',
                      }}
                    />
                  </div>
                  <div className="xc-room-quiver-meta">
                    <span>Val: {q.value.toFixed(3)}</span>
                    <span>Spherical: ({q.dir.x.toFixed(2)}, {q.dir.y.toFixed(2)}, {q.dir.z.toFixed(2)})</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab 3: Novel Scalar Representation */}
        {activeTab === 'scalars' && (
          <div className="xc-room-panel">
            <div className="xc-room-section-header">
              <span>NOVEL SCALAR REPRESENTATION: PHYSICAL ARCHITECTURAL MONOLITHS</span>
            </div>
            <p className="xc-room-desc">
              Scalars are embodied as tangible monuments inside the room rather than flat numbers on a screen:
            </p>

            <div className="xc-room-monoliths-grid">
              {/* Monolith 1: Centrality Obelisk */}
              <div className="xc-room-monolith-card">
                <div className="xc-room-monolith-header">
                  <span className="xc-room-monolith-icon">🏛️</span>
                  <div>
                    <span className="xc-room-monolith-name">Degree Centrality Obelisk</span>
                    <span className="xc-room-monolith-sub">Tiered Stepped Monument (East Quadrant)</span>
                  </div>
                </div>
                <div className="xc-room-monolith-body">
                  <div className="xc-room-stat-row">
                    <span>Node Degree:</span>
                    <strong>{node.degree} edges</strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Quantile Classification:</span>
                    <strong style={{ color: 'var(--accent)' }}>{centralityTier.label}</strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Physical Monument Height:</span>
                    <strong>{centralityTier.height.toFixed(1)}m (4-Tier Steps)</strong>
                  </div>
                </div>
              </div>

              {/* Monolith 2: AIS Gyroscope */}
              <div className="xc-room-monolith-card">
                <div className="xc-room-monolith-header">
                  <span className="xc-room-monolith-icon">🧭</span>
                  <div>
                    <span className="xc-room-monolith-name">AIS Grounding Gyroscope</span>
                    <span className="xc-room-monolith-sub">Anti-Gravity Gimbal Apparatus (West Quadrant)</span>
                  </div>
                </div>
                <div className="xc-room-monolith-body">
                  <div className="xc-room-stat-row">
                    <span>Integrity Status:</span>
                    <strong style={{ color: aisState === 'ANCHORED' ? '#10b981' : aisState === 'CONFLICT' ? '#ef4444' : '#6366f1' }}>
                      {aisState}
                    </strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Gimbal Rings:</span>
                    <strong>Dual Concentric Orthogonal Rotors</strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Merkle Core:</span>
                    <strong>Cryptographic Seed Sphere</strong>
                  </div>
                </div>
              </div>

              {/* Monolith 3: Dirichlet Energy Pool */}
              <div className="xc-room-monolith-card">
                <div className="xc-room-monolith-header">
                  <span className="xc-room-monolith-icon">🌊</span>
                  <div>
                    <span className="xc-room-monolith-name">Dirichlet Topological Energy Pool</span>
                    <span className="xc-room-monolith-sub">Concentric Harmonic Ripple Disc (Floor Center)</span>
                  </div>
                </div>
                <div className="xc-room-monolith-body">
                  <div className="xc-room-stat-row">
                    <span>Dirichlet Energy E(f):</span>
                    <strong>{dirichletEnergy}</strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Topological Harmonicity:</span>
                    <strong style={{ color: '#06b6d4' }}>
                      {dirichletEnergy < 0.2 ? 'Smooth Manifold' : 'High Gradient'}
                    </strong>
                  </div>
                  <div className="xc-room-stat-row">
                    <span>Waveform Animation:</span>
                    <strong>Continuous Harmonic Pulsing in RAF</strong>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 4: Spatial Portals & Room-to-Room Teleportation */}
        {activeTab === 'portals' && (
          <div className="xc-room-panel">
            <div className="xc-room-section-header">
              <span>DIRECTIONAL SPATIAL PORTALS (SPO GATEWAYS & TELEPORTATION)</span>
            </div>
            <p className="xc-room-desc">
              Every relation $(S, P, O)$ connected to this node is erected as an <strong>Arched Dimensional Portal Gateway</strong> along
              the perimeter walls. Click <strong>Warp to Room</strong> on any portal to teleport directly into that neighbor's inner sanctum chamber!
            </p>

            {allEdges.length === 0 ? (
              <div className="xc-room-empty">No external relation portals connected to this node.</div>
            ) : (
              <div className="xc-room-portals-grid">
                {allEdges.map((e) => {
                  const isOutgoing = e.source === node.id
                  const neighborId = isOutgoing ? e.target : e.source
                  const neighborNode = model ? model.nodes.find((n) => n.id === neighborId) : null
                  const neighborLabel = neighborNode ? neighborNode.label : neighborId
                  const pred = e.predicate || e.type || e.group

                  return (
                    <div key={e.id} className="xc-room-portal-card">
                      <div className="xc-room-portal-top">
                        <span className={`xc-room-portal-dir xc-room-portal-dir--${isOutgoing ? 'out' : 'in'}`}>
                          {isOutgoing ? 'OUTGOING →' : '← INCOMING'}
                        </span>
                        <span className="xc-room-portal-pred">{pred}</span>
                      </div>
                      <div className="xc-room-portal-target">
                        <span className="xc-room-portal-lbl" title={neighborLabel}>
                          {neighborLabel}
                        </span>
                      </div>
                      <div className="xc-room-portal-footer">
                        <span className="xc-room-portal-sim">
                          {e.similarity ? `sim: ${Number(e.similarity).toFixed(2)}` : `group: ${e.group}`}
                        </span>
                        <button
                          type="button"
                          className="xc-room-warp-btn"
                          onClick={() => onWarpToNode(neighborId)}
                          title={`Teleport camera through dimensional gateway into ${neighborLabel}'s room`}
                        >
                          ⚡ Warp to Room
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
