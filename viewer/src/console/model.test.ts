import { describe, expect, it } from 'vitest'
import type { GraphPayload } from '../api'
import {
  buildLanes,
  buildModel,
  changedFacetCount,
  countFacets,
  defaultFacets,
  edgeGroup,
  elideHash,
  filterModel,
  thinTicks,
  histogram,
  mergeFacets,
  parseServerTime,
  presetWindow,
  isEdgeVisible,
  selectionHidden,
} from './model'

// The fixture mirrors what GET /api/graph actually returned from a live local API (one node per
// class, the real id prefixes, and the real timestamp dialects), not an idealised shape.
const T0 = Date.parse('2026-09-30T11:00:00Z')
const iso = (offsetMin: number) => new Date(T0 + offsetMin * 60_000).toISOString().replace('.000Z', 'Z')
const sqlite = (offsetMin: number) => new Date(T0 + offsetMin * 60_000).toISOString().slice(0, 19).replace('T', ' ')

const payload: GraphPayload = {
  nodes: [
    { id: 'session:s1', type: 'session', label: 'Session s1', status: 'closed', started_at: sqlite(0) },
    { id: 'exchange:e1', type: 'exchange', label: 'Exchange 0', timestamp: iso(10) },
    { id: 'exchange:e2', type: 'exchange', label: 'Exchange 1', timestamp: iso(40) },
    { id: 'memory:m-observed', type: 'memory', label: 'observed', status: 'confirmed', evidence_class: 'policy', source_kind: 'direct_user' },
    { id: 'memory:m-ctx', type: 'memory', label: 'via exchange', status: 'active', evidence_class: 'observed_event', source_kind: 'direct_model_response' },
    { id: 'memory:m-both', type: 'memory', label: 'in two exchanges', status: 'confirmed', evidence_class: 'inference', source_kind: 'explicit_memory' },
    { id: 'memory:m-none', type: 'memory', label: 'untimed', status: 'candidate', evidence_class: 'inference', source_kind: 'imported_document' },
    { id: 'memory:m-old', type: 'memory', label: 'superseded', status: 'superseded', evidence_class: 'policy', source_kind: 'imported_document' },
    { id: 'entity:x', type: 'entity', label: 'store.py', entity_type: 'unknown', agent_id: '' },
    { id: 'entity:y', type: 'entity', label: 'domain root', entity_type: 'unknown', agent_id: '' },
    { id: 'entity:orphan', type: 'entity', label: 'no evidence', entity_type: 'unknown', agent_id: '' },
    { id: 'merkle:sha256:abc', type: 'merkle', label: 'Root sha256:a', valid: true },
  ],
  edges: [
    { source: 'session:s1', target: 'exchange:e1', type: 'contains' },
    { source: 'session:s1', target: 'exchange:e2', type: 'contains' },
    { source: 'exchange:e1', target: 'memory:m-ctx', type: 'prompt' },
    { source: 'exchange:e1', target: 'memory:m-both', type: 'context' },
    { source: 'exchange:e2', target: 'memory:m-both', type: 'response' },
    { source: 'session:s1', target: 'merkle:sha256:abc', type: 'merkle_root' },
    { source: 'entity:x', target: 'entity:y', type: 'relation', predicate: 'computes', evidence_memory_id: 'm-observed' },
    { source: 'memory:m-observed', target: 'memory:m-none', type: 'contradiction', predicate: 'contradicts', reason: 'conflict' },
    { source: 'memory:m-ctx', target: 'memory:m-observed', type: 'similarity', cosine_similarity: 0.9 },
    // an edge whose endpoint was dropped by the server-side sample must not survive into the model
    { source: 'memory:m-ctx', target: 'memory:not-in-sample', type: 'similarity', cosine_similarity: 0.8 },
  ],
}

const info = new Map([['m-observed', { observedAt: iso(25), sessionId: 's1' }]])

