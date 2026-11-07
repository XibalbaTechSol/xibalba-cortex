// GraphMathStudio.tsx: Formal Mathematics of Graphs Studio
// Computes and renders Adjacency Matrices, Cosine Similarity Manifolds,
// Graph Laplacians (Combinatorial & Normalized), Spectral Eigenvalue Distributions,
// Fiedler Vector Graph Partitioning, and Centrality Leaderboards.

import { useEffect, useState, useMemo } from 'react'
import { api, type GraphMathResult } from '../api'
import { IconCheck, IconClose } from './icons'

interface GraphMathStudioProps {
  onClose?: () => void
  onSelectNode?: (nodeId: string) => void
  agentId?: string
}

type MatrixTab = 'adjacency' | 'cosine' | 'laplacian' | 'norm_laplacian' | 'spectral' | 'centrality'

export function GraphMathStudio({ onClose, onSelectNode, agentId }: GraphMathStudioProps) {
  const [activeTab, setActiveTab] = useState<MatrixTab>('adjacency')
  const [mathData, setMathData] = useState<GraphMathResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterQuery, setFilterQuery] = useState('')
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null)

  useEffect(() => {
    let unmounted = false
    setLoading(true)
    setError(null)
    api.getGraphMath(100, 0.75, agentId)
      .then((res) => {
        if (!unmounted) {
          setMathData(res)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!unmounted) {
          setError(err?.message || 'Failed to compute formal graph mathematics')
          setLoading(false)
        }
      })
    return () => {
      unmounted = true
    }
  }, [agentId])

  // Filter labels and subset indices if user searches
  const filteredIndices = useMemo(() => {
    if (!mathData) return []
    if (!filterQuery.trim()) {
      return mathData.node_labels.map((_, i) => i).slice(0, 40) // cap to 40 for optimal matrix grid rendering
    }
    const q = filterQuery.toLowerCase()
    return mathData.node_labels
      .map((lab, i) => ({ lab, i }))
      .filter(({ lab }) => lab.toLowerCase().includes(q))
      .map(({ i }) => i)
      .slice(0, 40)
  }, [mathData, filterQuery])

  // Copy matrix in LaTeX or Python format
  const handleCopyMatrix = (matrix: number[][], name: string, format: 'python' | 'latex') => {
    if (!matrix || matrix.length === 0) return
    let text = ''
    if (format === 'python') {
      text = `import numpy as np\n\n${name} = np.array([\n`
      text += matrix.map((row) => '    [' + row.join(', ') + ']').join(',\n')
      text += '\n], dtype=float)\n'
    } else {
      text = `\\begin{pmatrix}\n`
      text += matrix.map((row) => '  ' + row.join(' & ')).join(' \\\\\n')
      text += '\n\\end{pmatrix}'
    }
    navigator.clipboard.writeText(text).then(() => {
      setCopiedFormat(format)
      setTimeout(() => setCopiedFormat(null), 2500)
    })
  }

  // Centrality rankings sorted by PageRank
  const centralityRows = useMemo(() => {
    if (!mathData?.centrality) return []
    const pr = mathData.centrality.pagerank || {}
    const deg = mathData.centrality.degree || {}
    const bet = mathData.centrality.betweenness || {}
    const cls = mathData.centrality.closeness || {}
    const eig = mathData.centrality.eigenvector || {}

    return mathData.node_labels.map((label, idx) => ({
      id: mathData.node_ids?.[idx] || label,
      label,
      pagerank: pr[label] ?? 0,
      degree: deg[label] ?? 0,
      betweenness: bet[label] ?? 0,
      closeness: cls[label] ?? 0,
      eigenvector: eig[label] ?? 0,
    })).sort((a, b) => b.pagerank - a.pagerank)
  }, [mathData])

  return (
    <div
      className="xc-deep-dive-overlay"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1400,
        backgroundColor: 'rgba(5, 8, 15, 0.88)',
        backdropFilter: 'blur(16px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        className="xc-modal xc-math-studio"
        style={{
          width: '94vw',
          maxWidth: 1200,
          maxHeight: '92vh',
          backgroundColor: 'var(--ground, #0b0f19)',
          border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.12))',
          borderRadius: 12,
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.75), 0 0 40px rgba(99, 102, 241, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          color: 'var(--ink, #f3f4f6)',
        }}
      >
        {/* Studio Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'linear-gradient(90deg, rgba(99, 102, 241, 0.1) 0%, transparent 60%)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 22 }}>📐</span>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em' }}>
                  Formal Mathematics of Graphs Studio
                </h2>
                <span
                  style={{
                    fontSize: 11,
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: 4,
                    background: 'rgba(99, 102, 241, 0.2)',
                    color: '#818cf8',
                    border: '1px solid rgba(99, 102, 241, 0.35)',
                  }}
                >
                  Spectral & Topological Manifold
                </span>
              </div>
              <p style={{ margin: '4px 0 0 0', fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                Adjacency matrix algebra, Cosine similarity tensors, Laplacian spectrum, and Graph Centrality metrics
              </p>
            </div>
          </div>
          {onClose && (
            <button
              type="button"
              className="xc-btn xc-btn--square"
              onClick={onClose}
              title="Close Math Studio (ESC)"
              style={{ width: 34, height: 34 }}
            >
              <IconClose />
            </button>
          )}
        </div>

        {/* Global Formal Metrics Bar */}
        {mathData && (
          <div
            style={{
              padding: '12px 24px',
              backgroundColor: 'rgba(255, 255, 255, 0.02)',
              borderBottom: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))',
              display: 'flex',
              gap: 20,
              flexWrap: 'wrap',
              fontSize: 12,
            }}
          >
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Order |V|: </span>
              <strong style={{ color: '#60a5fa' }}>{mathData.node_count} nodes</strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Size |E|: </span>
              <strong style={{ color: '#34d399' }}>{mathData.edge_count} edges</strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Density ρ: </span>
              <strong>{mathData.density.toFixed(4)}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Clustering C: </span>
              <strong>{mathData.clustering_coefficient.toFixed(4)}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Algebraic Conn λ₂: </span>
              <strong style={{ color: '#f59e0b' }}>
                {mathData.spectral.algebraic_connectivity.toFixed(4)}
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Spectral Gap: </span>
              <strong style={{ color: '#ec4899' }}>
                {mathData.spectral.spectral_gap.toFixed(4)}
              </strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Diameter: </span>
              <strong>{mathData.diameter ?? '—'}</strong>
            </div>
            <div>
              <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Avg Path Length: </span>
              <strong>{mathData.average_shortest_path_length?.toFixed(3) ?? '—'}</strong>
            </div>
          </div>
        )}

        {/* Tabs Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 24px',
            borderBottom: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))',
            backgroundColor: 'rgba(0, 0, 0, 0.25)',
          }}
        >
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'adjacency' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('adjacency')}
            >
              Adjacency Matrix (A)
            </button>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'cosine' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('cosine')}
            >
              Cosine Similarity (S_cos)
            </button>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'laplacian' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('laplacian')}
            >
              Laplacian (L = D - A)
            </button>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'norm_laplacian' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('norm_laplacian')}
            >
              Normalized Laplacian (L_sym)
            </button>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'spectral' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('spectral')}
            >
              Spectral Theory (λ_i)
            </button>
            <button
              type="button"
              className={`xc-btn ${activeTab === 'centrality' ? 'xc-btn--primary' : ''}`}
              onClick={() => setActiveTab('centrality')}
            >
              Centrality Leaderboard
            </button>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Filter nodes in matrix…"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className="xc-input"
              style={{ width: 190, height: 30, fontSize: 12 }}
            />
            {mathData && activeTab !== 'spectral' && activeTab !== 'centrality' && (
              <>
                <button
                  type="button"
                  className="xc-btn"
                  style={{ fontSize: 11, height: 30 }}
                  onClick={() => {
                    const mat = activeTab === 'adjacency' ? mathData.adjacency_matrix :
                                activeTab === 'cosine' ? mathData.cosine_similarity_matrix :
                                activeTab === 'laplacian' ? mathData.laplacian_matrix :
                                mathData.normalized_laplacian_matrix
                    handleCopyMatrix(mat, activeTab.toUpperCase(), 'python')
                  }}
                >
                  {copiedFormat === 'python' ? <><IconCheck style={{ width: 12, height: 12 }} /> Copied NumPy</> : 'Copy NumPy'}
                </button>
                <button
                  type="button"
                  className="xc-btn"
                  style={{ fontSize: 11, height: 30 }}
                  onClick={() => {
                    const mat = activeTab === 'adjacency' ? mathData.adjacency_matrix :
                                activeTab === 'cosine' ? mathData.cosine_similarity_matrix :
                                activeTab === 'laplacian' ? mathData.laplacian_matrix :
                                mathData.normalized_laplacian_matrix
                    handleCopyMatrix(mat, activeTab.toUpperCase(), 'latex')
                  }}
                >
                  {copiedFormat === 'latex' ? <><IconCheck style={{ width: 12, height: 12 }} /> Copied LaTeX</> : 'Copy LaTeX'}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Studio Content Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--ink-muted, #9ca3af)' }}>
              <div style={{ fontSize: 24, marginBottom: 12 }}>⚙️</div>
              <p>Computing graph spectra, adjacency manifolds, and topological invariants…</p>
            </div>
          )}

          {error && (
            <div style={{ padding: 18, backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 8, color: '#fca5a5' }}>
              <strong>Computation Error: </strong> {error}
            </div>
          )}

          {!loading && mathData && (
            <>
              {/* TAB 1: ADJACENCY MATRIX */}
              {activeTab === 'adjacency' && (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 15, fontWeight: 600 }}>
                      Adjacency Matrix A ∈ ℝⁿˣⁿ
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Formally: A_ij = w_ij if an edge directed from v_i to v_j exists with weight w_ij, else 0.
                    </p>
                  </div>
                  <MatrixGrid
                    matrix={mathData.adjacency_matrix}
                    labels={mathData.node_labels}
                    indices={filteredIndices}
                    onSelectNode={(lbl) => {
                      const idx = mathData.node_labels.indexOf(lbl)
                      if (idx >= 0 && onSelectNode) onSelectNode(mathData.node_ids[idx])
                    }}
                    mode="adjacency"
                  />
                </div>
              )}

              {/* TAB 2: COSINE SIMILARITY */}
              {activeTab === 'cosine' && (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 15, fontWeight: 600 }}>
                      Cosine Similarity Matrix S_cos ∈ [-1, 1]ⁿˣⁿ
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Formally: S_ij = (u_i · u_j) / (‖u_i‖₂ ‖u_j‖₂), computing directional alignment across embedding representations.
                    </p>
                  </div>
                  <MatrixGrid
                    matrix={mathData.cosine_similarity_matrix}
                    labels={mathData.node_labels}
                    indices={filteredIndices}
                    onSelectNode={(lbl) => {
                      const idx = mathData.node_labels.indexOf(lbl)
                      if (idx >= 0 && onSelectNode) onSelectNode(mathData.node_ids[idx])
                    }}
                    mode="cosine"
                  />
                </div>
              )}

              {/* TAB 3: LAPLACIAN */}
              {activeTab === 'laplacian' && (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 15, fontWeight: 600 }}>
                      Combinatorial Graph Laplacian L = D - A ∈ ℝⁿˣⁿ
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Formally: Positive semi-definite operator governing diffusion, heat kernel dynamics, and random walks across graph topology.
                    </p>
                  </div>
                  <MatrixGrid
                    matrix={mathData.laplacian_matrix}
                    labels={mathData.node_labels}
                    indices={filteredIndices}
                    onSelectNode={(lbl) => {
                      const idx = mathData.node_labels.indexOf(lbl)
                      if (idx >= 0 && onSelectNode) onSelectNode(mathData.node_ids[idx])
                    }}
                    mode="laplacian"
                  />
                </div>
              )}

              {/* TAB 4: NORMALIZED LAPLACIAN */}
              {activeTab === 'norm_laplacian' && (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 15, fontWeight: 600 }}>
                      Normalized Symmetric Laplacian L_sym = D⁻¹/² L D⁻¹/²
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Formally: L_sym = I - D⁻¹/² A D⁻¹/², eigenvalues bounded in [0, 2], invariant under degree re-scaling.
                    </p>
                  </div>
                  <MatrixGrid
                    matrix={mathData.normalized_laplacian_matrix}
                    labels={mathData.node_labels}
                    indices={filteredIndices}
                    onSelectNode={(lbl) => {
                      const idx = mathData.node_labels.indexOf(lbl)
                      if (idx >= 0 && onSelectNode) onSelectNode(mathData.node_ids[idx])
                    }}
                    mode="norm_laplacian"
                  />
                </div>
              )}

              {/* TAB 5: SPECTRAL GRAPH THEORY */}
              {activeTab === 'spectral' && (
                <div>
                  <div style={{ marginBottom: 20 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 16, fontWeight: 600 }}>
                      Spectral Decomposition & Laplacian Eigenvalues
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Eigenvalues λ₀ ≤ λ₁ ≤ … ≤ λₙ₋₁ characterize the topological connectivity, bottlenecks, and expansion properties of the graph.
                    </p>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 24 }}>
                    <div style={{ padding: 18, backgroundColor: 'rgba(255, 255, 255, 0.02)', borderRadius: 8, border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))' }}>
                      <h4 style={{ margin: '0 0 10px 0', fontSize: 13, color: 'var(--ink-muted, #9ca3af)', textTransform: 'uppercase' }}>
                        Fiedler Value (Algebraic Connectivity λ₂)
                      </h4>
                      <div style={{ fontSize: 32, fontWeight: 800, color: '#f59e0b', letterSpacing: '-0.02em' }}>
                        {mathData.spectral.algebraic_connectivity.toFixed(6)}
                      </div>
                      <p style={{ margin: '8px 0 0 0', fontSize: 12, color: 'var(--ink-muted, #9ca3af)' }}>
                        λ₂ &gt; 0 proves the graph is connected. Higher values quantify robust multi-path connectivity against edge failures.
                      </p>
                    </div>

                    <div style={{ padding: 18, backgroundColor: 'rgba(255, 255, 255, 0.02)', borderRadius: 8, border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))' }}>
                      <h4 style={{ margin: '0 0 10px 0', fontSize: 13, color: 'var(--ink-muted, #9ca3af)', textTransform: 'uppercase' }}>
                        Spectral Gap (λₘₐₓ - λ₂)
                      </h4>
                      <div style={{ fontSize: 32, fontWeight: 800, color: '#ec4899', letterSpacing: '-0.02em' }}>
                        {mathData.spectral.spectral_gap.toFixed(6)}
                      </div>
                      <p style={{ margin: '8px 0 0 0', fontSize: 12, color: 'var(--ink-muted, #9ca3af)' }}>
                        Determines the mixing rate of random walks and information propagation speed across the knowledge graph.
                      </p>
                    </div>
                  </div>

                  {/* Eigenvalues Chart */}
                  <div style={{ marginBottom: 24 }}>
                    <h4 style={{ margin: '0 0 12px 0', fontSize: 14, fontWeight: 600 }}>
                      Eigenvalue Spectrum Histogram
                    </h4>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 160, padding: '16px 12px 0 12px', backgroundColor: 'rgba(0, 0, 0, 0.3)', borderRadius: 8, border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))' }}>
                      {mathData.spectral.eigenvalues.slice(0, 24).map((val, idx) => {
                        const maxVal = Math.max(...mathData.spectral.eigenvalues, 1.0)
                        const heightPct = Math.max(4, (val / maxVal) * 100)
                        const isFiedler = idx === 1
                        return (
                          <div key={idx} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-end' }}>
                            <div
                              style={{
                                width: '100%',
                                height: `${heightPct}%`,
                                backgroundColor: isFiedler ? '#f59e0b' : idx === 0 ? '#60a5fa' : '#6366f1',
                                borderRadius: '3px 3px 0 0',
                                transition: 'height 0.3s ease',
                              }}
                              title={`λ_${idx} = ${val.toFixed(4)}${isFiedler ? ' (Fiedler Value)' : ''}`}
                            />
                            <span style={{ fontSize: 9, marginTop: 4, color: 'var(--ink-muted, #9ca3af)' }}>
                              λ_{idx}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 6: CENTRALITY LEADERBOARD */}
              {activeTab === 'centrality' && (
                <div>
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: 15, fontWeight: 600 }}>
                      Graph Centrality Leaderboard
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted, #9ca3af)' }}>
                      Comparative ranking of nodes across PageRank, Degree, Betweenness, Closeness, and Principal Eigenvector metrics.
                    </p>
                  </div>

                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.12))', textAlign: 'left', color: 'var(--ink-muted, #9ca3af)' }}>
                          <th style={{ padding: '8px 12px' }}>Rank</th>
                          <th style={{ padding: '8px 12px' }}>Entity / Node</th>
                          <th style={{ padding: '8px 12px' }}>PageRank (PR)</th>
                          <th style={{ padding: '8px 12px' }}>Degree Cent</th>
                          <th style={{ padding: '8px 12px' }}>Betweenness</th>
                          <th style={{ padding: '8px 12px' }}>Closeness</th>
                          <th style={{ padding: '8px 12px' }}>Eigenvector</th>
                        </tr>
                      </thead>
                      <tbody>
                        {centralityRows.map((row, idx) => (
                          <tr
                            key={row.id}
                            style={{
                              borderBottom: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.05))',
                              backgroundColor: idx % 2 === 0 ? 'rgba(255, 255, 255, 0.01)' : 'transparent',
                            }}
                          >
                            <td style={{ padding: '8px 12px', fontWeight: 700, color: 'var(--ink-muted, #9ca3af)' }}>
                              #{idx + 1}
                            </td>
                            <td style={{ padding: '8px 12px' }}>
                              <button
                                type="button"
                                className="xc-link"
                                onClick={() => onSelectNode?.(row.id)}
                                style={{ fontWeight: 600, color: 'var(--ink, #f3f4f6)', textAlign: 'left' }}
                              >
                                {row.label}
                              </button>
                            </td>
                            <td style={{ padding: '8px 12px', color: '#60a5fa', fontWeight: 600 }}>
                              {row.pagerank.toFixed(5)}
                            </td>
                            <td style={{ padding: '8px 12px' }}>{row.degree.toFixed(4)}</td>
                            <td style={{ padding: '8px 12px' }}>{row.betweenness.toFixed(5)}</td>
                            <td style={{ padding: '8px 12px' }}>{row.closeness.toFixed(5)}</td>
                            <td style={{ padding: '8px 12px', color: '#a78bfa' }}>{row.eigenvector.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// Reusable Matrix Heatmap Grid Component
interface MatrixGridProps {
  matrix: number[][]
  labels: string[]
  indices: number[]
  onSelectNode: (label: string) => void
  mode: 'adjacency' | 'cosine' | 'laplacian' | 'norm_laplacian'
}

function MatrixGrid({ matrix, labels, indices, onSelectNode, mode }: MatrixGridProps) {
  const [hoveredCell, setHoveredCell] = useState<{ r: number; c: number; val: number } | null>(null)

  if (!matrix || matrix.length === 0 || indices.length === 0) {
    return <p style={{ color: 'var(--ink-muted, #9ca3af)' }}>No matrix data available.</p>
  }

  // Get color for matrix cell
  const getCellColor = (val: number): string => {
    if (mode === 'cosine') {
      if (val > 0.8) return 'rgba(16, 185, 129, 0.85)'
      if (val > 0.4) return 'rgba(16, 185, 129, 0.45)'
      if (val > 0.05) return 'rgba(16, 185, 129, 0.2)'
      if (val < -0.3) return 'rgba(59, 130, 246, 0.6)'
      if (val < -0.05) return 'rgba(59, 130, 246, 0.25)'
      return 'rgba(255, 255, 255, 0.04)'
    }
    if (mode === 'adjacency') {
      if (val >= 1.0) return 'rgba(99, 102, 241, 0.85)'
      if (val > 0.0) return 'rgba(99, 102, 241, 0.45)'
      return 'rgba(255, 255, 255, 0.03)'
    }
    // Laplacian
    if (val > 0) return 'rgba(245, 158, 11, 0.65)'
    if (val < 0) return 'rgba(236, 72, 153, 0.65)'
    return 'rgba(255, 255, 255, 0.03)'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {hoveredCell && (
        <div
          style={{
            padding: '6px 12px',
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.15))',
            borderRadius: 6,
            fontSize: 12,
            display: 'inline-flex',
            gap: 12,
            alignSelf: 'flex-start',
          }}
        >
          <span>
            <strong>Row (i):</strong> {labels[hoveredCell.r]}
          </span>
          <span>
            <strong>Col (j):</strong> {labels[hoveredCell.c]}
          </span>
          <span style={{ color: '#60a5fa' }}>
            <strong>M_{hoveredCell.r},{hoveredCell.c}:</strong> {hoveredCell.val.toFixed(4)}
          </span>
        </div>
      )}

      <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: '55vh', border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.1))', borderRadius: 8 }}>
        <table style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th style={{ width: 140, minWidth: 140, padding: 6, fontSize: 11, color: 'var(--ink-muted, #9ca3af)', textAlign: 'right', borderBottom: '1px solid rgba(255, 255, 255, 0.1)', position: 'sticky', top: 0, left: 0, zIndex: 10, backgroundColor: 'var(--ground, #0b0f19)' }}>
                i \ j
              </th>
              {indices.map((cIdx) => (
                <th
                  key={cIdx}
                  style={{
                    width: 32,
                    minWidth: 32,
                    height: 120,
                    padding: 0,
                    verticalAlign: 'bottom',
                    fontSize: 10,
                    position: 'sticky',
                    top: 0,
                    zIndex: 5,
                    backgroundColor: 'var(--ground, #0b0f19)',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
                  }}
                >
                  <div
                    style={{
                      writingMode: 'vertical-rl',
                      transform: 'rotate(180deg)',
                      whiteSpace: 'nowrap',
                      textOverflow: 'ellipsis',
                      overflow: 'hidden',
                      maxHeight: 110,
                      padding: '4px 2px',
                      color: 'var(--ink-muted, #9ca3af)',
                    }}
                    title={labels[cIdx]}
                  >
                    {labels[cIdx]}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {indices.map((rIdx) => (
              <tr key={rIdx}>
                <th
                  style={{
                    padding: '4px 8px',
                    fontSize: 11,
                    textAlign: 'right',
                    whiteSpace: 'nowrap',
                    textOverflow: 'ellipsis',
                    overflow: 'hidden',
                    maxWidth: 140,
                    position: 'sticky',
                    left: 0,
                    zIndex: 4,
                    backgroundColor: 'var(--ground, #0b0f19)',
                    borderRight: '1px solid rgba(255, 255, 255, 0.1)',
                  }}
                  title={labels[rIdx]}
                >
                  <button
                    type="button"
                    className="xc-link"
                    onClick={() => onSelectNode(labels[rIdx])}
                    style={{ fontSize: 11, color: 'var(--ink, #f3f4f6)' }}
                  >
                    {labels[rIdx]}
                  </button>
                </th>
                {indices.map((cIdx) => {
                  const val = matrix[rIdx]?.[cIdx] ?? 0
                  return (
                    <td
                      key={cIdx}
                      onMouseEnter={() => setHoveredCell({ r: rIdx, c: cIdx, val })}
                      onMouseLeave={() => setHoveredCell(null)}
                      style={{
                        width: 32,
                        height: 24,
                        padding: 0,
                        backgroundColor: getCellColor(val),
                        border: '1px solid rgba(255, 255, 255, 0.03)',
                        cursor: 'crosshair',
                        textAlign: 'center',
                        fontSize: 9,
                        color: Math.abs(val) > 0.01 ? '#fff' : 'rgba(255, 255, 255, 0.1)',
                      }}
                      title={`${labels[rIdx]} → ${labels[cIdx]}: ${val.toFixed(4)}`}
                    >
                      {Math.abs(val) > 0.05 ? (val >= 1 ? val.toFixed(0) : val.toFixed(1)) : ''}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
