import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

type GraphNode = { id: string; type: string; label: string; status?: string; created_at?: string; observed_at?: string | null; session_id?: string | null }
type GraphEdge = { source: string; target: string; type: string; predicate?: string }
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] }
type Session = { external_session_id: string; started_at: string; ended_at?: string | null; active?: boolean }
type TimelineData = { sessions: Session[]; nodes: GraphNode[] }

async function read<T>(path: string): Promise<T> {
  const response = await fetch('/api/managed/' + path, { credentials: 'same-origin' })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || 'Request failed (' + response.status + ')')
  return data as T
}

export function ManagedGraphLens({ onBack }: { onBack: () => void }) {
  const host = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(720)
  const [data, setData] = useState<GraphData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const element = host.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setWidth(Math.max(320, Math.floor(element.clientWidth))))
    observer.observe(element)
    setWidth(Math.max(320, Math.floor(element.clientWidth)))
    return () => observer.disconnect()
  }, [])
  useEffect(() => { read<GraphData>('graph?limit=700').then(setData).catch((e: Error) => setError(e.message)) }, [])
  return <section className="xc-managed-lens" aria-label="Managed Graph">
    <header className="xc-managed-lens-head"><div><p className="xc-eyebrow">Explore</p><h2 className="xc-title">Graph</h2><p className="xc-note">Memories, entities, sessions and their verified relationships.</p></div><button className="xc-btn" onClick={onBack}>Back to workspace</button></header>
    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
    {!data && !error && <p className="xc-note">Loading graph…</p>}
    {data && <div ref={host} className="xc-managed-graph" aria-label="Managed memory graph">
      {data.nodes.length === 0 ? <div className="xc-empty"><h3 className="xc-title">No graph data yet</h3><p>Connect an agent and let it write a memory first.</p></div> : <ForceGraph2D width={width} height={620} graphData={{ nodes: data.nodes, links: data.edges }} nodeLabel={(node) => node.type + ': ' + node.label} nodeAutoColorBy="type" linkDirectionalArrowLength={3} linkDirectionalArrowRelPos={1} linkLabel={(link) => link.predicate || link.type} cooldownTicks={120} />}
    </div>}
  </section>
}

export function ManagedTimelineLens({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<TimelineData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { read<TimelineData>('timeline?limit=700').then(setData).catch((e: Error) => setError(e.message)) }, [])
  const timed = useMemo(() => (data?.nodes ?? []).filter((node) => node.type === 'memory' || node.type === 'exchange').map((node) => ({ node, time: Date.parse(node.observed_at || node.created_at || '') })).filter((item) => Number.isFinite(item.time)), [data])
  const domain = useMemo(() => { const values = timed.map((item) => item.time); if (!values.length) return null; const from = Math.min(...values); const to = Math.max(Date.now(), ...values); return { from, to: Math.max(from + 3600000, to) } }, [timed])
  const sessions = data?.sessions ?? []
  return <section className="xc-managed-lens" aria-label="Managed Timeline">
    <header className="xc-managed-lens-head"><div><p className="xc-eyebrow">Explore</p><h2 className="xc-title">Timeline</h2><p className="xc-note">Click a mark to inspect when an agent recorded it.</p></div><button className="xc-btn" onClick={onBack}>Back to workspace</button></header>
    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
    {!data && !error && <p className="xc-note">Loading timeline…</p>}
    {data && !domain && <div className="xc-empty"><h3 className="xc-title">No timed activity yet</h3><p>Sessions and memories will appear here after your agents connect.</p></div>}
    {data && domain && <div className="xc-managed-timeline" role="table" aria-label="Managed activity timeline">
      <div className="xc-managed-time-axis"><span>{new Date(domain.from).toLocaleString()}</span><span>{new Date(domain.to).toLocaleString()}</span></div>
      {(sessions.length ? sessions : [{ external_session_id: 'unassigned', started_at: new Date(domain.from).toISOString(), ended_at: null }]).map((session) => {
        const marks = timed.filter((item) => item.node.session_id === session.external_session_id || (session.external_session_id === 'unassigned' && !item.node.session_id))
        return <div className="xc-managed-lane" key={session.external_session_id} role="row"><div className="xc-managed-lane-label"><b>{session.external_session_id.slice(0, 18)}</b><span>{marks.length} event{marks.length === 1 ? '' : 's'}</span></div><div className="xc-managed-lane-track">{marks.map((item) => <button key={item.node.id} className="xc-managed-mark" style={{ left: ((item.time - domain.from) / (domain.to - domain.from)) * 100 + '%' }} title={item.node.label} aria-label={item.node.label}>{item.node.type === 'memory' ? 'M' : 'E'}</button>)}</div></div>
      })}
    </div>}
  </section>
}
