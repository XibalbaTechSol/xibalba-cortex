import { describe, expect, it } from 'vitest'
import { computeSynapticSpectrum, formatSpectrumDate } from './ChainRail'
import { NO_EVIDENCE, type GraphModel, type CNode } from './model'
import type { Invocation } from '../api'

describe('formatSpectrumDate', () => {
  it('formats dates as M/D HH:mm:ss', () => {
    const t = new Date(2026, 10, 16, 8, 35, 20).getTime()
    expect(formatSpectrumDate(t)).toBe('11/16 08:35:20')
  })
})

describe('computeSynapticSpectrum', () => {
  const from = 1000
  const to = 5000
  const extent: [number, number] = [from, to]

  it('returns null if extent is missing or buckets < 1', () => {
    expect(computeSynapticSpectrum(null, [], 0, extent)).toBeNull()
    expect(computeSynapticSpectrum(null, [], 72, null)).toBeNull()
  })

  it('buckets exchanges, tools, and anchors correctly across time', () => {
    const makeNode = (id: string, cls: CNode['cls'], time: number): CNode => ({
      id,
      cls,
      label: id,
      time,
      timeSource: 'observed',
      degree: 1,
      evidence: NO_EVIDENCE,
    })

    const mockModel: GraphModel = {
      nodes: [
        makeNode('ex-1', 'exchange', 1000),
        makeNode('ex-2', 'exchange', 3000),
        makeNode('mem-1', 'memory', 3000),
        makeNode('root-1', 'merkle', 4900),
        makeNode('out-of-bounds', 'exchange', 6000),
      ],
      edges: [],
      byId: new Map(),
      extent,
      timed: 4,
      untimed: 0,
    }

    const mockInvocations: Invocation[] = [
      {
        invocation_id: 'inv-1',
        session_id: 's1',
        agent_id: 'a1',
        runtime: 'node',
        tool_name: 'bash',
        tool_call_id: 'call-1',
        first_seen_at: new Date(3000).toISOString(),
        last_seen_at: new Date(3050).toISOString(),
        pre_tool: null,
        post_tool: null,
        runtime_status: 'complete',
      },
      {
        invocation_id: 'inv-2',
        session_id: 's1',
        agent_id: 'a1',
        runtime: 'node',
        tool_name: 'read',
        tool_call_id: 'call-2',
        first_seen_at: new Date(4900).toISOString(),
        last_seen_at: new Date(4950).toISOString(),
        pre_tool: null,
        post_tool: null,
        runtime_status: 'complete',
      },
    ]

    const result = computeSynapticSpectrum(mockModel, mockInvocations, 4, extent)
    expect(result).not.toBeNull()
    if (!result) return

    expect(result.from).toBe(1000)
    expect(result.to).toBe(5000)
    expect(result.buckets).toHaveLength(4)

    // Bucket 0 (1000 - 2000): ex-1
    expect(result.buckets[0].exchanges).toBe(1)
    expect(result.buckets[0].tools).toBe(0)
    expect(result.buckets[0].anchors).toBe(0)
    expect(result.buckets[0].total).toBe(1)

    // Bucket 2 (3000 - 4000): ex-2, mem-1, inv-1
    expect(result.buckets[2].exchanges).toBe(2)
    expect(result.buckets[2].tools).toBe(1)
    expect(result.buckets[2].anchors).toBe(0)
    expect(result.buckets[2].total).toBe(3)

    // Bucket 3 (4000 - 5000): root-1, inv-2
    expect(result.buckets[3].exchanges).toBe(0)
    expect(result.buckets[3].tools).toBe(1)
    expect(result.buckets[3].anchors).toBe(1)
    expect(result.buckets[3].total).toBe(2)

    // Max count across buckets is 3
    expect(result.max).toBe(3)
  })
})
