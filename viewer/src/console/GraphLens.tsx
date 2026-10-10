// Graph lens: the knowledge graph on a force layout, square nodes, one legend.
//
// Layout stability: react-force-graph mutates the node objects it is given (x, y, vx, vy). We keep
// ONE object per node id for the life of the component and hand it back on every filter change, so
// toggling a facet or moving the time window re-heats the simulation from where the nodes already
// are instead of scattering them.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { forceX, forceY } from 'd3-force'
import { useConsole } from './state'
import { useSettings } from './settingsContext'
import { Graph3D, type Graph3DHandle } from './Graph3D'
import { FADE, LINK_ALPHA, linkWidth, nodeHalf } from './graphStyle'
import { defaultFacets, filterModel, type CNode, type EdgeGroup, type NodeClass } from './model'
import { palette, withAlpha } from './palette'
import { IconFit } from './icons'

interface FGNode {
  id: string
  cls: NodeClass
  label: string
  status?: string
  valid?: boolean
  degree: number
  x?: number
  y?: number
  vx?: number
  vy?: number
}
interface FGLink {
  source: string | FGNode
  target: string | FGNode
  group: EdgeGroup
  similarity?: number
}

/** Half-extent of the drawn square, in graph units. */
const HALF: Record<NodeClass, number> = { memory: 4.5, entity: 3.5, session: 6.5, exchange: 3, merkle: 5 }
/** Statuses that are history rather than current belief are drawn dim. */
const DIM_STATUS = new Set(['superseded', 'forgotten'])

const endId = (end: string | FGNode): string => (typeof end === 'string' ? end : end.id)

