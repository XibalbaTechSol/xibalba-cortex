// The Graph lens in 3D: the same nodes, edges, selection, dimming and palette as the 2D lens, laid
// out by a 3D force simulation, snapped to a 3D lattice (one cube per cell, drawn as a full 3D lattice of cell walls)
// and rendered with three.js. Drag to orbit, right-drag to pan, wheel to
// zoom; click a cube to select it, click empty space to clear.
//
// Edges are selectable (the line nearest the pointer within a few pixels), relation edges carry an
// arrowhead at the object end, and a cube can be dragged: it follows the pointer on the plane facing the
// camera, lands in the nearest free lattice cell, and stays pinned there until it is double-clicked or
// "Unpin" is used. Pins live in this view only; nothing is written to the store.
//
// What it does not do, so nobody assumes it does: it is not keyboard-navigable (the inspector and the
// other pages are). If the browser cannot create a WebGL context it says so and offers 2D instead of
// drawing a blank rectangle.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { forceLink, forceManyBody, forceSimulation, forceX, forceY, forceZ, type Simulation } from 'd3-force-3d'
import type { CEdge, CNode, EdgeGroup, NodeClass } from './model'
import { FADE, LINK_ALPHA, blendOver } from './graphStyle'
import { palette } from './palette'
import { frameCamera, type Vec3 } from './framing'
import { cellBounds, cellCentre, latticeFrame, latticeLines, snapToGrid, type Cell } from './gridSnap'

export interface Graph3DHandle {
  fit: () => void
  /** frame the selected node and its neighbours, or the two ends of a selected edge */
  fitSelection: () => void
  zoomBy: (k: number) => void
  unpinAll: () => void
}

interface Props {
  nodes: CNode[]
  edges: CEdge[]
  selectedId: string | null
  focus: { id: string; nonce: number } | null
  /** a node id, an edge id, or null */
  onSelect: (id: string | null) => void
  /** cubes take a lattice cell each (true) or sit where the force layout leaves them (false) */
  snap: boolean
  /** how many cubes are pinned by dragging */
  onPinnedChange?: (count: number) => void
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
  /** d3-force-3d holds a node at fx/fy/fz while they are numbers; null lets the simulation move it */
  fx?: number | null
  fy?: number | null
  fz?: number | null
}
interface SimLink {
  id: string
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
  setSnap: (on: boolean) => void
  focusOn: (id: string) => void
  fit: () => void
  fitSelection: () => void
  zoomBy: (k: number) => void
  unpinAll: () => void
  dispose: () => void
}

