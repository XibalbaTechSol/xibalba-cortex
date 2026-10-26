import { describe, expect, it } from 'vitest'
import { MIN_PASSWORD_LENGTH, confirmNotice, requestNotice, resetTokenFromSearch, searchWithoutToken, validateNewPassword } from './passwordReset'

describe('reading the reset link', () => {
  it('accepts a URL-safe token and ignores everything else', () => {
    const token = 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v'
    expect(resetTokenFromSearch(`?token=${token}`)).toBe(token)
    expect(resetTokenFromSearch(`?agent_id=x&token=${token}&store_id=y`)).toBe(token)
    expect(resetTokenFromSearch('')).toBeNull()
    expect(resetTokenFromSearch('?token=')).toBeNull()
    expect(resetTokenFromSearch('?token=short')).toBeNull()
    expect(resetTokenFromSearch('?token=has spaces and <script>alert(1)</script>')).toBeNull()
    expect(resetTokenFromSearch(`?token=${'a'.repeat(129)}`)).toBeNull()
  })

  it('removes only the token from the address bar', () => {
    expect(searchWithoutToken('?token=abc')).toBe('')
    expect(searchWithoutToken('?agent_id=a%3Ab&token=abc&store_id=s')).toBe('?agent_id=a%3Ab&store_id=s')
    expect(searchWithoutToken('?agent_id=a')).toBe('?agent_id=a')
  })
})

describe('asking for a link', () => {
  it('says the same thing whether or not the account exists', () => {
    expect(requestNotice(200)).toEqual(requestNotice(null))
    expect(requestNotice(200).text).toMatch(/If an account exists/)
    expect(requestNotice(200).text).not.toMatch(/sent to|we found|no account/i)
  })
  it('names a server that cannot send email, and the rate limit', () => {
    expect(requestNotice(503)).toMatchObject({ tone: 'error', text: expect.stringMatching(/cannot send email/) })
    expect(requestNotice(429).text).toMatch(/Too many/)
    expect(requestNotice(500).tone).toBe('error')
  })
})

describe('setting the new password', () => {
  it('succeeds with a plain instruction', () => {
    expect(confirmNotice(200)).toEqual({ tone: 'ok', text: 'Password changed. Sign in with the new password.' })
  })
  it('tells a bad or used link from a weak password', () => {
    expect(confirmNotice(400, 'reset token is invalid or expired').text).toMatch(/invalid or has expired/)
    expect(confirmNotice(400, 'password must be at least 10 characters').text).toMatch(/longer password/)
  })
  it('validates before sending', () => {
    expect(validateNewPassword('short', 'short')).toMatch(new RegExp(String(MIN_PASSWORD_LENGTH)))
    expect(validateNewPassword('a-long-enough-one', 'a-different-one-x')).toMatch(/do not match/)
    expect(validateNewPassword('a-long-enough-one', 'a-long-enough-one')).toBeNull()
  })
})
