// workspace.ts imports api.ts, which touches sessionStorage at import: stub it, then load.
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { AgentWorkspace } from '../api'

let defaultOption: typeof import('./workspace').defaultOption
let toOptions: typeof import('./workspace').toOptions

beforeAll(async () => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  ;({ defaultOption, toOptions } = await import('./workspace'))
})

const row = (agent_id: string, extra: Partial<AgentWorkspace> = {}): AgentWorkspace =>
  ({
    agent_id,
    store_id: 'store-1',
    profile_id: 'default',
    store_access: 'writable',
    writable: true,
    memories: 0,
    memories_counted: false,
    ...extra,
  }) as AgentWorkspace

describe('defaultOption', () => {
  it('skips a namespace the server counted as empty', () => {
    // a device paired before its agent wrote anything is listed first, with memories counted at 0
    const options = toOptions([row('claude', { memories_counted: true, memories: 0 }), row('xibalba.agent')])
    expect(defaultOption(options)?.agentId).toBe('xibalba.agent')
  })

  it('treats an uncounted namespace as possibly populated', () => {
    expect(toOptions([row('agent-a')])[0].knownEmpty).toBe(false)
  })

  it('falls back to the first namespace when every one is empty', () => {
    const options = toOptions([row('a', { memories_counted: true }), row('b', { memories_counted: true })])
    expect(defaultOption(options)?.agentId).toBe('a')
  })

  it('returns nothing when there are no namespaces', () => {
    expect(defaultOption([])).toBeUndefined()
  })
})
