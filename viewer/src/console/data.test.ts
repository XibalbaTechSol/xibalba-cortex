import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Invocation } from '../api'
import { loadConsoleData } from './data'

vi.mock('../api', () => ({ api: { graph: vi.fn(), memories: vi.fn(), sessions: vi.fn(), stats: vi.fn(), status: vi.fn(), invocations: vi.fn() } }))

afterEach(() => vi.restoreAllMocks())

describe('optional timeline invocation data', () => {
  it.each([null, { items: [] }, 'unavailable'])('keeps the graph usable when invocation data is malformed (%j)', async (payload) => {
    vi.spyOn(api, 'graph').mockResolvedValue({ nodes: [], edges: [] })
    vi.spyOn(api, 'memories').mockResolvedValue({ memories: [], has_more: false, offset: 0, limit: 200 })
    vi.spyOn(api, 'sessions').mockResolvedValue([])
    vi.spyOn(api, 'stats').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'status').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'invocations').mockResolvedValue(payload as unknown as Invocation[])
    const result = await loadConsoleData({}, 0.5)
    expect(result.graph.nodes).toEqual([])
    expect(result.invocations).toEqual([])
  })
})