describe('parseServerTime', () => {
  it('reads a bare SQLite timestamp as UTC, not local time', () => {
    expect(parseServerTime('2026-09-30 11:00:00')).toBe(Date.parse('2026-09-30T11:00:00Z'))
  })
  it('reads ISO-8601 with a zone marker', () => {
    expect(parseServerTime('2026-09-30T11:00:03Z')).toBe(Date.parse('2026-09-30T11:00:03Z'))
  })
  it('returns null for missing or malformed values rather than guessing', () => {
    expect(parseServerTime(null)).toBeNull()
    expect(parseServerTime(undefined)).toBeNull()
    expect(parseServerTime('')).toBeNull()
    expect(parseServerTime('not a date')).toBeNull()
  })
})

describe('buildModel: time resolution', () => {
  const model = buildModel(payload, info)
  const node = (id: string) => model.byId.get(id)!

  it('gives exchanges and sessions their own timestamps', () => {
    expect(node('exchange:e1').time).toBe(T0 + 10 * 60_000)
    expect(node('exchange:e1').timeSource).toBe('exchange')
    expect(node('session:s1').time).toBe(T0)
    expect(node('session:s1').timeSource).toBe('session')
  })

  it('prefers source.observed_at over an exchange for a memory', () => {
    expect(node('memory:m-observed').time).toBe(T0 + 25 * 60_000)
    expect(node('memory:m-observed').timeSource).toBe('observed')
  })

  it('times a memory by the exchange it belongs to when it has no observed_at', () => {
    expect(node('memory:m-ctx').time).toBe(T0 + 10 * 60_000)
    expect(node('memory:m-ctx').timeSource).toBe('exchange')
  })

  it('uses the EARLIEST exchange when a memory is in several', () => {
    expect(node('memory:m-both').time).toBe(T0 + 10 * 60_000)
  })

  it('leaves a memory with no signal untimed instead of inventing a time', () => {
    expect(node('memory:m-none').time).toBeNull()
    expect(node('memory:m-none').timeSource).toBeNull()
  })

  it('times an entity by its earliest evidence memory', () => {
    expect(node('entity:x').time).toBe(T0 + 25 * 60_000)
    expect(node('entity:x').timeSource).toBe('evidence')
    expect(node('entity:y').time).toBe(T0 + 25 * 60_000)
  })

  it('leaves an entity with no evidence untimed', () => {
    expect(node('entity:orphan').time).toBeNull()
  })

  it('times a merkle root by its session', () => {
    expect(node('merkle:sha256:abc').time).toBe(T0)
    expect(node('merkle:sha256:abc').valid).toBe(true)
  })

  it('extracts bare ids from the server prefixes', () => {
    expect(node('memory:m-observed').memoryId).toBe('m-observed')
    expect(node('session:s1').sessionId).toBe('s1')
  })

  it('drops edges whose endpoints are not in the payload', () => {
    expect(model.edges.some((e) => e.target === 'memory:not-in-sample')).toBe(false)
    expect(model.edges).toHaveLength(payload.edges.length - 1)
  })

  it('reports timed and untimed counts that add up, and the extent', () => {
    expect(model.timed + model.untimed).toBe(model.nodes.length)
    expect(model.untimed).toBe(3) // m-none, m-old, entity:orphan
    expect(model.extent).toEqual([T0, T0 + 40 * 60_000])
  })

  it('counts degree from the surviving edges only', () => {
    expect(node('session:s1').degree).toBe(3)
  })
})

describe('edgeGroup', () => {
  it('keeps the three semantic edge types and folds the rest into structure', () => {
    expect(edgeGroup('relation')).toBe('relation')
    expect(edgeGroup('contradiction')).toBe('contradiction')
    expect(edgeGroup('similarity')).toBe('similarity')
    for (const t of ['contains', 'prompt', 'response', 'context', 'merkle_root'] as const) {
      expect(edgeGroup(t)).toBe('structure')
    }
  })
})