function createEngine(host: HTMLElement, cb: { snap: boolean; onSelect: (id: string | null) => void; onPinnedChange: (count: number) => void }): Engine {
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
  // a selected edge is a thin cylinder, because a WebGL line is always one pixel wide
  const edgeMark = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 1, 8), new THREE.MeshBasicMaterial({ color: C.ink }))
  edgeMark.visible = false
  scene.add(edgeMark)
  // relation edges point from subject to object; the cone's tip sits on the object cube's surface
  const ARROW_LEN = 6
  const arrowGeom = new THREE.ConeGeometry(2.1, ARROW_LEN, 10)
  const arrowMat = new THREE.MeshBasicMaterial({ color: 0xffffff })
  let arrows: THREE.InstancedMesh | null = null
  let arrowLinks: SimLink[] = []

  // --- the lattice ---------------------------------------------------------------------------------------
  // The simulation runs in continuous space; what is drawn is each node's cell. `targets` is where each
  // cube is heading, `cells` remembers the previous assignment so boundary nodes do not flicker.
  let snapOn = cb.snap
  let cells = new Map<string, Cell>()
  const targets = new Map<string, THREE.Vector3>()
  let animating = false
  // the lattice is a true 3D grid: cell walls run through the whole volume along x, y and z, with the
  // bounding box drawn a little brighter. depthWrite is off so the faint lines never fight the cubes.
  const gridObj = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: blendOver(C.ink, C.ground, 0.028), depthWrite: false }))
  gridObj.frustumCulled = false
  const frameObj = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: blendOver(C.ink, C.ground, 0.13), depthWrite: false }))
  frameObj.frustumCulled = false
  scene.add(gridObj, frameObj)
  let gridKey = ''
  function retarget() {
    const pts = visibleIds.map((id) => simNodes.get(id)!).map((n) => ({ id: n.id, x: n.x, y: n.y, z: n.z, priority: n.fx != null ? 1e6 : n.degree }))
    // the cells are always computed: they size the grid. Only with snap on do the cubes go to them.
    cells = snapToGrid(pts, GRID, cells)
    targets.clear()
    if (snapOn) for (const [id, c] of cells) { const p = cellCentre(c, GRID); targets.set(id, new THREE.Vector3(p.x, p.y, p.z)) }
    else for (const pt of pts) targets.set(pt.id, new THREE.Vector3(pt.x, pt.y, pt.z))
    const b = cellBounds(cells.values())
    const k = b ? `${b.min.i},${b.min.j},${b.min.k}|${b.max.i},${b.max.j},${b.max.k}` : ''
    if (k !== gridKey) {
      gridKey = k
      gridObj.geometry.dispose()
      frameObj.geometry.dispose()
      const g = new THREE.BufferGeometry()
      const f = new THREE.BufferGeometry()
      if (b) {
        g.setAttribute('position', new THREE.BufferAttribute(latticeLines(b, GRID, 1), 3))
        f.setAttribute('position', new THREE.BufferAttribute(latticeFrame(b, GRID, 1), 3))
      }
      gridObj.geometry = g
      frameObj.geometry = f
    }
    canvas.dataset.cells = snapOn ? String(new Set([...cells.values()].map((c) => `${c.i},${c.j},${c.k}`)).size) : 'off'
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
  // once the person orbits, pans or zooms, the camera is theirs: layout changes stop re-framing it until they press Fit
  let userMoved = false
  controls.addEventListener('start', () => { userMoved = true })
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
    hit.scale.setScalar(side * 1.5)
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
  const selectedLink = (): SimLink | undefined => (selectedId ? links.find((l) => l.id === selectedId) : undefined)
  function linkColour(l: SimLink): number {
    const g = l.group
    const base = g === 'relation' ? C.accent : g === 'contradiction' ? C.review : g === 'similarity' ? C.anchored : 0xffffff
    const lit = !near || l.id === selectedId || (near.has(endId(l.source)) && near.has(endId(l.target)) && (endId(l.source) === selectedId || endId(l.target) === selectedId))
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
    if (arrows) { scene.remove(arrows); arrows.dispose(); arrows = null }
    arrowLinks = links.filter((l) => l.group === 'relation')
    if (arrowLinks.length > 0) {
      arrows = new THREE.InstancedMesh(arrowGeom, arrowMat, arrowLinks.length)
      arrows.frustumCulled = false
      scene.add(arrows)
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
    if (arrows) {
      arrowLinks.forEach((l, i) => arrows!.setColorAt(i, tmp.setHex(linkColour(l))))
      if (arrows.instanceColor) arrows.instanceColor.needsUpdate = true
    }
  }
  const up = new THREE.Vector3(0, 1, 0)
  const aDir = new THREE.Vector3()
  const aPos = new THREE.Vector3()
  const aQuat = new THREE.Quaternion()
  const aScale = new THREE.Vector3(1, 1, 1)
  const aMat = new THREE.Matrix4()
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
    if (arrows) {
      arrowLinks.forEach((l, i) => {
        const s = objects.get(endId(l.source))!.position
        const t = objects.get(endId(l.target))!.position
        aDir.subVectors(t, s)
        if (aDir.lengthSq() < 1e-6) { aMat.makeScale(0, 0, 0); arrows!.setMatrixAt(i, aMat); return }
        aDir.normalize()
        // distance from the cube's centre to its surface along the line, for an axis-aligned cube
        const reach = half(simNodes.get(endId(l.target))!) / Math.max(Math.abs(aDir.x), Math.abs(aDir.y), Math.abs(aDir.z))
        aPos.copy(t).addScaledVector(aDir, -(reach + ARROW_LEN / 2))
        aQuat.setFromUnitVectors(up, aDir)
        arrows!.setMatrixAt(i, aMat.compose(aPos, aQuat, aScale))
      })
      arrows.instanceMatrix.needsUpdate = true
    }
    const picked = selectedLink()
    edgeMark.visible = !!picked
    if (picked) {
      const s = objects.get(endId(picked.source))!.position
      const t = objects.get(endId(picked.target))!.position
      aDir.subVectors(t, s)
      const len = aDir.length()
      edgeMark.position.copy(s).addScaledVector(aDir, 0.5)
      edgeMark.quaternion.setFromUnitVectors(up, len > 1e-6 ? aDir.divideScalar(len) : up)
      edgeMark.scale.set(1, Math.max(len, 0.01), 1)
    }
  }

  // --- labels (DOM, so they use the real font and stay crisp) --------------------------------------------------
  const labels = new Map<string, HTMLDivElement>()
  function wantedLabels(): Set<string> {
    const want = new Set<string>()
    for (const id of visibleIds) if (simNodes.get(id)?.cls === 'session' && (!near || near.has(id))) want.add(id)
    if (selectedId && simNodes.has(selectedId)) want.add(selectedId)
    const sl = selectedLink()
    if (sl) { want.add(endId(sl.source)); want.add(endId(sl.target)) }
    if (hoverId && simNodes.has(hoverId)) want.add(hoverId)
    return want
  }
  const tmpV = new THREE.Vector3()
  function updateLabels() {
    const want = wantedLabels()
    for (const [id, el] of labels) if (!want.has(id)) { el.remove(); labels.delete(id) }
    const w = canvas.clientWidth, h = canvas.clientHeight
    const sl2 = selectedLink()
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
      el.dataset.selected = String(id === selectedId || (!!sl2 && (id === endId(sl2.source) || id === endId(sl2.target))))
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
  /** The edge whose projected segment passes within EDGE_PICK_PX of the pointer, nearest first. */
  const EDGE_PICK_PX = 6
  const pa = new THREE.Vector3()
  const pb = new THREE.Vector3()
  function pickEdge(clientX: number, clientY: number): string | null {
    const r = canvas.getBoundingClientRect()
    const px = clientX - r.left, py = clientY - r.top
    let best: string | null = null
    let bestD = EDGE_PICK_PX
    for (const l of links) {
      const a = objects.get(endId(l.source)), b = objects.get(endId(l.target))
      if (!a || !b) continue
      pa.copy(a.position).project(camera)
      pb.copy(b.position).project(camera)
      if (pa.z > 1 || pb.z > 1) continue
      const ax = (pa.x * 0.5 + 0.5) * r.width, ay = (-pa.y * 0.5 + 0.5) * r.height
      const bx = (pb.x * 0.5 + 0.5) * r.width, by = (-pb.y * 0.5 + 0.5) * r.height
      const dx = bx - ax, dy = by - ay
      const len2 = dx * dx + dy * dy
      // point-to-segment distance in screen pixels
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
      const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
      if (d < bestD) { bestD = d; best = l.id }
    }
    return best
  }
  const pickAny = (x: number, y: number): string | null => pick(x, y) ?? pickEdge(x, y)

  // --- dragging a cube -----------------------------------------------------------------------------------------
  // Pointer-down on a cube takes the pointer away from the orbit controls. The cube follows the pointer on
  // the plane through it that faces the camera; the lattice then puts it in the nearest free cell.
  let down: { x: number; y: number; id: string | null } | null = null
  let drag: { id: string; plane: THREE.Plane; moved: boolean } | null = null
  const pinned = new Set<string>()
  const pinMarks = new Map<string, THREE.LineSegments>()
  const hitPoint = new THREE.Vector3()
  function setPinned(id: string, on: boolean) {
    const n = simNodes.get(id)
    const o = objects.get(id)
    if (!n || !o) return
    if (on) {
      pinned.add(id)
      if (!pinMarks.has(id)) {
        const mark = new THREE.LineSegments(boxEdges, new THREE.LineBasicMaterial({ color: C.ink, transparent: true, opacity: 0.55 }))
        mark.scale.setScalar(half(n) * 2 * 1.3)
        o.add(mark)
        pinMarks.set(id, mark)
      }
    } else {
      n.fx = n.fy = n.fz = null
      pinned.delete(id)
      const mark = pinMarks.get(id)
      if (mark) { o.remove(mark); (mark.material as THREE.Material).dispose(); pinMarks.delete(id) }
    }
    canvas.dataset.pinned = String(pinned.size)
    cb.onPinnedChange(pinned.size)
  }
  function reheat() { sim.alpha(Math.max(sim.alpha(), 0.3)); moving = true }
  const onDown = (e: PointerEvent) => {
    down = { x: e.clientX, y: e.clientY, id: pick(e.clientX, e.clientY) }
    const n = down.id ? simNodes.get(down.id) : undefined
    if (!n || !objects.has(n.id)) return
    controls.enabled = false
    const normal = camera.getWorldDirection(new THREE.Vector3())
    drag = { id: n.id, plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, new THREE.Vector3(n.x, n.y, n.z)), moved: false }
    canvas.setPointerCapture(e.pointerId)
  }
  const onUp = (e: PointerEvent) => {
    const wasClick = !!down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5
    if (drag) {
      controls.enabled = true
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId)
      drag = null
    }
    // a drag orbits or moves a cube; only a click that barely moved selects
    if (wasClick) cb.onSelect(pickAny(e.clientX, e.clientY))
    down = null
  }
  const onDouble = (e: MouseEvent) => {
    const id = pick(e.clientX, e.clientY)
    if (id && pinned.has(id)) { setPinned(id, false); reheat() }
  }
  let hoverQueued = false
  const onMove = (e: PointerEvent) => {
    if (drag && down && Math.hypot(e.clientX - down.x, e.clientY - down.y) >= 5) {
      const n = simNodes.get(drag.id)!
      const r = canvas.getBoundingClientRect()
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1))
      raycaster.setFromCamera(ndc, camera)
      if (raycaster.ray.intersectPlane(drag.plane, hitPoint)) {
        drag.moved = true
        n.fx = hitPoint.x; n.fy = hitPoint.y; n.fz = hitPoint.z
        setPinned(drag.id, true)
        reheat()
        canvas.style.cursor = 'grabbing'
      }
      return
    }
    if (hoverQueued || e.buttons) return
    hoverQueued = true
    const { clientX, clientY } = e
    requestAnimationFrame(() => {
      hoverQueued = false
      const id = pick(clientX, clientY)
      const edge = id ? null : pickEdge(clientX, clientY)
      if (id !== hoverId) { hoverId = id; dirty = true }
      canvas.style.cursor = id ? 'grab' : edge ? 'pointer' : 'grab'
    })
  }
  canvas.style.cursor = 'grab'
  // capture phase, so the controls never see a pointer that starts on a cube
  canvas.addEventListener('pointerdown', onDown, true)
  canvas.addEventListener('dblclick', onDouble)
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
  // Smart framing (see framing.ts): the camera looks along the cloud's thinnest axis, with a little tilt,
  // at the nearest distance that holds every cube inside the real perspective frustum.
  const lastFrame = { pts: 0 }
  function frameOn(ids: Iterable<string>, opts: { margin: number; minDistance?: number }) {
    const pts: Vec3[] = []
    for (const id of ids) { const t = targets.get(id); if (t) pts.push([t.x, t.y, t.z]) }
    const f = frameCamera(pts, { fovDeg: FOV, aspect: camera.aspect, margin: opts.margin, pad: MAX_HALF * 0.7, minDistance: opts.minDistance, prefer: direction().toArray() as Vec3 })
    if (!f) return
    lastFrame.pts = pts.length
    const target = new THREE.Vector3(...f.target)
    flyTo(target.clone().add(new THREE.Vector3(...f.direction).multiplyScalar(f.distance)), target)
  }
  function fit() {
    // the zoom buttons and the legend sit over the canvas edge, so leave a little more room than the bare fit
    frameOn(visibleIds, { margin: 1.06 })
  }

  // --- size -------------------------------------------------------------------------------------------------------
  function resize() {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight)
    renderer.setSize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    dirty = true
    if (fittedOnce && !userMoved) fit()
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
        // frame the first layout, and every later one (a filter, snap on or off) until the person takes the camera
        if (!fittedOnce || !userMoved) { fittedOnce = true; fit() }
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
    const edge = selectedLink()
    if (edge) { near = new Set([endId(edge.source), endId(edge.target)]); return }
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
        const mark = pinMarks.get(id)
        if (mark) { (mark.material as THREE.Material).dispose(); pinMarks.delete(id) }
        objects.delete(id)
      }
      for (const n of nodes) {
        if (objects.has(n.id)) continue
        const o = buildObject(simNodes.get(n.id)!)
        objects.set(n.id, o)
        nodeGroup.add(o)
        proxies.push(o.userData.hit as THREE.Mesh)
      }
      links = edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ id: e.id, source: e.source, target: e.target, group: e.group }))
      sim.nodes(nodes.map((n) => simNodes.get(n.id)!))
      sim.force('link')?.links(links)
      sim.alpha(fittedOnce ? 0.35 : 1)
      moving = true
      recomputeNear(); applyNodeStyle(); buildBuckets(); retarget(); syncObjects(); updateLinkPositions()
      canvas.dataset.nodeCount = String(nodes.length)
      dirty = true
    },
    setSnap(on) {
      if (on === snapOn) return
      snapOn = on
      // re-heat so the cubes glide to their cells (or off them) rather than jump
      cells = new Map(); retarget(); reheat(); dirty = true
    },
    setSelection(id) {
      selectedId = id
      recomputeNear(); applyNodeStyle(); paintLinks(); syncObjects(); updateLinkPositions()
      canvas.dataset.selected = id ?? ''
      dirty = true
    },
    focusOn(id) {
      const t = targets.get(id)
      if (!t) return
      const target = t.clone()
      flyTo(target.clone().add(direction().multiplyScalar(90)), target)
    },
    fit() { userMoved = false; fit() },
    fitSelection() {
      if (!selectedId) return fit()
      // the selection and what it touches: the same set that is lit, so the framing matches the dimming
      // (a lone node would otherwise fill the screen, so never come closer than a comfortable 70 units)
      frameOn(near ?? new Set([selectedId]), { margin: 1.25, minDistance: 70 })
    },
    unpinAll() {
      for (const id of [...pinned]) setPinned(id, false)
      reheat()
    },
    zoomBy(k) {
      const offset = camera.position.clone().sub(controls.target)
      flyTo(controls.target.clone().add(offset.divideScalar(k)), controls.target.clone())
    },
    dispose() {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onDown, true)
      canvas.removeEventListener('dblclick', onDouble)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointermove', onMove)
      controls.dispose()
      disposeBuckets()
      for (const o of objects.values()) { materialOf(o).dispose(); ((o.userData.hit as THREE.Mesh).material as THREE.Material).dispose() }
      ring.material.dispose()
      edgeMark.geometry.dispose(); (edgeMark.material as THREE.Material).dispose()
      if (arrows) arrows.dispose()
      arrowGeom.dispose(); arrowMat.dispose()
      for (const m of pinMarks.values()) (m.material as THREE.Material).dispose()
      gridObj.geometry.dispose(); (gridObj.material as THREE.Material).dispose()
      frameObj.geometry.dispose(); (frameObj.material as THREE.Material).dispose()
      box.dispose(); boxEdges.dispose()
      sim.stop()
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
      labelLayer.remove()
    },
  }
}

export const Graph3D = forwardRef<Graph3DHandle, Props>(function Graph3D({ nodes, edges, selectedId, focus, snap, onSelect, onPinnedChange, onUnsupported }, ref) {
  const hostRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<Engine | null>(null)
  const [failed, setFailed] = useState(false)
  // the callbacks change identity every render; the engine reads the latest through these
  const selectRef = useRef(onSelect)
  selectRef.current = onSelect
  const pinRef = useRef(onPinnedChange)
  pinRef.current = onPinnedChange

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    try {
      engineRef.current = createEngine(host, { snap, onSelect: (id) => selectRef.current(id), onPinnedChange: (n) => pinRef.current?.(n) })
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
  useEffect(() => { engineRef.current?.setSnap(snap) }, [snap])

  useImperativeHandle(
    ref,
    () => ({
      fit: () => engineRef.current?.fit(),
      fitSelection: () => engineRef.current?.fitSelection(),
      zoomBy: (k) => engineRef.current?.zoomBy(k),
      unpinAll: () => engineRef.current?.unpinAll(),
    }),
    [],
  )

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
