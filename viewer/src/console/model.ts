// Pure data model for the console: raw API payloads in, typed graph/timeline model out.
//
// Nothing in this file touches the network or React, so the rules that decide what the user
// sees -- how a node gets a time, what a facet hides, how the chain rail buckets -- can be unit
// tested against the exact payload shapes the local API returns.
//
// One rule governs the time model: a node only gets a time if the API supplied a real signal for
// it. `GET /api/memories` and `/api/memory/{id}` do not expose `created_at`, so a memory is
// timed by (1) `source.observed_at` when the writing agent set it, otherwise (2) the exchange it
// was part of. A memory with neither is UNTIMED and is reported as such -- never given a guessed
// timestamp.

import type { GraphEdge, GraphEdgeType, GraphNode, GraphPayload } from '../api'

export type NodeClass = 'memory' | 'entity' | 'session' | 'exchange' | 'merkle'
export const NODE_CLASSES: readonly NodeClass[] = ['memory', 'entity', 'session', 'exchange', 'merkle']

/** Facet grouping for edges. The five structural edge types toggle together. */
export type EdgeGroup = 'relation' | 'contradiction' | 'similarity' | 'structure'
export const EDGE_GROUPS: readonly EdgeGroup[] = ['relation', 'contradiction', 'similarity', 'structure']

/** `contains`, `prompt`, `response`, `context` and `merkle_root` are session structure; they toggle together. */
export function edgeGroup(type: GraphEdgeType): EdgeGroup {
  return type === 'relation' || type === 'contradiction' || type === 'similarity' ? type : 'structure'
}

export type TimeSource = 'observed' | 'exchange' | 'session' | 'evidence'

export interface CNode {
  id: string
  cls: NodeClass
  label: string
  status?: string
  evidenceClass?: string
  sourceKind?: string
  /** Epoch ms, or null when the API gave no usable timestamp. */
  time: number | null
  timeSource: TimeSource | null
  /** memory nodes: the bare memory id used by /api/memory/{id}. */
  memoryId?: string
  /** session nodes: external_session_id. */
  sessionId?: string
  /** merkle nodes: the server-computed root validity. */
  valid?: boolean
  degree: number
}

export interface CEdge {
  id: string
  source: string
  target: string
  type: GraphEdgeType
  group: EdgeGroup
  predicate?: string
  similarity?: number
  reason?: string
  evidenceMemoryId?: string
}

export interface GraphModel {
  nodes: CNode[]
  edges: CEdge[]
  byId: Map<string, CNode>
  /** Min and max timed node, or null when nothing is timed. */
  extent: [number, number] | null
  timed: number
  untimed: number
}

/** What `/api/memories` can tell us about a memory that the graph payload cannot. */
export interface MemoryTimeInfo {
  observedAt?: string | null
  sessionId?: string | null
}

/**
 * The API emits two timestamp dialects: "YYYY-MM-DD HH:MM:SS" from SQLite (UTC, no zone marker)
 * and ISO-8601 with a Z. A bare SQLite string must be read as UTC, not local time -- `new Date`
 * on it would silently shift every mark by the viewer's offset.
 */
export function parseServerTime(value: string | null | undefined): number | null {
  if (!value) return null
  const text = value.trim()
  if (!text) return null
  const bareSqlite = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$/.test(text)
  const ms = Date.parse(bareSqlite ? `${text.replace(' ', 'T')}Z` : text)
  return Number.isFinite(ms) ? ms : null
}

function stripPrefix(id: string, prefix: string): string | undefined {
  return id.startsWith(prefix) ? id.slice(prefix.length) : undefined
}

