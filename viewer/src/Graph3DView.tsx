import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'

export type DemoNodeType = 'memory' | 'entity' | 'session' | 'exchange' | 'merkle'

export interface DemoNode {
  id: string
  type: DemoNodeType
  label: string
  tags: string[]
  relatedIds: string[]
  payload?: unknown
}

export interface DemoEdge {
  source: string
  target: string
  type: string
  label?: string
  evidenceMemoryId?: string
  cosineSimilarity?: number
  reason?: string
}

export interface DemoGraph {
  nodes: DemoNode[]
  edges: DemoEdge[]
}

export type GraphBackground = 'midnight' | 'paper' | 'matrix' | 'contrast'

export interface GraphViewOptions {
  background: GraphBackground
  zoom: number
  panX: number
  panY: number
  fitMode: 'all' | 'selected'
  fitNonce: number
  showGrid: boolean
}

import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const BACKGROUNDS: Record<GraphBackground, { color: number; fog: number | null; label: string }> = {
  midnight: { color: 0x0f172a, fog: 0x0f172a, label: '#f8fafc' },
  paper: { color: 0xf8fafc, fog: null, label: '#111827' },
  matrix: { color: 0x001b12, fog: 0x001b12, label: '#d1fae5' },
  contrast: { color: 0x050505, fog: null, label: '#ffffff' },
}

const COLORS: Record<DemoNodeType, number> = {
  memory: 0x2f80ed,
  entity: 0xd19a2a,
  session: 0x16a085,
  exchange: 0x7c3aed,
  merkle: 0xe11d48,
}

const EDGE_COLORS: Record<string, number> = {
  relation: 0x8b93a7,
  similarity: 0x30b981,
  contains: 0x2563eb,
  merkle_root: 0xe11d48,
  context: 0x8b5cf6,
  prompt: 0x16a085,
  response: 0xf97316,
  contradiction: 0xdc2626,
}

function stableHash(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function snap(val: number, step: number): number {
  return Math.round(val / step) * step
}

function nodePosition(node: DemoNode, index: number, total: number): THREE.Vector3 {
  const GRID = 16
  const pos = new THREE.Vector3()
  if (node.type === 'merkle') pos.set(0, 96, 0)
  else if (node.type === 'session') pos.set(0, 48, 0)
  else {
    const hash = stableHash(node.id)
    const ring = node.type === 'exchange' ? 48 : node.type === 'entity' ? 80 : 112
    const angle = ((hash % 10000) / 10000) * Math.PI * 2 + (index / Math.max(total, 1)) * 0.5
    const y =
      node.type === 'exchange'
        ? 16
        : node.type === 'entity'
          ? -16 + ((hash >> 4) % 48)
          : -48 + ((hash >> 5) % 96)
    pos.set(Math.cos(angle) * ring, y, Math.sin(angle) * ring)
  }
  
  pos.x = snap(pos.x, GRID)
  pos.y = snap(pos.y, GRID)
  pos.z = snap(pos.z, GRID)
  return pos
}

function makeLabel(text: string, color = '#f8fafc', scale = 1): THREE.Sprite {
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')
  canvas.width = 512
  canvas.height = 128
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height)
    context.font = '600 34px system-ui, sans-serif'
    context.textBaseline = 'middle'
    const clipped = text.length > 32 ? `${text.slice(0, 29)}...` : text
    const width = Math.min(context.measureText(clipped).width + 28, 500)
    context.fillStyle = 'rgba(15, 23, 42, 0.82)'
    context.strokeStyle = 'rgba(148, 163, 184, 0.65)'
    context.lineWidth = 2
    context.beginPath()
    context.roundRect((canvas.width - width) / 2, 32, width, 64, 12)
    context.fill()
    context.stroke()
    context.fillStyle = color
    context.textAlign = 'center'
    context.fillText(clipped, canvas.width / 2, canvas.height / 2 + 2)
  }
  const texture = new THREE.CanvasTexture(canvas)
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false })
  const sprite = new THREE.Sprite(material)
  sprite.scale.set(42 * scale, 10 * scale, 1)
  return sprite
}