export function GraphLens() {
  const { model, facets, setFacets, window: timeWindow, selectedId, select, focus, loading, error, reload } = useConsole()

  const visible = useMemo(() => (model && facets ? filterModel(model, facets, timeWindow) : null), [model, facets, timeWindow])

  // 2D or 3D. If the browser cannot make a WebGL context the 3D lens says so and this falls back to 2D.
  const { settings, update } = useSettings()
  const [no3d, setNo3d] = useState(false)
  const mode3d = settings.graphMode === '3d' && !no3d
  const g3Ref = useRef<Graph3DHandle>(null)
  const zoomRef = useRef(1)

  // --- stable node objects -------------------------------------------------------------------------
  const objects = useRef(new Map<string, FGNode>())
  const graphData = useMemo(() => {
    if (!visible) return { nodes: [] as FGNode[], links: [] as FGLink[] }
    const nodes = visible.nodes.map((n: CNode) => {
      let obj = objects.current.get(n.id)
      if (!obj) {
        obj = { id: n.id, cls: n.cls, label: n.label, degree: n.degree }
        objects.current.set(n.id, obj)
      }
      obj.label = n.label
      obj.status = n.status
      obj.valid = n.valid
      obj.degree = n.degree
      return obj
    })
    const links: FGLink[] = visible.edges.map((e) => ({ source: e.source, target: e.target, group: e.group, similarity: e.similarity }))
    return { nodes, links }
  }, [visible])

  // --- neighbourhood of the selection, for dimming ---------------------------------------------------
  const near = useMemo(() => {
    if (!selectedId || !visible) return null
    const set = new Set<string>([selectedId])
    for (const e of visible.edges) {
      if (e.source === selectedId) set.add(e.target)
      if (e.target === selectedId) set.add(e.source)
    }
    return set
  }, [selectedId, visible])

  // --- sizing ------------------------------------------------------------------------------------------
  const hostRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // --- camera ------------------------------------------------------------------------------------------
  const fgRef = useRef<ForceGraphMethods<FGNode, FGLink> | undefined>(undefined)
  const fitted = useRef(false)
  const [hoverId, setHoverId] = useState<string | null>(null)

  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    // structure edges hold a session together tightly; semantic edges can be longer
    const link = fg.d3Force('link') as { distance?: (fn: (l: FGLink) => number) => void } | undefined
    link?.distance?.((l) => (l.group === 'structure' ? 22 : l.group === 'relation' ? 55 : 80))
    const charge = fg.d3Force('charge') as { strength?: (n: number) => void } | undefined
    charge?.strength?.(-70)
    // a weak pull toward the middle keeps disconnected clusters (one per session) in view together,
    // so fit-to-screen is not forced to zoom out to a dust of dots
    fg.d3Force('x', forceX(0).strength(0.02))
    fg.d3Force('y', forceY(0).strength(0.02))
  }, [graphData])

  useEffect(() => {
    if (!focus || mode3d) return
    const obj = objects.current.get(focus.id)
    const fg = fgRef.current
    if (!obj || obj.x === undefined || obj.y === undefined || !fg) return
    fg.centerAt(obj.x, obj.y, 600)
    fg.zoom(Math.max(fg.zoom(), 2.4), 600)
  }, [focus, mode3d])

  const fit = useCallback(() => {
    if (mode3d) g3Ref.current?.fit()
    else fgRef.current?.zoomToFit(400, 70)
  }, [mode3d])
  const zoomBy = useCallback((k: number) => {
    if (mode3d) { g3Ref.current?.zoomBy(k); return }
    const fg = fgRef.current
    if (fg) fg.zoom(fg.zoom() * k, 200)
  }, [mode3d])

  // --- painting ----------------------------------------------------------------------------------------
  const colors = palette()

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = node.x ?? 0
      const y = node.y ?? 0
      // never smaller than a few screen pixels, however far out the fit-to-screen zoom is
      const h = nodeHalf(HALF[node.cls], node.degree, scale)
      const isSelected = node.id === selectedId
      const isHover = node.id === hoverId
      const dimmed = near ? !near.has(node.id) : false
      const history = node.status ? DIM_STATUS.has(node.status) : false
      ctx.globalAlpha = dimmed ? FADE.node : history ? 0.4 : 1

      const fill =
        node.cls === 'memory' ? colors.accent
        : node.cls === 'entity' ? colors.inkMuted
        : node.cls === 'session' ? colors.anchored
        : node.cls === 'exchange' ? colors.inkDim
        : node.valid === false ? colors.conflict : colors.anchored

      if (node.cls === 'merkle') {
        // a root is a ring: it is evidence about a session, not a thing in the graph
        ctx.lineWidth = 1.6 / scale
        ctx.strokeStyle = fill
        ctx.strokeRect(x - h, y - h, h * 2, h * 2)
      } else if (node.cls === 'memory' && (node.status === 'candidate' || node.status === 'disputed' || node.status === 'quarantined')) {
        // not-yet-trusted memories are outlined, in the colour of why
        ctx.lineWidth = 1.6 / scale
        ctx.strokeStyle = node.status === 'candidate' ? colors.accent : node.status === 'disputed' ? colors.review : colors.conflict
        ctx.strokeRect(x - h, y - h, h * 2, h * 2)
      } else {
        ctx.fillStyle = fill
        ctx.fillRect(x - h, y - h, h * 2, h * 2)
      }

      if (isSelected) {
        ctx.globalAlpha = 1
        ctx.lineWidth = 1.6 / scale
        ctx.strokeStyle = colors.ink
        ctx.strokeRect(x - h - 3 / scale, y - h - 3 / scale, (h + 3 / scale) * 2, (h + 3 / scale) * 2)
      }

      // labels earn their place: zoomed in, selected, hovered, or a hub
      // sessions are the cluster anchors, so they are named at any zoom
      const showLabel = isSelected || isHover || (!dimmed && (node.cls === 'session' || scale >= 1.8 || (scale >= 1.0 && node.degree >= 6)))
      if (showLabel) {
        const name = node.cls === 'session' ? node.label.replace(/^Session /, '') : node.label
        const text = name.length > 46 ? `${name.slice(0, 45)}…` : name
        const fontSize = 11 / scale
        ctx.font = `400 ${fontSize}px Barlow, system-ui, sans-serif`
        const w = ctx.measureText(text).width
        const padX = 5 / scale
        const padY = 3 / scale
        const lx = x + h + 5 / scale
        ctx.globalAlpha = 1
        ctx.fillStyle = colors.ground
        ctx.fillRect(lx - padX, y - fontSize / 2 - padY, w + padX * 2, fontSize + padY * 2)
        ctx.lineWidth = 1 / scale
        ctx.strokeStyle = isSelected ? colors.accent : colors.hairline
        ctx.strokeRect(lx - padX, y - fontSize / 2 - padY, w + padX * 2, fontSize + padY * 2)
        ctx.fillStyle = colors.ink
        ctx.textBaseline = 'middle'
        ctx.fillText(text, lx, y + 0.5 / scale)
      }
      ctx.globalAlpha = 1
    },
    [colors, selectedId, hoverId, near],
  )

  const paintPointer = useCallback((node: FGNode, paint: string, ctx: CanvasRenderingContext2D) => {
    const h = HALF[node.cls] + 3
    ctx.fillStyle = paint
    ctx.fillRect((node.x ?? 0) - h, (node.y ?? 0) - h, h * 2, h * 2)
  }, [])

  const linkTouchesSelection = useCallback(
    (l: FGLink) => !near || (near.has(endId(l.source)) && near.has(endId(l.target)) && (endId(l.source) === selectedId || endId(l.target) === selectedId)),
    [near, selectedId],
  )
  const linkColor = useCallback(
    (l: FGLink) => {
      // lit = no selection, or an edge of the selected node; the rest recede but stay visible
      const a = linkTouchesSelection(l) ? 1 : FADE.link / 0.4
      switch (l.group) {
        case 'relation': return withAlpha(colors.accent, LINK_ALPHA.relation * a)
        case 'contradiction': return withAlpha(colors.review, LINK_ALPHA.contradiction * a)
        case 'similarity': return withAlpha(colors.anchored, LINK_ALPHA.similarity * a)
        default: return `rgba(255,255,255,${LINK_ALPHA.structure * a})`
      }
    },
    [colors, linkTouchesSelection],
  )

  // --- empty / error / loading ---------------------------------------------------------------------------
  const resetFacets = () => model && setFacets(defaultFacets(model))

  let overlay: React.ReactNode = null
  if (error && !model) {
    overlay = (
      <div className="xc-empty" role="alert">
        <h3 className="xc-title">Graph unavailable</h3>
        <p>{error}</p>
        <div><button className="xc-btn" onClick={reload}>Retry</button></div>
      </div>
    )
  } else if (!model && loading) {
    overlay = <div className="xc-empty" role="status"><p className="xc-eyebrow xc-eyebrow--dim">Loading graph…</p></div>
  } else if (model && model.nodes.length === 0) {
    overlay = (
      <div className="xc-empty">
        <h3 className="xc-title">This workspace has no memories yet</h3>
        <p>Nodes appear here as agents write to this store.</p>
      </div>
    )
  } else if (visible && visible.nodes.length === 0) {
    overlay = (
      <div className="xc-empty">
        <h3 className="xc-title">No nodes match the current facets</h3>
        <p>The facet rail or the chain rail window is hiding all {model?.nodes.length} nodes.</p>
        <div><button className="xc-btn" onClick={resetFacets}>Reset facets</button></div>
      </div>
    )
  }

  const total = model?.nodes.length ?? 0

  return (
    <section className="xc-win xc-pane xc-canvas-win" aria-label="Graph lens">
      <div className="xc-bar">
        <p className="xc-eyebrow">Graph lens</p>
        <span className="xc-note" aria-live="polite">
          {visible ? `${visible.nodes.length === total ? total : `${visible.nodes.length} of ${total}`} nodes · ${visible.edges.length} edges` : loading ? 'Loading…' : '—'}
        </span>
        <span className="xc-spacer" />
        <div className="xc-ranges" role="group" aria-label="Graph view">
          <button type="button" aria-pressed={!mode3d} onClick={() => update({ graphMode: '2d' })}>2D</button>
          <button type="button" aria-pressed={mode3d} onClick={() => { setNo3d(false); update({ graphMode: '3d' }) }} title="Orbit, pan and zoom. Needs WebGL.">3D</button>
        </div>
        <button type="button" className="xc-btn" onClick={fit} disabled={!visible || visible.nodes.length === 0}>
          <IconFit style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />Fit
        </button>
      </div>

      {no3d && settings.graphMode === '3d' && (
        <p className="xc-note xc-3d-notice" role="status">3D needs WebGL, which this browser could not start, so the 2D view is showing.</p>
      )}

      <div className="xc-host" ref={hostRef} style={{ cursor: hoverId ? 'pointer' : 'default' }}>
        {mode3d && visible && visible.nodes.length > 0 && (
          <Graph3D ref={g3Ref} nodes={visible.nodes} edges={visible.edges} selectedId={selectedId} focus={focus} onSelect={select} onUnsupported={() => setNo3d(true)} />
        )}
        {!mode3d && size.width > 0 && visible && visible.nodes.length > 0 && (
          <ForceGraph2D<FGNode, FGLink>
            ref={fgRef}
            width={size.width}
            height={size.height}
            graphData={graphData}
            backgroundColor="rgba(0,0,0,0)"
            nodeId="id"
            nodeLabel={(n) => `${n.cls}${n.status ? ` · ${n.status}` : ''} — ${n.label}`}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={paintPointer}
            linkColor={linkColor}
            // widths are in graph units, so they are divided by the live zoom to stay at least 1px
            linkWidth={(l) => linkWidth(l.group === 'contradiction' ? 2 : l.group === 'structure' ? 1 : 1.2, zoomRef.current)}
            onZoom={(t) => { zoomRef.current = t.k }}
            linkLineDash={(l) => (l.group === 'contradiction' ? [5, 3] : l.group === 'similarity' ? [1.5, 2.5] : null)}
            linkDirectionalArrowLength={(l) => (l.group === 'relation' ? 3 : 0)}
            linkDirectionalArrowRelPos={1}
            warmupTicks={90}
            cooldownTicks={160}
            onNodeClick={(n) => select(n.id)}
            onBackgroundClick={() => select(null)}
            onNodeHover={(n) => setHoverId(n ? n.id : null)}
            onEngineStop={() => {
              if (!fitted.current) {
                fitted.current = true
                fit()
              }
            }}
          />
        )}
        {overlay && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>{overlay}</div>}

        <div className="xc-zoom">
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.4)}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.4)}>−</button>
        </div>

        <div className="xc-legend" aria-label="Legend">
          <div><i className="xc-swatch" style={{ background: 'var(--cortex-accent)' }} />Memory</div>
          <div><i className="xc-swatch" style={{ background: 'transparent', border: '1.5px solid var(--cortex-accent)' }} />Candidate memory</div>
          <div><i className="xc-swatch" style={{ background: 'var(--ink-muted)' }} />Entity</div>
          <div><i className="xc-swatch" style={{ background: 'var(--status-anchored)' }} />Session</div>
          <div><i className="xc-swatch xc-swatch--ring" />Merkle root</div>
          <div><i className="xc-rule" style={{ borderTop: '2px dashed var(--status-review)' }} />Contradiction</div>
          <div><i className="xc-rule" style={{ borderTop: '1px dotted var(--status-anchored)' }} />Similarity</div>
        </div>
      </div>
    </section>
  )
}