export function buildModel(payload: GraphPayload, memoryInfo: ReadonlyMap<string, MemoryTimeInfo> = new Map()): GraphModel {
  const nodes: CNode[] = payload.nodes.map((raw: GraphNode) => {
    const cls = raw.type as NodeClass
    const node: CNode = {
      id: raw.id,
      cls,
      label: raw.label,
      status: raw.status,
      evidenceClass: raw.evidence_class,
      sourceKind: raw.source_kind,
      time: null,
      timeSource: null,
      degree: 0,
    }
    if (cls === 'memory') node.memoryId = stripPrefix(raw.id, 'memory:')
    if (cls === 'session') node.sessionId = stripPrefix(raw.id, 'session:')
    if (cls === 'merkle') node.valid = raw.valid
    return node
  })
  const byId = new Map(nodes.map((n) => [n.id, n]))

  const edges: CEdge[] = payload.edges
    .filter((e: GraphEdge) => byId.has(e.source) && byId.has(e.target))
    .map((e: GraphEdge, index) => ({
      id: `${e.type}:${e.source}>${e.target}:${index}`,
      source: e.source,
      target: e.target,
      type: e.type,
      group: edgeGroup(e.type),
      predicate: e.predicate,
      similarity: e.cosine_similarity,
      reason: e.reason,
      evidenceMemoryId: e.evidence_memory_id,
    }))

  for (const edge of edges) {
    const a = byId.get(edge.source)
    const b = byId.get(edge.target)
    if (a) a.degree += 1
    if (b) b.degree += 1
  }

  // --- time resolution, in dependency order ------------------------------------------------------
  // 1. exchanges and sessions carry their own timestamps
  for (const raw of payload.nodes) {
    const node = byId.get(raw.id)
    if (!node) continue
    if (node.cls === 'exchange') {
      node.time = parseServerTime(raw.timestamp)
      node.timeSource = node.time === null ? null : 'exchange'
    } else if (node.cls === 'session') {
      node.time = parseServerTime(raw.started_at)
      node.timeSource = node.time === null ? null : 'session'
    }
  }

  // 2. a memory is timed by its own observed_at, else the earliest exchange it belongs to
  const exchangeTimes = new Map<string, number[]>()
  for (const edge of edges) {
    if (edge.type !== 'prompt' && edge.type !== 'response' && edge.type !== 'context') continue
    const exchange = byId.get(edge.source)
    if (!exchange || exchange.cls !== 'exchange' || exchange.time === null) continue
    const list = exchangeTimes.get(edge.target) ?? []
    list.push(exchange.time)
    exchangeTimes.set(edge.target, list)
  }
  for (const node of nodes) {
    if (node.cls !== 'memory') continue
    const observed = node.memoryId ? parseServerTime(memoryInfo.get(node.memoryId)?.observedAt) : null
    if (observed !== null) {
      node.time = observed
      node.timeSource = 'observed'
      continue
    }
    const viaExchange = exchangeTimes.get(node.id)
    if (viaExchange && viaExchange.length > 0) {
      node.time = Math.min(...viaExchange)
      node.timeSource = 'exchange'
    }
  }

  // 3. a merkle root takes its session's time; an entity takes its earliest evidence memory's
  for (const edge of edges) {
    if (edge.type !== 'merkle_root') continue
    const session = byId.get(edge.source)
    const root = byId.get(edge.target)
    if (session?.cls === 'session' && root?.cls === 'merkle' && session.time !== null) {
      root.time = session.time
      root.timeSource = 'session'
    }
  }
  for (const edge of edges) {
    if (edge.type !== 'relation' || !edge.evidenceMemoryId) continue
    const evidence = byId.get(`memory:${edge.evidenceMemoryId}`)
    if (!evidence || evidence.time === null) continue
    for (const endId of [edge.source, edge.target]) {
      const entity = byId.get(endId)
      if (entity?.cls !== 'entity') continue
      if (entity.time === null || evidence.time < entity.time) {
        entity.time = evidence.time
        entity.timeSource = 'evidence'
      }
    }
  }

  let min = Infinity
  let max = -Infinity
  let timed = 0
  for (const node of nodes) {
    if (node.time === null) continue
    timed += 1
    if (node.time < min) min = node.time
    if (node.time > max) max = node.time
  }
  return {
    nodes,
    edges,
    byId,
    extent: timed > 0 ? [min, max] : null,
    timed,
    untimed: nodes.length - timed,
  }
}

// --- facets and the time window --------------------------------------------------------------------

export interface TimeWindow {
  from: number
  to: number
}

export interface Facets {
  classes: Record<NodeClass, boolean>
  /** Memory status -> shown. A status absent from this map is shown. */
  statuses: Record<string, boolean>
  /** Evidence class -> shown. */
  evidence: Record<string, boolean>
  edges: Record<EdgeGroup, boolean>
}

/** Statuses hidden until asked for: they are history, not current belief. */
const HIDDEN_BY_DEFAULT = new Set(['superseded', 'forgotten'])

