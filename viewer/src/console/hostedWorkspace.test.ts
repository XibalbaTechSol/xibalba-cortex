import { describe, expect, it, vi } from 'vitest'
import { destinationsFrom } from './nav'
import { AGENT_DID_REQUIRED, keyRows, offersHostedWorkspace, parseAgentDids } from './hostedWorkspace'

/* The expiry pin (`'en-US'` + `timeZone: 'UTC'`) is only observable away from UTC, and nothing in
   this repo sets the runner's zone -- so the test sets it itself rather than inheriting whatever CI
   happens to run in. America/Los_Angeles is negative-offset, where a UTC 00:30 expiry reads as the
   previous day; the 23:30 fixture below covers the eastern observer (Asia/Tokyo reads it as the
   next day). Node re-reads this assignment on the next Date use. */
vi.stubEnv('TZ', 'America/Los_Angeles')

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
  /* Two instants on the same UTC day, one either side of midnight UTC: no single instant can
     discriminate in both directions, because one instant has one local date per zone. 00:30Z reads
     as 11/24 for every zone west of UTC, 23:30Z as 11/26 for every zone east of it, so dropping
     the pin is red wherever this runs -- and, with TZ forced above, red even on a UTC runner. */
  it('dates the expiry in UTC, so the row does not read differently per machine', () => {
    expect(keyRows([key({ expires_at: '2026-11-25T00:30:00Z' })])[0].expires).toBe('11/25/2026')
    expect(keyRows([key({ expires_at: '2026-11-25T23:30:00Z' })])[0].expires).toBe('11/25/2026')
  })
  it('keeps the id, so a row can be revoked', () => {
    expect(keyRows([key({ id: 'k9' })])[0].id).toBe('k9')
  })
})
