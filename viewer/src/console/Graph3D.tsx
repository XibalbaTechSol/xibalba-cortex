// The Graph lens in 3D: the same nodes, edges, selection, dimming and palette as the 2D lens, laid
// out by a 3D force simulation, snapped to a 3D lattice (one cube per cell, drawn on three back faces)
// and rendered with three.js. Drag to orbit, right-drag to pan, wheel to
// zoom; click a cube to select it, click empty space to clear.
//
// What it does not do, so nobody assumes it does: it draws no arrowheads on relation edges (use the
// inspector or the 2D lens for direction), and it is not keyboard-navigable (the inspector and the
// other pages are). If the browser cannot create a WebGL context it says so and offers 2D instead of
// drawing a blank rectangle.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { forceLink, forceManyBody, forceSimulation, forceX, forceY, forceZ, type Simulation } from 'd3-force-3d'
import type { CEdge, CNode, EdgeGroup, NodeClass } from './model'
import { FADE, LINK_ALPHA, blendOver, boundingSphere, fitDistance } from './graphStyle'
import { palette } from './palette'
import { cellBounds, cellCentre, gridLines, snapToGrid, type Cell } from './gridSnap'

export interface Graph3DHandle {
  fit: () => void
  zoomBy: (k: number) => void
}

interface Props {
  nodes: CNode[]
  edges: CEdge[]
  selectedId: string | null
  focus: { id: string; nonce: number } | null
  onSelect: (id: string | null) => void
  /** the browser cannot create a WebGL context */
  onUnsupported: () => void
}

interface SimNode {
  id: string
  cls: NodeClass
  label: string
  status?: string
  valid?: boolean
  degree: number
  x: number
  y: number
  z: number
}
interface SimLink {
  source: string | SimNode
  target: string | SimNode
  group: EdgeGroup
}

/** Half-extent of a cube, in world units (the 2D lens uses the same numbers). */
const HALF: Record<NodeClass, number> = { memory: 4.5, entity: 3.5, session: 6.5, exchange: 3, merkle: 5 }
const HOLLOW_STATUS = new Set(['candidate', 'disputed', 'quarantined'])
const HISTORY_STATUS = new Set(['superseded', 'forgotten'])
const DASHED: Partial<Record<EdgeGroup, { dash: number; gap: number }>> = { contradiction: { dash: 5, gap: 3 }, similarity: { dash: 1.5, gap: 2.5 } }
const FOV = 50
/** Lattice cell size in world units. Cubes are capped below it so neighbours never touch. */
const GRID = 24
const MAX_HALF = 10.5
/** Cubes read small at the zoom that fits a whole cloud, so they are drawn larger than the 2D squares. */
const SIZE_3D = 1.4

const num = (hex: string): number => parseInt(hex.slice(1), 16)
const endId = (end: string | SimNode): string => (typeof end === 'string' ? end : end.id)

/** Deterministic start position, so the same graph opens the same way every time. */
function seedPosition(id: string): { x: number; y: number; z: number } {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619)
  const r = (k: number) => {
    const v = Math.imul(h ^ (k * 0x9e3779b1), 2246822519) >>> 0
    return v / 4294967296 - 0.5
  }
  return { x: r(1) * 120, y: r(2) * 120, z: r(3) * 120 }
}

interface Engine {
  setData: (nodes: CNode[], edges: CEdge[]) => void
  setSelection: (id: string | null) => void
  focusOn: (id: string) => void
  fit: () => void
  zoomBy: (k: number) => void
  dispose: () => void
}