export function defaultFacets(model: GraphModel): Facets {
  const statuses: Record<string, boolean> = {}
  const evidence: Record<string, boolean> = {}
  for (const node of model.nodes) {
    if (node.cls !== 'memory') continue
    if (node.status) statuses[node.status] = !HIDDEN_BY_DEFAULT.has(node.status)
    if (node.evidenceClass) evidence[node.evidenceClass] = true
  }
  return {
    classes: { memory: true, entity: true, session: true, exchange: true, merkle: true },
    statuses,
    evidence,
    edges: { relation: true, contradiction: true, similarity: true, structure: true },
  }
}

/**
 * Fold freshly-derived defaults into the user's current facets after a reload. Anything the user
 * already has a value for is kept; only values for statuses/evidence classes never seen before
 * are taken from the defaults. Without this, changing the similarity threshold (which refetches)
 * would silently reset every filter the user had set.
 */
export function mergeFacets(prev: Facets, next: Facets): Facets {
  const fold = (current: Record<string, boolean>, fresh: Record<string, boolean>) => {
    const out: Record<string, boolean> = {}
    for (const key of Object.keys(fresh)) out[key] = key in current ? current[key] : fresh[key]
    return out
  }
  return {
    classes: prev.classes,
    statuses: fold(prev.statuses, next.statuses),
    evidence: fold(prev.evidence, next.evidence),
    edges: prev.edges,
  }
}

export function isNodeVisible(node: CNode, facets: Facets, window: TimeWindow | null): boolean {
  if (!facets.classes[node.cls]) return false
  if (node.cls === 'memory') {
    if (node.status && facets.statuses[node.status] === false) return false
    if (node.evidenceClass && facets.evidence[node.evidenceClass] === false) return false
  }
  // Untimed nodes are never filtered out by the window: hiding what we cannot place in time
  // would make the window look like it removed things it has no basis to remove.
  if (window && node.time !== null && (node.time < window.from || node.time > window.to)) return false
  return true
}

export interface VisibleGraph {
  nodes: CNode[]
  edges: CEdge[]
}

export function filterModel(model: GraphModel, facets: Facets, window: TimeWindow | null): VisibleGraph {
  const nodes = model.nodes.filter((n) => isNodeVisible(n, facets, window))
  const visible = new Set(nodes.map((n) => n.id))
  const edges = model.edges.filter((e) => facets.edges[e.group] && visible.has(e.source) && visible.has(e.target))
  return { nodes, edges }
}

export interface FacetCounts {
  classes: Record<NodeClass, number>
  statuses: Record<string, number>
  evidence: Record<string, number>
  edges: Record<EdgeGroup, number>
}

export function countFacets(model: GraphModel): FacetCounts {
  const counts: FacetCounts = {
    classes: { memory: 0, entity: 0, session: 0, exchange: 0, merkle: 0 },
    statuses: {},
    evidence: {},
    edges: { relation: 0, contradiction: 0, similarity: 0, structure: 0 },
  }
  for (const node of model.nodes) {
    counts.classes[node.cls] += 1
    if (node.cls !== 'memory') continue
    if (node.status) counts.statuses[node.status] = (counts.statuses[node.status] ?? 0) + 1
    if (node.evidenceClass) counts.evidence[node.evidenceClass] = (counts.evidence[node.evidenceClass] ?? 0) + 1
  }
  for (const edge of model.edges) counts.edges[edge.group] += 1
  return counts
}

// --- chain rail ------------------------------------------------------------------------------------

export type RangePreset = '1h' | '24h' | '7d' | '30d' | 'all'

const PRESET_MS: Record<Exclude<RangePreset, 'all'>, number> = {
  '1h': 3_600_000,
  '24h': 86_400_000,
  '7d': 7 * 86_400_000,
  '30d': 30 * 86_400_000,
}

/** Presets are relative to NOW, not to the newest datum: "7d" must mean the last seven days. */
export function presetWindow(preset: RangePreset, now: number): TimeWindow | null {
  if (preset === 'all') return null
  return { from: now - PRESET_MS[preset], to: now }
}

export interface Histogram {
  from: number
  to: number
  buckets: number[]
  max: number
}

/**
 * Write density over time. Counts only nodes that are genuine events -- memories and exchanges --
 * so sessions, entities and roots (which are derived from them) don't inflate a bucket.
 */