export function Graph3DView({
  graph,
  selectedNodeId,
  selectedEdgeKey,
  options,
  onSelectNode,
  onSelectEdge,
}: {
  graph: DemoGraph
  selectedNodeId: string | null
  selectedEdgeKey: string | null
  options: GraphViewOptions
  onSelectNode: (node: DemoNode) => void
  onSelectEdge: (edge: DemoEdge) => void
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const selectedRef = useRef<string | null>(selectedNodeId)

  const relatedToSelected = useMemo(() => {
    if (!selectedNodeId) return new Set<string>()
    const selected = graph.nodes.find((node) => node.id === selectedNodeId)
    const ids = new Set<string>([selectedNodeId, ...(selected?.relatedIds ?? [])])
    for (const edge of graph.edges) {
      if (edge.source === selectedNodeId) ids.add(edge.target)
      if (edge.target === selectedNodeId) ids.add(edge.source)
    }
    return ids
  }, [graph, selectedNodeId])

  useEffect(() => {
    selectedRef.current = selectedNodeId
  }, [selectedNodeId])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    host.innerHTML = ''

    const scene = new THREE.Scene()
    const background = BACKGROUNDS[options.background]
    scene.background = new THREE.Color(background.color)
    scene.fog = background.fog === null ? null : new THREE.Fog(background.fog, 150, 420)

    const camera = new THREE.PerspectiveCamera(52, host.clientWidth / Math.max(host.clientHeight, 1), 0.1, 1200)
    camera.position.set(0, 74, 210)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(host.clientWidth, host.clientHeight)
    host.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05

    if (options.showGrid) {
      const GRID = 16
      const SIZE = GRID * 16 // 256
      const DIVISIONS = 16
      const gridGroup = new THREE.Group()
      
      const addGrid = (grid: THREE.GridHelper) => {
        const mat = grid.material as THREE.Material
        mat.transparent = true
        mat.opacity = 0.15
        gridGroup.add(grid)
      }

      for (let y = -SIZE/2; y <= SIZE/2; y += GRID) {
        const grid = new THREE.GridHelper(SIZE, DIVISIONS, 0x475569, 0x1e293b)
        grid.position.y = y
        addGrid(grid)
      }
      
      for (let z = -SIZE/2; z <= SIZE/2; z += GRID) {
        const grid = new THREE.GridHelper(SIZE, DIVISIONS, 0x475569, 0x1e293b)
        grid.rotation.x = Math.PI / 2
        grid.position.z = z
        addGrid(grid)
      }

      scene.add(gridGroup)
    }

    scene.add(new THREE.AmbientLight(0xffffff, 0.75))
    const key = new THREE.DirectionalLight(0xffffff, 1.2)
    key.position.set(40, 90, 80)
    scene.add(key)

    const positions = new Map<string, THREE.Vector3>()
    graph.nodes.forEach((node, index) => positions.set(node.id, nodePosition(node, index, graph.nodes.length)))

    const nodeObjects = new Map<string, THREE.Mesh>()
    const labelObjects = new Map<string, THREE.Sprite>()
    const edgeObjects: Array<THREE.Line> = []
    const raycaster = new THREE.Raycaster()
    raycaster.params.Line = { threshold: 5 }
    const pointer = new THREE.Vector2()

    for (const edge of graph.edges) {
      const source = positions.get(edge.source)
      const target = positions.get(edge.target)
      if (!source || !target) continue
      const edgeKey = `${edge.source}->${edge.target}:${edge.type}:${edge.label ?? ''}`
      const selected = selectedEdgeKey === edgeKey
      const geometry = new THREE.BufferGeometry().setFromPoints([source, target])
      const material = new THREE.LineBasicMaterial({
        color: EDGE_COLORS[edge.type] ?? 0x64748b,
        transparent: true,
        opacity: selected ? 1.0 : edge.type === 'similarity' ? 0.5 : 0.8,
        blending: THREE.AdditiveBlending,
      })
      const line = new THREE.Line(geometry, material)
      line.userData.edge = edge
      scene.add(line)
      edgeObjects.push(line)
    }

    graph.nodes.forEach((node) => {
      const position = positions.get(node.id) ?? new THREE.Vector3()
      const radius =
        node.type === 'merkle' ? 5.8 : node.type === 'session' ? 5.2 : node.type === 'exchange' ? 4.8 : 3.8
      const geometry = new THREE.SphereGeometry(radius, 28, 20)
      const material = new THREE.MeshStandardMaterial({
        color: COLORS[node.type],
        roughness: 0.48,
        metalness: node.type === 'merkle' ? 0.42 : 0.18,
        emissive: COLORS[node.type],
        emissiveIntensity: selectedNodeId === node.id ? 0.45 : 0.11,
      })
      const mesh = new THREE.Mesh(geometry, material)
      mesh.position.copy(position)
      mesh.userData.nodeId = node.id
      scene.add(mesh)
      nodeObjects.set(node.id, mesh)

      const isLocal = selectedNodeId ? relatedToSelected.has(node.id) : node.type !== 'memory'
      const label = makeLabel(node.label, node.type === 'merkle' ? '#fecdd3' : background.label, isLocal ? 1.35 : 0.82)
      label.position.copy(position).add(new THREE.Vector3(0, radius + 7, 0))
      label.visible = isLocal
      scene.add(label)
      labelObjects.set(node.id, label)
    })

    const focusNode = (nodeId: string) => {
      const position = positions.get(nodeId)
      if (!position) return
      const neighbors = [...relatedToSelected].map((id) => positions.get(id)).filter(Boolean) as THREE.Vector3[]
      const center = neighbors.length
        ? neighbors.reduce((acc, item) => acc.add(item), new THREE.Vector3()).multiplyScalar(1 / neighbors.length)
        : position
      const distance = Math.max(42, 104 / options.zoom)
      const offset = new THREE.Vector3(options.panX, 38 + options.panY, distance)
      camera.position.copy(center.clone().add(offset))
      controls.target.copy(center)
      camera.lookAt(center)
    }
    const fitGraph = () => {
      const allPositions = [...positions.values()]
      if (!allPositions.length) {
        camera.position.set(options.panX, 74 + options.panY, 210 / options.zoom)
        controls.target.set(0, 0, 0)
        camera.lookAt(0, 0, 0)
        return
      }
      const center = allPositions.reduce((acc, item) => acc.add(item), new THREE.Vector3()).multiplyScalar(1 / allPositions.length)
      const radius = Math.max(...allPositions.map((item) => item.distanceTo(center)), 76)
      camera.position.copy(center.clone().add(new THREE.Vector3(options.panX, 64 + options.panY, (radius * 2.05) / options.zoom)))
      controls.target.copy(center)
      camera.lookAt(center)
    }

    if (selectedNodeId && options.fitMode === 'selected') focusNode(selectedNodeId)
    else fitGraph()

    let activeDraggedNodeId: string | null = null
    const dragPlane = new THREE.Plane()
    let hasDragged = false
    const startPointerPos = new THREE.Vector2()

    const onPointerDown = (event: MouseEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect()
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
      startPointerPos.set(event.clientX, event.clientY)
      hasDragged = false

      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObjects([...nodeObjects.values()], false)[0]
      if (hit) {
        const nodeId = hit.object.userData.nodeId as string
        activeDraggedNodeId = nodeId
        controls.enabled = false

        const clickedNodePosition = positions.get(nodeId)
        if (clickedNodePosition) {
          const normal = new THREE.Vector3()
          camera.getWorldDirection(normal)
          normal.negate()
          dragPlane.setFromNormalAndCoplanarPoint(normal, clickedNodePosition)
        }
      }
    }

    const onPointerMove = (event: MouseEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect()
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1

      if (!activeDraggedNodeId) return

      const distance = startPointerPos.distanceTo(new THREE.Vector2(event.clientX, event.clientY))
      if (distance > 4) {
        hasDragged = true
      }

      raycaster.setFromCamera(pointer, camera)
      const intersectionPoint = new THREE.Vector3()
      if (raycaster.ray.intersectPlane(dragPlane, intersectionPoint)) {
        const GRID = 16
        const snappedX = Math.round(intersectionPoint.x / GRID) * GRID
        const snappedY = Math.round(intersectionPoint.y / GRID) * GRID
        const snappedZ = Math.round(intersectionPoint.z / GRID) * GRID
        const newPos = new THREE.Vector3(snappedX, snappedY, snappedZ)

        positions.set(activeDraggedNodeId, newPos)
        
        const mesh = nodeObjects.get(activeDraggedNodeId)
        if (mesh) mesh.position.copy(newPos)

        const label = labelObjects.get(activeDraggedNodeId)
        if (label) {
          const node = graph.nodes.find(n => n.id === activeDraggedNodeId)
          const radius = node?.type === 'merkle' ? 5.8 : node?.type === 'session' ? 5.2 : node?.type === 'exchange' ? 4.8 : 3.8
          label.position.copy(newPos).add(new THREE.Vector3(0, radius + 7, 0))
        }

        for (const line of edgeObjects) {
          const edge = line.userData.edge as DemoEdge
          if (edge.source === activeDraggedNodeId || edge.target === activeDraggedNodeId) {
            const srcPos = positions.get(edge.source)
            const tgtPos = positions.get(edge.target)
            if (srcPos && tgtPos) {
              line.geometry.setFromPoints([srcPos, tgtPos])
              line.geometry.attributes.position.needsUpdate = true
            }
          }
        }
      }
    }

    const onPointerUp = (event: MouseEvent) => {
      if (activeDraggedNodeId) {
        if (!hasDragged) {
          const node = graph.nodes.find((item) => item.id === activeDraggedNodeId)
          if (node) onSelectNode(node)
        }
        activeDraggedNodeId = null
        controls.enabled = true
      } else {
        const bounds = renderer.domElement.getBoundingClientRect()
        pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
        pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
        raycaster.setFromCamera(pointer, camera)
        const edgeHit = raycaster.intersectObjects(edgeObjects, false)[0]
        const edge = edgeHit?.object.userData.edge as DemoEdge | undefined
        if (edge) onSelectEdge(edge)
      }
    }

    renderer.domElement.addEventListener('mousedown', onPointerDown)
    renderer.domElement.addEventListener('mousemove', onPointerMove)
    renderer.domElement.addEventListener('mouseup', onPointerUp)

    const handleResize = () => {
      camera.aspect = host.clientWidth / Math.max(host.clientHeight, 1)
      camera.updateProjectionMatrix()
      renderer.setSize(host.clientWidth, host.clientHeight)
    }
    window.addEventListener('resize', handleResize)

    let animation = 0
    const animate = () => {
      controls.update()
      for (const [nodeId, mesh] of nodeObjects) {
        if (selectedRef.current) continue
        const base = positions.get(nodeId)
        if (base) mesh.position.copy(base)
        const label = labelObjects.get(nodeId)
        if (label && base) label.position.y = mesh.position.y + 9
      }
      renderer.render(scene, camera)
      animation = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      cancelAnimationFrame(animation)
      window.removeEventListener('resize', handleResize)
      renderer.domElement.removeEventListener('mousedown', onPointerDown)
      renderer.domElement.removeEventListener('mousemove', onPointerMove)
      renderer.domElement.removeEventListener('mouseup', onPointerUp)
      controls.dispose()
      renderer.dispose()
      host.innerHTML = ''
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh
        mesh.geometry?.dispose()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material?.dispose()
      })
    }
  }, [
    graph,
    onSelectNode,
    onSelectEdge,
    options.background,
    options.fitMode,
    options.fitNonce,
    options.panX,
    options.panY,
    options.zoom,
    options.showGrid,
    relatedToSelected,
    selectedEdgeKey,
    selectedNodeId,
  ])

  return <div className="graph3d-host" ref={hostRef} />
}