function createEngine(host: HTMLElement, cb: { onSelect: (id: string | null) => void }): Engine {
  const pal = palette()
  const C = { ground: num(pal.ground), ink: num(pal.ink), muted: num(pal.inkMuted), dim: num(pal.inkDim), accent: num(pal.accent), anchored: num(pal.anchored), review: num(pal.review), conflict: num(pal.conflict) }
  const reduceMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

  // throws when WebGL is unavailable; the component turns that into a visible fallback
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setClearColor(C.ground, 1)
  const canvas = renderer.domElement
  canvas.style.display = 'block'
  canvas.setAttribute('aria-label', '3D graph. Select nodes with the pointer; the inspector and the other pages are keyboard accessible.')
  canvas.setAttribute('role', 'img')
  host.appendChild(canvas)

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(FOV, 1, 1, 6000)
  camera.position.set(0, 0, 320)
  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = false
  controls.screenSpacePanning = true
  controls.zoomSpeed = 0.8

  const labelLayer = document.createElement('div')
  labelLayer.className = 'xc-3d-labels'
  host.appendChild(labelLayer)

  // --- state ---------------------------------------------------------------------------------------------
  const simNodes = new Map<string, SimNode>() // kept for the life of the engine, so a filter change re-heats rather than scatters
  let visibleIds: string[] = []
  let links: SimLink[] = []
  let selectedId: string | null = null
  let hoverId: string | null = null
  let near: Set<string> | null = null
  const objects = new Map<string, THREE.Object3D>()
  const proxies: THREE.Mesh[] = []
  const box = new THREE.BoxGeometry(1, 1, 1)
  const boxEdges = new THREE.EdgesGeometry(box)
  const nodeGroup = new THREE.Group()
  const linkGroup = new THREE.Group()
  scene.add(linkGroup, nodeGroup)
  const ring = new THREE.LineSegments(boxEdges, new THREE.LineBasicMaterial({ color: C.ink }))
  ring.visible = false
  scene.add(ring)

  // --- the lattice ---------------------------------------------------------------------------------------
  // The simulation runs in continuous space; what is drawn is each node's cell. `targets` is where each
  // cube is heading, `cells` remembers the previous assignment so boundary nodes do not flicker.
  let cells = new Map<string, Cell>()
  const targets = new Map<string, THREE.Vector3>()
  let animating = false
  const gridObj = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: blendOver(C.ink, C.ground, 0.1) }))
  gridObj.frustumCulled = false
  scene.add(gridObj)
  let gridKey = ''
  function retarget() {
    const pts = visibleIds.map((id) => simNodes.get(id)!).map((n) => ({ id: n.id, x: n.x, y: n.y, z: n.z, priority: n.degree }))
    cells = snapToGrid(pts, GRID, cells)
    targets.clear()
    for (const [id, c] of cells) { const p = cellCentre(c, GRID); targets.set(id, new THREE.Vector3(p.x, p.y, p.z)) }
    const b = cellBounds(cells.values())
    const k = b ? `${b.min.i},${b.min.j},${b.min.k}|${b.max.i},${b.max.j},${b.max.k}` : ''
    if (k !== gridKey) {
      gridKey = k
      gridObj.geometry.dispose()
      const g = new THREE.BufferGeometry()
      if (b) g.setAttribute('position', new THREE.BufferAttribute(gridLines(b, GRID, 1), 3))
      gridObj.geometry = g
    }
    canvas.dataset.cells = String(new Set([...cells.values()].map((c) => `${c.i},${c.j},${c.k}`)).size)
  }

  const sim: Simulation = forceSimulation([], 3).alphaDecay(0.035).velocityDecay(0.4).stop()
  sim.force('charge', forceManyBody().strength(-48))
  sim.force('x', forceX(0).strength(0.045))
  sim.force('y', forceY(0).strength(0.045))
  sim.force('z', forceZ(0).strength(0.045))
  sim.force('link', forceLink([]).id((n) => n.id).distance((l) => {
    const g = (l as SimLink).group
    return g === 'structure' ? 22 : g === 'relation' ? 55 : 80
  }).strength(0.7))

  let moving = true
  let fittedOnce = false
  let dirty = true
  let raf = 0
  let tween: { from: THREE.Vector3; to: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; start: number; ms: number } | null = null

  const half = (n: SimNode): number => Math.min(MAX_HALF, HALF[n.cls] * SIZE_3D * (1 + Math.min(n.degree, 12) * 0.05))
  const colourOf = (n: SimNode): number => {
    if (n.cls === 'memory') return n.status === 'disputed' ? C.review : n.status === 'quarantined' ? C.conflict : C.accent
    if (n.cls === 'entity') return C.muted
    if (n.cls === 'session') return C.anchored
    if (n.cls === 'exchange') return C.dim
    return n.valid === false ? C.conflict : C.anchored
  }
  const opacityOf = (n: SimNode): number => (near && !near.has(n.id) ? FADE.node : n.status && HISTORY_STATUS.has(n.status) ? 0.4 : 1)

  // --- nodes ------------------------------------------------------------------------------------------------
  function buildObject(n: SimNode): THREE.Object3D {
    const side = half(n) * 2
    const hollow = n.cls === 'merkle' || (n.cls === 'memory' && !!n.status && HOLLOW_STATUS.has(n.status))
    let visual: THREE.Object3D
    if (hollow) visual = new THREE.LineSegments(boxEdges, new THREE.LineBasicMaterial({ color: colourOf(n), transparent: true }))
    else visual = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: colourOf(n), transparent: true }))
    visual.scale.setScalar(side)
    // a slightly larger invisible cube is what the pointer hits, so a hollow node is as easy to pick as a solid one
    const hit = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ visible: false }))
    hit.scale.setScalar(1.5)
    hit.userData.id = n.id
    const group = new THREE.Group()
    group.add(visual, hit)
    group.userData = { id: n.id, visual, hit }
    return group
  }
  const materialOf = (o: THREE.Object3D): THREE.Material & { opacity: number } =>
    ((o.userData.visual as THREE.Mesh | THREE.LineSegments).material as THREE.Material & { opacity: number })

  function applyNodeStyle() {
    for (const [id, o] of objects) {
      const n = simNodes.get(id)
      if (n) materialOf(o).opacity = opacityOf(n)
    }
  }

  // --- links ------------------------------------------------------------------------------------------------
  interface Bucket { line: THREE.LineSegments; idx: SimLink[]; dashed: boolean }
  let buckets: Bucket[] = []
  function disposeBuckets() {
    for (const b of buckets) {
      linkGroup.remove(b.line)
      b.line.geometry.dispose()
      ;(b.line.material as THREE.Material).dispose()
    }
    buckets = []
  }
  function linkColour(l: SimLink): number {
    const g = l.group
    const base = g === 'relation' ? C.accent : g === 'contradiction' ? C.review : g === 'similarity' ? C.anchored : 0xffffff
    const lit = !near || (near.has(endId(l.source)) && near.has(endId(l.target)) && (endId(l.source) === selectedId || endId(l.target) === selectedId))
    return blendOver(base, C.ground, LINK_ALPHA[g] * (lit ? 1 : FADE.link / 0.4))
  }
  function buildBuckets() {
    disposeBuckets()
    const groups: EdgeGroup[] = ['structure', 'relation', 'similarity', 'contradiction']
    for (const g of groups) {
      const idx = links.filter((l) => l.group === g)
      if (idx.length === 0) continue
      const dashed = !!DASHED[g]
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(idx.length * 6), 3))
      geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(idx.length * 6), 3))
      const material = dashed
        ? new THREE.LineDashedMaterial({ vertexColors: true, dashSize: DASHED[g]!.dash, gapSize: DASHED[g]!.gap })
        : new THREE.LineBasicMaterial({ vertexColors: true })
      const line = new THREE.LineSegments(geometry, material)
      line.frustumCulled = false
      linkGroup.add(line)
      buckets.push({ line, idx, dashed })
    }
    paintLinks()
  }
  function paintLinks() {
    const tmp = new THREE.Color()
    for (const b of buckets) {
      const attr = b.line.geometry.getAttribute('color') as THREE.BufferAttribute
      b.idx.forEach((l, i) => {
        tmp.setHex(linkColour(l))
        attr.setXYZ(i * 2, tmp.r, tmp.g, tmp.b)
        attr.setXYZ(i * 2 + 1, tmp.r, tmp.g, tmp.b)
      })
      attr.needsUpdate = true
    }
  }
  function updateLinkPositions() {
    for (const b of buckets) {
      const attr = b.line.geometry.getAttribute('position') as THREE.BufferAttribute
      b.idx.forEach((l, i) => {
        const s = objects.get(endId(l.source))!.position
        const t = objects.get(endId(l.target))!.position
        attr.setXYZ(i * 2, s.x, s.y, s.z)
        attr.setXYZ(i * 2 + 1, t.x, t.y, t.z)
      })
      attr.needsUpdate = true
      if (b.dashed) b.line.computeLineDistances()
    }
  }

  // --- labels (DOM, so they use the real font and stay crisp) --------------------------------------------------
  const labels = new Map<string, HTMLDivElement>()
  function wantedLabels(): Set<string> {
    const want = new Set<string>()
    for (const id of visibleIds) if (simNodes.get(id)?.cls === 'session' && (!near || near.has(id))) want.add(id)
    if (selectedId && simNodes.has(selectedId)) want.add(selectedId)
    if (hoverId && simNodes.has(hoverId)) want.add(hoverId)
    return want
  }
  const tmpV = new THREE.Vector3()
  function updateLabels() {
    const want = wantedLabels()
    for (const [id, el] of labels) if (!want.has(id)) { el.remove(); labels.delete(id) }
    const w = canvas.clientWidth, h = canvas.clientHeight
    for (const id of want) {
      const n = simNodes.get(id)!
      if (!objects.has(id)) continue
      let el = labels.get(id)
      if (!el) {
        el = document.createElement('div')
        el.className = 'xc-3d-label'
        const name = n.cls === 'session' ? n.label.replace(/^Session /, '') : n.label
        el.textContent = name.length > 46 ? `${name.slice(0, 45)}…` : name
        labelLayer.appendChild(el)
        labels.set(id, el)
      }
      el.dataset.selected = String(id === selectedId)
      tmpV.copy(objects.get(id)!.position).project(camera)
      const behind = tmpV.z > 1
      el.style.display = behind ? 'none' : 'block'
      el.style.transform = `translate(${(tmpV.x * 0.5 + 0.5) * w + 12}px, ${(-tmpV.y * 0.5 + 0.5) * h}px) translateY(-50%)`
    }
  }

  // --- picking -------------------------------------------------------------------------------------------------
  const raycaster = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  function pick(clientX: number, clientY: number): string | null {
    const r = canvas.getBoundingClientRect()
    ndc.set(((clientX - r.left) / r.width) * 2 - 1, -(((clientY - r.top) / r.height) * 2 - 1))
    raycaster.setFromCamera(ndc, camera)
    const hit = raycaster.intersectObjects(proxies, false)[0]
    return hit ? (hit.object.userData.id as string) : null
  }
  let down: { x: number; y: number } | null = null
  const onDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY } }
  const onUp = (e: PointerEvent) => {
    // a drag orbits; only a click that barely moved selects
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) cb.onSelect(pick(e.clientX, e.clientY))
    down = null
  }
  let hoverQueued = false
  const onMove = (e: PointerEvent) => {
    if (hoverQueued || e.buttons) return
    hoverQueued = true
    const { clientX, clientY } = e
    requestAnimationFrame(() => {
      hoverQueued = false
      const id = pick(clientX, clientY)
      if (id !== hoverId) { hoverId = id; canvas.style.cursor = id ? 'pointer' : 'grab'; dirty = true }
    })
  }
  canvas.style.cursor = 'grab'
  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('pointerup', onUp)
  canvas.addEventListener('pointermove', onMove)
  controls.addEventListener('change', () => { dirty = true })

  // --- camera ---------------------------------------------------------------------------------------------------
  function flyTo(position: THREE.Vector3, target: THREE.Vector3) {
    if (reduceMotion) { camera.position.copy(position); controls.target.copy(target); controls.update(); dirty = true; return }
    tween = { from: camera.position.clone(), to: position, fromT: controls.target.clone(), toT: target, start: performance.now(), ms: 550 }
  }
  function direction(): THREE.Vector3 {
    const d = camera.position.clone().sub(controls.target)
    return d.lengthSq() < 1e-6 ? new THREE.Vector3(0.45, 0.35, 1).normalize() : d.normalize()
  }
  function fit() {
    const pts = visibleIds.map((id) => targets.get(id)).filter((v): v is THREE.Vector3 => !!v)
    if (pts.length === 0) return
    const s = boundingSphere(pts)
    const c = new THREE.Vector3(s.cx, s.cy, s.cz)
    const dist = fitDistance(s.radius + 8, FOV, camera.aspect, 1.05)
    flyTo(c.clone().add(direction().multiplyScalar(dist)), c)
  }

  // --- size -------------------------------------------------------------------------------------------------------
  function resize() {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight)
    renderer.setSize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    dirty = true
  }
  const ro = new ResizeObserver(resize)
  ro.observe(host)
  resize()

  // --- loop ----------------------------------------------------------------------------------------------------------
  function syncObjects() {
    animating = false
    for (const [id, o] of objects) {
      const t = targets.get(id)
      if (!t) continue
      if (reduceMotion || o.userData.placed !== true) { o.position.copy(t); o.userData.placed = true }
      else {
        // glide cell to cell rather than teleport, so a re-layout stays readable
        o.position.lerp(t, 0.3)
        if (o.position.distanceToSquared(t) > 0.01) animating = true
        else o.position.copy(t)
      }
    }
    const sel = selectedId ? objects.get(selectedId) : null
    ring.visible = !!sel
    if (sel && selectedId) { ring.position.copy(sel.position); ring.scale.setScalar(half(simNodes.get(selectedId)!) * 2 * 1.45) }
  }
  function frame(now: number) {
    raf = requestAnimationFrame(frame)
    if (moving) {
      for (let i = 0; i < 3; i++) sim.tick()
      retarget()
      if (sim.alpha() < sim.alphaMin()) {
        moving = false
        if (!fittedOnce) { fittedOnce = true; fit() }
      }
    }
    if (moving || animating) { syncObjects(); updateLinkPositions(); dirty = true }
    if (tween) {
      const k = Math.min(1, (now - tween.start) / tween.ms)
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2
      camera.position.lerpVectors(tween.from, tween.to, e)
      controls.target.lerpVectors(tween.fromT, tween.toT, e)
      controls.update()
      if (k >= 1) tween = null
      dirty = true
    }
    if (dirty) {
      dirty = false
      updateLabels()
      renderer.render(scene, camera)
      canvas.dataset.settled = String(!moving)
    }
  }
  raf = requestAnimationFrame(frame)

  // --- API --------------------------------------------------------------------------------------------------------------
  function recomputeNear() {
    if (!selectedId) { near = null; return }
    const set = new Set<string>([selectedId])
    for (const l of links) {
      if (endId(l.source) === selectedId) set.add(endId(l.target))
      if (endId(l.target) === selectedId) set.add(endId(l.source))
    }
    near = set
  }

  return {
    setData(nodes, edges) {
      const ids = new Set(nodes.map((n) => n.id))
      visibleIds = nodes.map((n) => n.id)
      for (const n of nodes) {
        let s = simNodes.get(n.id)
        if (!s) { s = { id: n.id, cls: n.cls, label: n.label, degree: n.degree, ...seedPosition(n.id) }; simNodes.set(n.id, s) }
        s.label = n.label; s.status = n.status; s.valid = n.valid; s.degree = n.degree; s.cls = n.cls
      }
      for (const [id, o] of objects) {
        if (ids.has(id)) continue
        nodeGroup.remove(o)
        const hit = o.userData.hit as THREE.Mesh
        proxies.splice(proxies.indexOf(hit), 1)
        materialOf(o).dispose()
        ;(hit.material as THREE.Material).dispose()
        objects.delete(id)
      }
      for (const n of nodes) {
        if (objects.has(n.id)) continue
        const o = buildObject(simNodes.get(n.id)!)
        objects.set(n.id, o)
        nodeGroup.add(o)
        proxies.push(o.userData.hit as THREE.Mesh)
      }
      links = edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ source: e.source, target: e.target, group: e.group }))
      sim.nodes(nodes.map((n) => simNodes.get(n.id)!))
      sim.force('link')?.links(links)
      sim.alpha(fittedOnce ? 0.35 : 1)
      moving = true
      recomputeNear(); applyNodeStyle(); buildBuckets(); retarget(); syncObjects(); updateLinkPositions()
      canvas.dataset.nodeCount = String(nodes.length)
      dirty = true
    },
    setSelection(id) {
      selectedId = id
      recomputeNear(); applyNodeStyle(); paintLinks(); syncObjects()
      canvas.dataset.selected = id ?? ''
      dirty = true
    },
    focusOn(id) {
      const t = targets.get(id)
      if (!t) return
      const target = t.clone()
      flyTo(target.clone().add(direction().multiplyScalar(90)), target)
    },
    fit,
    zoomBy(k) {
      const offset = camera.position.clone().sub(controls.target)
      flyTo(controls.target.clone().add(offset.divideScalar(k)), controls.target.clone())
    },
    dispose() {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointermove', onMove)
      controls.dispose()
      disposeBuckets()
      for (const o of objects.values()) { materialOf(o).dispose(); ((o.userData.hit as THREE.Mesh).material as THREE.Material).dispose() }
      ring.material.dispose()
      gridObj.geometry.dispose(); (gridObj.material as THREE.Material).dispose()
      box.dispose(); boxEdges.dispose()
      sim.stop()
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
      labelLayer.remove()
    },
  }
}

