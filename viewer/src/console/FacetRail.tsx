// Left rail: what's loaded, and the facets that filter both lenses. Facets live in shared state,
// so toggling one in Graph is still toggled when you switch to Timeline.

import { useEffect, useMemo, useState } from 'react'
import { useConsole } from './state'
import { countFacets, EDGE_TYPE_LABEL, type EdgeGroup, type Facets, type NodeClass } from './model'

const CLASS_LABEL: Record<NodeClass, string> = {
  memory: 'Memories',
  entity: 'Entities',
  session: 'Sessions',
  exchange: 'Exchanges',
  merkle: 'Merkle roots',
}
const CLASS_SWATCH: Record<NodeClass, { background: string; ring?: boolean }> = {
  memory: { background: 'var(--cortex-accent)' },
  entity: { background: 'var(--ink-muted)' },
  session: { background: 'var(--status-anchored)' },
  exchange: { background: 'var(--ink-dim)' },
  merkle: { background: 'transparent', ring: true },
}
const EDGE_LABEL: Record<EdgeGroup, string> = {
  relation: 'Extracted relations',
  contradiction: 'Contradictions',
  similarity: 'Similarity',
  structure: 'Session structure',
}
const EDGE_RULE: Record<EdgeGroup, string> = {
  relation: '1px solid var(--cortex-accent)',
  contradiction: '2px dashed var(--status-review)',
  similarity: '1px dotted var(--status-anchored)',
  structure: '1px solid var(--hairline-strong)',
}

const titleCase = (value: string) => value.replace(/_/g, ' ')

