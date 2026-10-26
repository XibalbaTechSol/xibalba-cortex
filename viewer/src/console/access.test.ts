import { describe, expect, it } from 'vitest'
import type { ApiTokenRecord } from '../api'
import { LIFETIMES, DEFAULT_LIFETIME_HOURS, adminRefusal, describeRole, destinationRows, featureRows, tokenRows, validateTokenLabel } from './access'

const token = (over: Partial<ApiTokenRecord>): ApiTokenRecord => ({
  id: 't', label: 'ci', roles: ['reader'], scopes: ['memory:read'], agent_ids: [], created_at: '2026-10-01T00:00:00+00:00',
  last_used_at: null, expires_at: '2026-11-01T00:00:00+00:00', revoked_at: null, state: 'active', ...over,
})

describe('roles', () => {
  it('every role the server can grant has a description a person can act on', () => {
    for (const role of ['reader', 'writer', 'reviewer', 'operator', 'admin']) expect(describeRole(role).length).toBeGreaterThan(20)
    expect(describeRole('mystery')).toMatch(/custom role/)
  })
  it('offers no token without an end date, and the default is thirty days', () => {
    expect(LIFETIMES.every((l) => l.hours > 0)).toBe(true)
    expect(LIFETIMES.find((l) => l.hours === DEFAULT_LIFETIME_HOURS)?.label).toMatch(/30 days/)
  })
})

describe('token rows', () => {
  it('lists active tokens first, newest first within a state', () => {
    const rows = tokenRows([
      token({ id: 'old-revoked', state: 'revoked', revoked_at: '2026-10-05T00:00:00+00:00', created_at: '2026-09-01T00:00:00+00:00' }),
      token({ id: 'older-active', created_at: '2026-09-15T00:00:00+00:00' }),
      token({ id: 'newer-active', created_at: '2026-10-02T00:00:00+00:00' }),
      token({ id: 'expired', state: 'expired', created_at: '2026-08-01T00:00:00+00:00' }),
    ])
    expect(rows.map((r) => r.id)).toEqual(['newer-active', 'older-active', 'expired', 'old-revoked'])
  })
  it('says in words when it ends, was last used, and whether it can still be revoked', () => {
    const [active] = tokenRows([token({})])
    expect(active).toMatchObject({ ends: 'expires 2026-11-01', lastUsed: 'never used', canRevoke: true, stateWord: 'active' })
    const [revoked] = tokenRows([token({ state: 'revoked', revoked_at: '2026-10-05T12:00:00+00:00' })])
    expect(revoked).toMatchObject({ ends: 'revoked 2026-10-05', canRevoke: false, stateWord: 'revoked' })
    const [forever] = tokenRows([token({ expires_at: null, last_used_at: '2026-10-09T08:00:00+00:00' })])
    expect(forever).toMatchObject({ ends: 'no end date', lastUsed: '2026-10-09' })
  })
})

describe('labels and refusals', () => {
  it('requires a label that is neither empty, long, nor reserved', () => {
    expect(validateTokenLabel('')).toMatch(/Give the token a label/)
    expect(validateTokenLabel('   ')).toMatch(/Give the token a label/)
    expect(validateTokenLabel('x'.repeat(81))).toMatch(/80/)
    expect(validateTokenLabel('account:me@example.com')).toMatch(/reserved/)
    expect(validateTokenLabel('ingest bot')).toBeNull()
  })
  it('words a 403 as "you may not"', () => {
    expect(adminRefusal(403, "your credential may not issue the 'admin' role")).toMatch(/^Your credential may not do this/)
    expect(adminRefusal(400, 'label is required')).toBe('label is required')
  })
})

describe('profile configuration', () => {
  it('reports each destination as set or not, never where', () => {
    const rows = destinationRows({ backup: true, vault: false, integrity_dag: true, anchor_service: false, oracle: false })
    expect(rows.map((r) => [r.id, r.word])).toEqual([
      ['backup', 'configured'], ['vault', 'not configured'], ['integrity_dag', 'configured'], ['anchor_service', 'not configured'], ['oracle', 'not configured'],
    ])
    expect(JSON.stringify(rows)).not.toMatch(/\/|http/)
  })
  it('sorts features with the enabled ones first', () => {
    expect(featureRows({ provenance: true, telemetry: false, audit: true })).toEqual([
      { name: 'audit', on: true }, { name: 'provenance', on: true }, { name: 'telemetry', on: false },
    ])
  })
})