export const Graph3D = forwardRef<Graph3DHandle, Props>(function Graph3D({ nodes, edges, selectedId, focus, onSelect, onUnsupported }, ref) {
  const hostRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<Engine | null>(null)
  const [failed, setFailed] = useState(false)
  // the callbacks change identity every render; the engine reads the latest through these
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    try {
      engineRef.current = createEngine(host, { onSelect: (id) => selectRef.current(id) })
    } catch {
      setFailed(true)
      onUnsupported()
      return
    }
    return () => {
      engineRef.current?.dispose()
      engineRef.current = null
    }
    // created once per mount; data and selection arrive through the effects below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { engineRef.current?.setData(nodes, edges) }, [nodes, edges])
  useEffect(() => { engineRef.current?.setSelection(selectedId) }, [selectedId, nodes, edges])
  useEffect(() => { if (focus) engineRef.current?.focusOn(focus.id) }, [focus])

  useImperativeHandle(ref, () => ({ fit: () => engineRef.current?.fit(), zoomBy: (k) => engineRef.current?.zoomBy(k) }), [])

  if (failed) {
    return (
      <div className="xc-empty" role="alert">
        <h3 className="xc-title">3D needs WebGL</h3>
        <p>This browser could not create a WebGL context, so the 3D view cannot be drawn. The 2D view is showing instead.</p>
      </div>
    )
  }
  return <div ref={hostRef} className="xc-3d-host" data-graph3d="" />
})
