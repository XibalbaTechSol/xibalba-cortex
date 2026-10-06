import { describe, expect, it } from 'vitest'
import type { GraphPayload } from '../api'
import {
  buildLanes,
  buildModel,
  countFacets,
  defaultFacets,
  edgeGroup,
  elideHash,
  filterModel,
  histogram,
  mergeFacets,
  parseServerTime,
  presetWindow,
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
