import { describe, expect, it } from 'vitest'
import { asText, sessionRows } from './account'

describe('asText', () => {
  it('names missing values instead of printing null', () => {
    expect(asText(null)).toBe('none')
    expect(asText(undefined)).toBe('none')
    expect(asText('')).toBe('none')
  })
  it('keeps zero and false (they are values, not absences)', () => {
    expect(asText(0)).toBe('0')
    expect(asText(false)).toBe('false')
  })
  it('stringifies structures compactly', () => {
    expect(asText({ a: 1 })).toBe('{"a":1}')
  })
})

describe('sessionRows', () => {
  const rows = [
    { id: 'a', label: 'account:x@y', created_at: '2026-10-01 10:00:00', last_used_at: null, revoked_at: null },
    { id: 'b', label: 'account:x@y', created_at: '2026-10-05 10:00:00', last_used_at: '2026-10-06 09:00:00', revoked_at: '2026-10-06 09:30:00' },
    { label: 'no id', created_at: '2026-10-06' },
  ]
  it('orders newest first, flags revoked, and drops rows that cannot be revoked', () => {
    const out = sessionRows(rows)
    expect(out.map((r) => r.id)).toEqual(['b', 'a'])
    expect(out[0].revoked).toBe(true)
    expect(out[1].revoked).toBe(false)
  })
  it('says "never" for a session that was never used', () => {
    expect(sessionRows(rows).find((r) => r.id === 'a')?.lastUsed).toBe('never')
  })
})
