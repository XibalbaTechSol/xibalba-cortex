import { describe, expect, it } from 'vitest'
import { SIGNUP_PENDING, UNVERIFIED, VERIFIED, signInError, verifiedFromSearch } from './authNotice'

describe('the sign-in wording the two editions shared', () => {
  it('turns both servers’ verification refusals into the one actionable instruction', () => {
    // accounts.py:225, raised by issue_account_session on either edition
    expect(signInError('account requires email verification or administrator approval')).toBe(UNVERIFIED)
    // managed/api.py:126, raised by authenticate once a session exists
    expect(signInError('Account verification is required')).toBe(UNVERIFIED)
    expect(UNVERIFIED).toMatch(/verif/i)
  })

  it('passes every other failure through unchanged, so a real error is not relabelled', () => {
    expect(signInError('Invalid email or password')).toBe('Invalid email or password')
    expect(signInError('Too many requests; retry in one minute')).toBe('Too many requests; retry in one minute')
    expect(signInError('')).toBe('')
  })

  it('reads the verify-email redirect, and only that', () => {
    // managed/api.py:227 redirects a clicked verification link to `/managed?verified=1`
    expect(verifiedFromSearch('?verified=1')).toBe(true)
    expect(verifiedFromSearch('?agent_id=a&verified=1')).toBe(true)
    expect(verifiedFromSearch('')).toBe(false)
    expect(verifiedFromSearch('?agent_id=a')).toBe(false)
    expect(VERIFIED).toMatch(/verified/i)
  })

  it('tells a new account that verification comes before its first sign-in', () => {
    expect(SIGNUP_PENDING).toMatch(/verif/i)
    expect(SIGNUP_PENDING).toMatch(/email/i)
  })
})
