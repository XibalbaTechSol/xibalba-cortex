import { describe, expect, it } from 'vitest'
import { PAIR_ACTION_COPY, countText, describeIdentity, pairActions } from './agents'

describe('describeIdentity', () => {
  it('never reports off-chain for an agent whose oracle lookup did not happen', () => {
    expect(describeIdentity({ on_chain: false, identity_verified: false, wallet_address: null })).toMatchObject({ label: 'not checked', tone: 'neutral' })
    expect(describeIdentity({ on_chain: undefined, identity_verified: undefined, wallet_address: undefined }).label).toBe('not checked')
  })
  it('reports on-chain and off-chain only when verified', () => {
    expect(describeIdentity({ on_chain: true, identity_verified: true, wallet_address: '0xabc' })).toMatchObject({ label: 'registered on-chain', tone: 'ok', detail: 'wallet 0xabc' })
    expect(describeIdentity({ on_chain: false, identity_verified: true, wallet_address: null })).toMatchObject({ label: 'off-chain', tone: 'review' })
  })
})

describe('pairActions', () => {
  it('offers nothing for a revoked or missing pairing, and not detach for one already detached', () => {
    expect(pairActions('active')).toEqual(['rename', 'detach', 'revoke'])
    expect(pairActions('detached')).toEqual(['rename', 'revoke'])
    expect(pairActions('revoked')).toEqual([])
    expect(pairActions(null)).toEqual([])
    expect(pairActions(undefined)).toEqual([])
  })
  it('requires a stated consequence before the irreversible actions', () => {
    expect(PAIR_ACTION_COPY.rename.confirm).toBeNull()
    expect(PAIR_ACTION_COPY.detach.confirm).toBeTruthy()
    expect(PAIR_ACTION_COPY.revoke.confirm).toMatch(/permanent/)
  })
})

describe('countText', () => {
  it('says not counted instead of zero when the API skipped the count', () => {
    expect(countText(0, false)).toBe('not counted')
    expect(countText(0, true)).toBe('0')
    expect(countText(1200, undefined)).toBe('1,200')
  })
})
