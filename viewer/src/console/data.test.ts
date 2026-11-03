import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Invocation } from '../api'
import { loadConsoleData } from './data'

vi.mock('../api', () => ({ api: { graph: vi.fn(), memories: vi.fn(), sessions: vi.fn(), stats: vi.fn(), status: vi.fn(), invocations: vi.fn(), agents: vi.fn() } }))

afterEach(() => vi.restoreAllMocks())

describe('optional timeline invocation data', () => {
  it.each([null, { items: [] }, 'unavailable'])('keeps the graph usable when invocation data is malformed (%j)', async (payload) => {
    vi.spyOn(api, 'graph').mockResolvedValue({ nodes: [], edges: [] })
    vi.spyOn(api, 'memories').mockResolvedValue({ memories: [], has_more: false, offset: 0, limit: 200 })
    vi.spyOn(api, 'sessions').mockResolvedValue([])
    vi.spyOn(api, 'stats').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'status').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'invocations').mockResolvedValue(payload as unknown as Invocation[])
    vi.spyOn(api, 'agents').mockRejectedValue(new Error('unavailable'))
    const result = await loadConsoleData({}, 0.5)
    expect(result.graph.nodes).toEqual([])
    expect(result.invocations).toEqual([])
    // A refused agent listing is "unknown", not "no agents": the first-run gate must not fire
    // on a failed probe, or a transient error would divert a populated workspace to onboarding.
    expect(result.hasAgents).toBeNull()
  })
})

describe('the first-run agent probe', () => {
  /* `hasAgents` is the only input to the console's first-run gate. Three values, three
   * meanings: false gates, true does not, and null means the listing did not answer and so
   * must not gate. */
  const base = () => {
    vi.spyOn(api, 'graph').mockResolvedValue({ nodes: [], edges: [] })
    vi.spyOn(api, 'memories').mockResolvedValue({ memories: [], has_more: false, offset: 0, limit: 200 })
    vi.spyOn(api, 'sessions').mockResolvedValue([])
    vi.spyOn(api, 'stats').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'status').mockRejectedValue(new Error('unavailable'))
    vi.spyOn(api, 'invocations').mockResolvedValue([])
  }

  it('reports false for an empty listing', async () => {
    base()
    vi.spyOn(api, 'agents').mockResolvedValue({ agents: [], oracle_reachable: false })
    expect((await loadConsoleData({}, 0.5)).hasAgents).toBe(false)
  })

  it('reports true as soon as one agent exists', async () => {
    base()
    vi.spyOn(api, 'agents').mockResolvedValue({ agents: [{ agent_id: 'did:integrity:one' }], oracle_reachable: false } as never)
    expect((await loadConsoleData({}, 0.5)).hasAgents).toBe(true)
  })

  it('asks for one row, not the page the Agents surface loads', async () => {
    base()
    const agents = vi.spyOn(api, 'agents').mockResolvedValue({ agents: [], oracle_reachable: false })
    await loadConsoleData({}, 0.5)
    expect(agents).toHaveBeenCalledWith(1)
  })
})