describe('facets and the time window', () => {
  const model = buildModel(payload, info)

  it('hides superseded and forgotten memories by default but shows every other status', () => {
    const facets = defaultFacets(model)
    expect(facets.statuses.superseded).toBe(false)
    expect(facets.statuses.confirmed).toBe(true)
    expect(facets.statuses.candidate).toBe(true)
    const visible = filterModel(model, facets, null).nodes.map((n) => n.id)
    expect(visible).not.toContain('memory:m-old')
    expect(visible).toContain('memory:m-none')
  })

  it('removes a node class and every edge that touches it', () => {
    const facets = defaultFacets(model)
    facets.classes.exchange = false
    const { nodes, edges } = filterModel(model, facets, null)
    expect(nodes.some((n) => n.cls === 'exchange')).toBe(false)
    expect(edges.some((e) => e.type === 'prompt' || e.type === 'contains')).toBe(false)
  })

  it('hides an edge group without hiding its nodes', () => {
    const facets = defaultFacets(model)
    facets.edges.structure = false
    const { nodes, edges } = filterModel(model, facets, null)
    expect(edges.some((e) => e.group === 'structure')).toBe(false)
    expect(nodes.some((n) => n.cls === 'exchange')).toBe(true)
  })

  it('filters by evidence class', () => {
    const facets = defaultFacets(model)
    facets.evidence.policy = false
    const ids = filterModel(model, facets, null).nodes.map((n) => n.id)
    expect(ids).not.toContain('memory:m-observed')
  })

  it('windows timed nodes but never hides an untimed one', () => {
    const facets = defaultFacets(model)
    const win = { from: T0 + 30 * 60_000, to: T0 + 60 * 60_000 }
    const ids = filterModel(model, facets, win).nodes.map((n) => n.id)
    expect(ids).toContain('exchange:e2') // +40min, inside
    expect(ids).not.toContain('exchange:e1') // +10min, outside
    expect(ids).not.toContain('memory:m-observed') // +25min, outside
    expect(ids).toContain('memory:m-none') // untimed: never windowed away
    expect(ids).toContain('entity:orphan')
  })

  it('counts facets over the full model, not the filtered view', () => {
    const c = countFacets(model)
    expect(c.classes.memory).toBe(5)
    expect(c.classes.exchange).toBe(2)
    expect(c.statuses.superseded).toBe(1)
    expect(c.edges.structure).toBe(6)
    expect(c.edges.relation).toBe(1)
  })
})

describe('mergeFacets', () => {
  const model = buildModel(payload, info)

  it('keeps what the user toggled across a reload', () => {
    const prev = defaultFacets(model)
    prev.classes.entity = false
    prev.statuses.confirmed = false
    prev.edges.similarity = false
    const merged = mergeFacets(prev, defaultFacets(model))
    expect(merged.classes.entity).toBe(false)
    expect(merged.statuses.confirmed).toBe(false)
    expect(merged.edges.similarity).toBe(false)
  })

  it('adopts the default for a status it has never seen, and drops one that vanished', () => {
    const prev = defaultFacets(model)
    const next = defaultFacets(model)
    next.statuses.disputed = true
    delete next.statuses.candidate
    const merged = mergeFacets(prev, next)
    expect(merged.statuses.disputed).toBe(true)
    expect('candidate' in merged.statuses).toBe(false)
  })
})

describe('chain rail', () => {
  const model = buildModel(payload, info)

  it('buckets only memories and exchanges, not derived nodes', () => {
    const h = histogram(model, 4)!
    // timed memories (observed, ctx, both) + exchanges (e1, e2) = 5; session/entity/merkle excluded
    expect(h.buckets.reduce((a, b) => a + b, 0)).toBe(5)
    expect(h.from).toBe(T0)
    expect(h.to).toBe(T0 + 40 * 60_000)
  })

  it('puts a datum at the extent end in the last bucket, not past it', () => {
    const h = histogram(model, 4)!
    expect(h.buckets[3]).toBeGreaterThan(0)
  })

  it('returns null when nothing is timed', () => {
    const empty = buildModel({ nodes: [{ id: 'memory:a', type: 'memory', label: 'a' }], edges: [] })
    expect(empty.extent).toBeNull()
    expect(histogram(empty, 10)).toBeNull()
  })

  it('anchors range presets to now and lets "all" mean no window', () => {
    const now = Date.parse('2026-10-06T12:00:00Z')
    expect(presetWindow('all', now)).toBeNull()
    expect(presetWindow('7d', now)).toEqual({ from: now - 7 * 86_400_000, to: now })
    expect(presetWindow('1h', now)?.to).toBe(now)
  })
})