export function histogram(model: GraphModel, bucketCount: number, extent: [number, number] | null = model.extent): Histogram | null {
  if (!extent || bucketCount < 1) return null
  const [from, to] = extent
  const span = Math.max(1, to - from)
  const buckets = new Array<number>(bucketCount).fill(0)
  for (const node of model.nodes) {
    if (node.time === null || (node.cls !== 'memory' && node.cls !== 'exchange')) continue
    if (node.time < from || node.time > to) continue
    const index = Math.min(bucketCount - 1, Math.floor(((node.time - from) / span) * bucketCount))
    buckets[index] += 1
  }
  return { from, to, buckets, max: Math.max(1, ...buckets) }
}

// --- timeline lanes --------------------------------------------------------------------------------

export interface Mark {
  nodeId: string
  cls: 'exchange' | 'memory'
  time: number
  status?: string
}

export interface Lane {
  session: CNode
  start: number
  /** null = the session is still open; the lane runs to "now". */
  end: number | null
  marks: Mark[]
  root: CNode | null
}

export function buildLanes(
  model: GraphModel,
  endedAt: ReadonlyMap<string, string | null> = new Map(),
  memoryInfo: ReadonlyMap<string, MemoryTimeInfo> = new Map(),
): Lane[] {
  const lanes = new Map<string, Lane>()
  for (const node of model.nodes) {
    if (node.cls !== 'session' || node.time === null) continue
    const ended = node.sessionId ? parseServerTime(endedAt.get(node.sessionId)) : null
    lanes.set(node.id, { session: node, start: node.time, end: ended, marks: [], root: null })
  }

  const seen = new Set<string>()
  const add = (laneId: string, node: CNode | undefined) => {
    if (!node || node.time === null || (node.cls !== 'exchange' && node.cls !== 'memory')) return
    const lane = lanes.get(laneId)
    if (!lane || seen.has(`${laneId}|${node.id}`)) return
    seen.add(`${laneId}|${node.id}`)
    lane.marks.push({ nodeId: node.id, cls: node.cls, time: node.time, status: node.status })
  }

  for (const edge of model.edges) {
    if (edge.type === 'contains') add(edge.source, model.byId.get(edge.target))
    if (edge.type === 'merkle_root') {
      const lane = lanes.get(edge.source)
      const root = model.byId.get(edge.target)
      if (lane && root?.cls === 'merkle') lane.root = root
    }
  }
  // memories: placed in a lane by the session that wrote them, or the exchange they belong to
  const exchangeSession = new Map<string, string>()
  for (const edge of model.edges) if (edge.type === 'contains') exchangeSession.set(edge.target, edge.source)
  for (const node of model.nodes) {
    if (node.cls !== 'memory') continue
    const writer = node.memoryId ? memoryInfo.get(node.memoryId)?.sessionId : null
    if (writer) add(`session:${writer}`, node)
  }
  for (const edge of model.edges) {
    if (edge.type !== 'prompt' && edge.type !== 'response' && edge.type !== 'context') continue
    const laneId = exchangeSession.get(edge.source)
    if (laneId) add(laneId, model.byId.get(edge.target))
  }

  const result = [...lanes.values()]
  for (const lane of result) {
    lane.marks.sort((a, b) => a.time - b.time)
    // a lane always spans at least its own marks, even if the session row says otherwise
    for (const mark of lane.marks) if (mark.time < lane.start) lane.start = mark.time
  }
  return result.sort((a, b) => b.start - a.start)
}

// --- formatting ------------------------------------------------------------------------------------

const pad = (n: number) => String(n).padStart(2, '0')

/** "MM-DD HH:MM" in the viewer's local zone: compact enough for a rail label or an axis tick. */
export function shortStamp(ms: number): string {
  const d = new Date(ms)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function shortDay(ms: number): string {
  const d = new Date(ms)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Elide the middle of a hash, never the prefix: `sha256:9c4e3b…a71f`. */
export function elideHash(hash: string, head = 6, tail = 4): string {
  const colon = hash.indexOf(':')
  const prefix = colon >= 0 ? hash.slice(0, colon + 1) : ''
  const body = colon >= 0 ? hash.slice(colon + 1) : hash
  if (body.length <= head + tail + 1) return hash
  return `${prefix}${body.slice(0, head)}…${body.slice(-tail)}`
}