export function FacetRail() {
  const { model, facets, setFacets, stats, similarity, setSimilarity, window: timeWindow, setWindow, loading, openPage } = useConsole()
  const counts = useMemo(() => (model ? countFacets(model) : null), [model])

  // the slider refetches the graph, so it commits after the user stops moving it
  const [pending, setPending] = useState(similarity)
  useEffect(() => setPending(similarity), [similarity])
  useEffect(() => {
    if (pending === similarity) return
    const timer = window.setTimeout(() => setSimilarity(pending), 400)
    return () => window.clearTimeout(timer)
  }, [pending, similarity, setSimilarity])

  const toggle = <K extends keyof Facets>(group: K, key: string) =>
    setFacets((prev) => {
      if (!prev) return prev
      const current = prev[group] as Record<string, boolean>
      return { ...prev, [group]: { ...current, [key]: !(current[key] ?? true) } }
    })

  return (
    <aside className="xc-win xc-pane xc-rail" aria-label="Facets">
      <div className="xc-scroll">
        <section className="xc-facet-group">
          <p className="xc-eyebrow">Projection</p>
          <dl className="xc-kv" style={{ marginTop: 10 }}>
            {/* the counts are the way into the lists behind them: each opens its drawer over this lens */}
            <div><dt><button type="button" className="xc-link xc-kv-link" aria-haspopup="dialog" onClick={() => openPage('memories')}>Memories</button></dt><dd title={stats?.memories == null ? 'The API did not count them' : undefined}>{stats?.memories == null ? '—' : stats.memories.toLocaleString()}</dd></div>
            <div><dt><button type="button" className="xc-link xc-kv-link" aria-haspopup="dialog" onClick={() => openPage('entities')}>Entities</button></dt><dd>{stats ? stats.entities.toLocaleString() : '—'}</dd></div>
            <div><dt>Relations</dt><dd>{stats ? stats.relations.toLocaleString() : '—'}</dd></div>
            <div><dt><button type="button" className="xc-link xc-kv-link" aria-haspopup="dialog" onClick={() => openPage('sessions')}>Sessions</button></dt><dd>{stats ? stats.sessions.toLocaleString() : '—'}</dd></div>
            <div><dt>In this sample</dt><dd>{model ? `${model.nodes.length} nodes` : loading ? '…' : '—'}</dd></div>
          </dl>
        </section>

        {model && facets && counts && (
          <>
            <section className="xc-facet-group">
              <p className="xc-eyebrow">Node class</p>
              {(Object.keys(CLASS_LABEL) as NodeClass[]).map((cls) => (
                <label className="xc-check" key={cls}>
                  <input type="checkbox" checked={facets.classes[cls]} onChange={() => toggle('classes', cls)} />
                  <i className={`xc-swatch${CLASS_SWATCH[cls].ring ? ' xc-swatch--ring' : ''}`} style={{ background: CLASS_SWATCH[cls].background }} />
                  <span>{CLASS_LABEL[cls]}</span>
                  <b>{counts.classes[cls]}</b>
                </label>
              ))}
            </section>

            {Object.keys(facets.statuses).length > 0 && (
              <section className="xc-facet-group">
                <p className="xc-eyebrow">Memory status</p>
                {Object.keys(facets.statuses).sort().map((status) => (
                  <label className="xc-check" key={status}>
                    <input type="checkbox" checked={facets.statuses[status]} onChange={() => toggle('statuses', status)} />
                    <span>{titleCase(status)}</span>
                    <b>{counts.statuses[status] ?? 0}</b>
                  </label>
                ))}
              </section>
            )}

            {Object.keys(facets.evidence).length > 0 && (
              <section className="xc-facet-group">
                <p className="xc-eyebrow">Evidence class</p>
                {Object.keys(facets.evidence).sort().map((evidence) => (
                  <label className="xc-check" key={evidence}>
                    <input type="checkbox" checked={facets.evidence[evidence]} onChange={() => toggle('evidence', evidence)} />
                    <span>{titleCase(evidence)}</span>
                    <b>{counts.evidence[evidence] ?? 0}</b>
                  </label>
                ))}
              </section>
            )}

            {Object.keys(facets.sources ?? {}).length > 0 && (
              <section className="xc-facet-group">
                <p className="xc-eyebrow">Memory source</p>
                {Object.keys(facets.sources).sort().map((source) => (
                  <label className="xc-check" key={source}>
                    <input type="checkbox" checked={facets.sources[source]} onChange={() => toggle('sources', source)} />
                    <span>{titleCase(source)}</span>
                    <b>{counts.sources[source] ?? 0}</b>
                  </label>
                ))}
              </section>
            )}

            <section className="xc-facet-group">
              <p className="xc-eyebrow">Edges</p>
              {(Object.keys(EDGE_LABEL) as EdgeGroup[]).map((group) => (
                <div key={group}>
                  <label className="xc-check">
                    <input type="checkbox" checked={facets.edges[group]} onChange={() => toggle('edges', group)} />
                    <i className="xc-rule" style={{ width: 16, height: 0, borderTop: EDGE_RULE[group], flexShrink: 0 }} />
                    <span>{EDGE_LABEL[group]}</span>
                    <b>{counts.edges[group]}</b>
                  </label>
                  {/* finer switches, indented under the group they refine; dimmed while the group is off */}
                  {group === 'structure' && Object.keys(facets.edgeTypes ?? {}).sort().map((type) => (
                    <label className="xc-check xc-check--sub" key={type} style={{ opacity: facets.edges.structure ? 1 : 0.45 }}>
                      <input type="checkbox" checked={facets.edgeTypes[type]} onChange={() => toggle('edgeTypes', type)} />
                      <span>{EDGE_TYPE_LABEL[type] ?? titleCase(type)}</span>
                      <b>{counts.edgeTypes[type] ?? 0}</b>
                    </label>
                  ))}
                  {group === 'relation' && Object.keys(facets.predicates ?? {}).sort().map((predicate) => (
                    <label className="xc-check xc-check--sub" key={predicate} style={{ opacity: facets.edges.relation ? 1 : 0.45 }}>
                      <input type="checkbox" checked={facets.predicates[predicate]} onChange={() => toggle('predicates', predicate)} />
                      <span>{titleCase(predicate)}</span>
                      <b>{counts.predicates[predicate] ?? 0}</b>
                    </label>
                  ))}
                </div>
              ))}
              <label className="xc-field" style={{ marginTop: 10 }}>
                <span style={{ display: 'flex', justifyContent: 'space-between' }}>
                  Similarity at least <b className="xc-meta" style={{ color: 'var(--ink)' }}>{pending.toFixed(2)}</b>
                </span>
                <input
                  className="xc-range"
                  type="range"
                  min={0.2}
                  max={0.99}
                  step={0.01}
                  value={pending}
                  onChange={(e) => setPending(Number(e.target.value))}
                  aria-label="Minimum similarity for similarity edges"
                />
              </label>
              <p className="xc-note" style={{ marginTop: 6 }}>Refetches the graph; the server computes similarity.</p>
            </section>

            {timeWindow && (
              <section className="xc-facet-group">
                <p className="xc-eyebrow">Time window</p>
                <p className="xc-note" style={{ margin: '8px 0 10px' }}>The chain rail is windowing both lenses.</p>
                <button type="button" className="xc-btn" onClick={() => setWindow(null)}>Clear window</button>
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  )
}