describe('buildLanes', () => {
  const model = buildModel(payload, info)
  const lanes = buildLanes(model, new Map([['s1', sqlite(60)]]), info)

  it('makes one lane per timed session with its server end time', () => {
    expect(lanes).toHaveLength(1)
    expect(lanes[0].start).toBe(T0)
    expect(lanes[0].end).toBe(T0 + 60 * 60_000)
  })

  it('places exchanges and exchange-linked memories in the lane, each once', () => {
    const ids = lanes[0].marks.map((m) => m.nodeId)
    expect(ids).toContain('exchange:e1')
    expect(ids).toContain('memory:m-ctx')
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('places a memory by the session that wrote it', () => {
    expect(lanes[0].marks.map((m) => m.nodeId)).toContain('memory:m-observed')
  })

  it('omits untimed memories rather than placing them at a guess', () => {
    expect(lanes[0].marks.map((m) => m.nodeId)).not.toContain('memory:m-none')
  })

  it('keeps marks in time order and attaches the merkle root', () => {
    const times = lanes[0].marks.map((m) => m.time)
    expect(times).toEqual([...times].sort((a, b) => a - b))
    expect(lanes[0].root?.valid).toBe(true)
  })

  it('treats a session with no end time as still open', () => {
    const open = buildLanes(model, new Map(), info)
    expect(open[0].end).toBeNull()
  })
})

describe('elideHash', () => {
  it('keeps the algorithm prefix and both ends', () => {
    expect(elideHash('sha256:9c4e3b7f21a0e5c88d4417fbb0325de9a71f')).toBe('sha256:9c4e3b…a71f')
  })
  it('leaves a short value untouched', () => {
    expect(elideHash('sha256:abcd')).toBe('sha256:abcd')
  })
})

describe('changedFacetCount', () => {
  const model = buildModel(payload, new Map())
  it('is zero at the defaults, so a fresh view shows no badge', () => {
    expect(changedFacetCount(defaultFacets(model), model)).toBe(0)
  })
  it('counts each switch that differs from its default', () => {
    const f = defaultFacets(model)
    f.classes.entity = false
    f.edges.similarity = false
    expect(changedFacetCount(f, model)).toBe(2)
  })
  it('counts turning a hidden-by-default status on as a change too', () => {
    const f = defaultFacets(model)
    expect(f.statuses.superseded).toBe(false)
    f.statuses.superseded = true
    expect(changedFacetCount(f, model)).toBe(1)
  })
  it('does not count a switch the user put back', () => {
    const f = defaultFacets(model)
    f.classes.entity = false
    f.classes.entity = true
    expect(changedFacetCount(f, model)).toBe(0)
  })
})

describe('memory time from the backend write time (created_at)', () => {
  const base = (nodes: GraphPayload['nodes'], edges: GraphPayload['edges'] = []): GraphPayload => ({ nodes, edges })
  const mem = (id: string, extra: Record<string, unknown> = {}) => ({ id: `memory:${id}`, type: 'memory' as const, label: id, status: 'active', evidence_class: 'observed_event', source_kind: 'direct_user', ...extra })

  it('times a memory by created_at and says it is the store write time, not the event time', () => {
    const m = buildModel(base([mem('a', { created_at: sqlite(5) })]))
    const n = m.byId.get('memory:a')!
    expect(n.time).toBe(T0 + 5 * 60_000)
    expect(n.timeSource).toBe('recorded')
    expect(m.untimed).toBe(0)
  })
  it('prefers the writer-supplied observed_at over created_at', () => {
    const n = buildModel(base([mem('a', { created_at: sqlite(50), observed_at: iso(7) })])).byId.get('memory:a')!
    expect(n.time).toBe(T0 + 7 * 60_000)
    expect(n.timeSource).toBe('observed')
  })
  it('prefers the exchange the memory was part of over created_at', () => {
    const nodes = [{ id: 'exchange:e', type: 'exchange' as const, label: 'x', timestamp: iso(12) }, mem('a', { created_at: sqlite(60) })]
    const n = buildModel(base(nodes, [{ source: 'exchange:e', target: 'memory:a', type: 'prompt' }])).byId.get('memory:a')!
    expect(n.time).toBe(T0 + 12 * 60_000)
    expect(n.timeSource).toBe('exchange')
  })
  it('reads created_at as UTC even though SQLite sends no zone marker', () => {
    const n = buildModel(base([mem('a', { created_at: '2026-09-30 11:00:00' })])).byId.get('memory:a')!
    expect(n.time).toBe(Date.parse('2026-09-30T11:00:00Z'))
  })
  it('still falls back to the paged listing for a backend that does not send created_at on nodes', () => {
    const n = buildModel(base([mem('a')]), new Map([['a', { createdAt: sqlite(9) }]])).byId.get('memory:a')!
    expect(n.time).toBe(T0 + 9 * 60_000)
    expect(n.timeSource).toBe('recorded')
  })
  it('leaves a memory with no signal at all untimed', () => {
    const m = buildModel(base([mem('a')]))
    expect(m.byId.get('memory:a')!.time).toBeNull()
    expect(m.untimed).toBe(1)
  })
})

describe('the No session lane', () => {
  const nodes: GraphPayload['nodes'] = [
    { id: 'session:s1', type: 'session', label: 's1', status: 'closed', started_at: sqlite(0) },
    { id: 'memory:in', type: 'memory', label: 'in', status: 'active', evidence_class: 'observed_event', source_kind: 'direct_user', created_at: sqlite(5), session_id: 's1' },
    { id: 'memory:loose', type: 'memory', label: 'loose', status: 'active', evidence_class: 'observed_event', source_kind: 'direct_user', created_at: sqlite(30) },
    { id: 'memory:untimed', type: 'memory', label: 'untimed', status: 'active', evidence_class: 'observed_event', source_kind: 'direct_user' },
  ]
  const lanes = buildLanes(buildModel({ nodes, edges: [] }))
  it('places a memory in the session the graph payload says wrote it', () => {
    expect(lanes.find((l) => l.session.id === 'session:s1')!.marks.map((m) => m.nodeId)).toEqual(['memory:in'])
  })
  it('gives timed memories that no session wrote a lane of their own instead of dropping them', () => {
    const none = lanes.find((l) => l.synthetic)!
    expect(none.marks.map((m) => m.nodeId)).toEqual(['memory:loose'])
  })
  it('does not place an untimed memory anywhere', () => {
    expect(lanes.flatMap((l) => l.marks).some((m) => m.nodeId === 'memory:untimed')).toBe(false)
  })
  it('has no such lane when every timed memory belongs to a session', () => {
    const only = buildLanes(buildModel({ nodes: nodes.filter((n) => n.id !== 'memory:loose'), edges: [] }))
    expect(only.some((l) => l.synthetic)).toBe(false)
  })
})

describe('exchange time', () => {
  it('uses the event time when there is one, and the store write time (labelled) when there is not', () => {
    const m = buildModel({
      nodes: [
        { id: 'exchange:a', type: 'exchange', label: 'a', timestamp: iso(3), created_at: sqlite(9) },
        { id: 'exchange:b', type: 'exchange', label: 'b', timestamp: null, created_at: sqlite(9) },
        { id: 'exchange:c', type: 'exchange', label: 'c', timestamp: null },
      ],
      edges: [],
    })
    expect(m.byId.get('exchange:a')).toMatchObject({ time: T0 + 3 * 60_000, timeSource: 'exchange' })
    expect(m.byId.get('exchange:b')).toMatchObject({ time: T0 + 9 * 60_000, timeSource: 'recorded' })
    expect(m.byId.get('exchange:c')).toMatchObject({ time: null, timeSource: null })
  })
})


describe('thinTicks', () => {
  const ticks = Array.from({ length: 10 }, (_, i) => i)
  it('keeps everything when there is room', () => {
    expect(thinTicks(ticks, 1000)).toEqual(ticks)
  })
  it('drops labels evenly when the axis is narrow, keeping the first', () => {
    const out = thinTicks(ticks, 280, 56) // room for 5
    expect(out).toEqual([0, 2, 4, 6, 8])
  })
  it('never returns fewer than one label, and keeps all when the width is unknown', () => {
    expect(thinTicks(ticks, 10).length).toBe(1)
    expect(thinTicks(ticks, 0)).toEqual(ticks)
  })
})


describe('finer facets', () => {
  const model = buildModel(payload, info)

  it('lists each session-structure edge type, each relation predicate and each memory source kind', () => {
    const f = defaultFacets(model)
    expect(Object.keys(f.edgeTypes).sort()).toEqual(['contains', 'context', 'merkle_root', 'prompt', 'response'])
    expect(Object.keys(f.predicates)).toEqual(['computes'])
    expect(Object.keys(f.sources).sort()).toEqual(['direct_model_response', 'direct_user', 'explicit_memory', 'imported_document'])
  })

  it('hides one structure edge type without hiding the others', () => {
    const f = defaultFacets(model)
    f.edgeTypes.prompt = false
    const types = new Set(filterModel(model, f, null).edges.map((e) => e.type))
    expect(types.has('prompt')).toBe(false)
    expect(types.has('response')).toBe(true)
    expect(types.has('contains')).toBe(true)
  })

  it('hides a relation by predicate, and a memory by source kind', () => {
    const f = defaultFacets(model)
    f.predicates.computes = false
    expect(filterModel(model, f, null).edges.some((e) => e.type === 'relation')).toBe(false)
    const g = defaultFacets(model)
    g.sources.direct_user = false
    expect(filterModel(model, g, null).nodes.some((n) => n.id === 'memory:m-observed')).toBe(false)
  })

  it('counts them, and counts a switch away from default as a changed facet', () => {
    const c = countFacets(model)
    expect(c.edgeTypes.contains).toBe(2)
    expect(c.predicates.computes).toBe(1)
    expect(c.sources.imported_document).toBe(2)
    const f = defaultFacets(model)
    f.edgeTypes.prompt = false
    f.sources.direct_user = false
    expect(changedFacetCount(f, model)).toBe(2)
  })

  it('keeps them across a reload, and adopts ones never seen', () => {
    const prev = defaultFacets(model)
    prev.edgeTypes.prompt = false
    const next = defaultFacets(model)
    next.sources.brand_new = true
    const merged = mergeFacets(prev, next)
    expect(merged.edgeTypes.prompt).toBe(false)
    expect(merged.sources.brand_new).toBe(true)
  })

  it('treats facets saved before these existed as everything shown', () => {
    const old = defaultFacets(model)
    // an object from before the fields were added
    const legacy = { classes: old.classes, statuses: old.statuses, evidence: old.evidence, edges: old.edges } as unknown as ReturnType<typeof defaultFacets>
    expect(model.edges.every((e) => isEdgeVisible(e, legacy) || !legacy.edges[e.group])).toBe(true)
  })
})

describe('selectionHidden', () => {
  const model = buildModel(payload, info)
  it('is false with no selection, and false while the selection is drawn', () => {
    const visible = filterModel(model, defaultFacets(model), null)
    expect(selectionHidden(model, visible, null)).toBe(false)
    expect(selectionHidden(model, visible, 'memory:m-observed')).toBe(false)
  })
  it('is true when a filter removes the selected node', () => {
    const f = defaultFacets(model)
    f.classes.memory = false
    expect(selectionHidden(model, filterModel(model, f, null), 'memory:m-observed')).toBe(true)
  })
  it('is true when a filter removes the selected edge, and false for an id the model does not know', () => {
    const edge = model.edges.find((e) => e.type === 'relation')!
    const f = defaultFacets(model)
    f.edges.relation = false
    expect(selectionHidden(model, filterModel(model, f, null), edge.id)).toBe(true)
    expect(selectionHidden(model, filterModel(model, f, null), 'memory:not-here')).toBe(false)
  })
})
