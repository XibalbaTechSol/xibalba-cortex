import { describe, expect, it } from 'vitest'
import { destinationsFrom } from './nav'
import { AGENT_DID_REQUIRED, keyRows, offersHostedWorkspace, parseAgentDids } from './hostedWorkspace'

/** What `GET /api/managed/me` declares (src/xibalba_cortex/managed/api.py, MANAGED_DESTINATIONS). */
const MANAGED = ['graph', 'timeline', 'memories', 'recall', 'settings', 'agents', 'billing']

describe('offersHostedWorkspace', () => {
  it('is false when the server declared nothing, which is what self-hosted does', () => {
    expect(offersHostedWorkspace(destinationsFrom(undefined))).toBe(false)
    expect(offersHostedWorkspace(destinationsFrom([]))).toBe(false)
  })
  it('is true for the destination list the hosted edition declares', () => {
    expect(offersHostedWorkspace(destinationsFrom(MANAGED))).toBe(true)
  })
  it('turns on the hosted-only destination, not on a page both editions serve', () => {
    expect(offersHostedWorkspace(destinationsFrom(['graph', 'memories', 'agents', 'settings']))).toBe(false)
    expect(offersHostedWorkspace(destinationsFrom(['graph', 'billing']))).toBe(true)
  })
})

describe('parseAgentDids', () => {
  it('splits on newlines and commas, trims, and drops empties', () => {
    expect(parseAgentDids(' did:integrity:one \n\n did:integrity:two,, did:integrity:three ')).toEqual({
      ok: true,
      agentIds: ['did:integrity:one', 'did:integrity:two', 'did:integrity:three'],
    })
  })
  it('de-duplicates, keeping the first occurrence', () => {
    expect(parseAgentDids('did:integrity:a\ndid:integrity:b\ndid:integrity:a')).toEqual({
      ok: true,
      agentIds: ['did:integrity:a', 'did:integrity:b'],
    })
  })
  it('refuses an empty result rather than asking for a key bound to nothing', () => {
    expect(parseAgentDids('')).toEqual({ ok: false, error: AGENT_DID_REQUIRED })
    expect(parseAgentDids('  \n , ,\n ')).toEqual({ ok: false, error: AGENT_DID_REQUIRED })
  })
})

describe('keyRows', () => {
  const key = (over: Partial<Parameters<typeof keyRows>[0][number]> = {}) => ({
    id: 'k1', label: 'managed-api:agent', expires_at: '2026-11-25T23:30:00Z', ...over,
  })

  it('strips the managed-api label prefix, but only at the start', () => {
    expect(keyRows([key()])[0].label).toBe('agent')
    expect(keyRows([key({ label: 'agent-managed-api:two' })])[0].label).toBe('agent-managed-api:two')
  })
  it('pluralises the bound agent count and says unbound when there are none', () => {
    expect(keyRows([key({ agent_ids: ['did:integrity:a'] })])[0].agents).toBe('1 agent')
    expect(keyRows([key({ agent_ids: ['did:integrity:a', 'did:integrity:b'] })])[0].agents).toBe('2 agents')
    expect(keyRows([key({ agent_ids: [] })])[0].agents).toBe('unbound')
    expect(keyRows([key()])[0].agents).toBe('unbound')
  })
  it('dates the expiry in UTC, so the row does not read differently per machine', () => {
    expect(keyRows([key()])[0].expires).toBe('11/25/2026')
  })
  it('keeps the id, so a row can be revoked', () => {
    expect(keyRows([key({ id: 'k9' })])[0].id).toBe('k9')
  })
})
