// A failed data call carries its HTTP status, because the server's message alone cannot say whether
// the session ended. "invalid or revoked token" is what local_api.py answers for an expired or
// revoked session cookie, and no pattern over that text is a safe way to decide "sign in again".
// api.ts touches sessionStorage at import, so the test stubs it and loads the module afterwards.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) })
  vi.resetModules()
})
afterEach(() => vi.unstubAllGlobals())

describe('ApiError', () => {
  it('a 401 on a read carries status 401 and the server wording', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(401, { error: 'invalid or revoked token' })))
    const { api, ApiError } = await import('./api')
    const err = await api.stats().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as InstanceType<typeof ApiError>).status).toBe(401)
    expect((err as Error).message).toBe('invalid or revoked token')
  })

  it('a 403 is a 403, not a reason to sign out', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(403, { error: 'credential lacks required scope: memory:write' })))
    const { api, ApiError } = await import('./api')
    const err = await api.stats().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as InstanceType<typeof ApiError>).status).toBe(403)
  })

  it('a body that is not JSON still yields a status-carrying error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' })))
    const { api, ApiError } = await import('./api')
    const err = await api.stats().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as InstanceType<typeof ApiError>).status).toBe(502)
  })
})
