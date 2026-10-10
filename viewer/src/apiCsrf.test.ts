// The CSRF contract with local_api.py: a cookie-authenticated write must carry
// X-Cortex-CSRF-Token (from GET /api/auth/csrf); a bearer-authenticated one has no cookie to ride,
// the csrf route answers 400, and nothing extra is sent. api.ts touches sessionStorage at import,
// so the test stubs it and loads the module afterwards.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

interface Call { url: string; method: string; csrf: string | undefined }

function installFetch(handler: (url: string, init: RequestInit, n: number) => Response): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = (init.headers ?? {}) as Record<string, string>
    calls.push({ url, method: init.method ?? 'GET', csrf: headers['X-Cortex-CSRF-Token'] })
    return handler(url, init, calls.length)
  }))
  return calls
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) })
  vi.resetModules()
})
afterEach(() => vi.unstubAllGlobals())

describe('CSRF on state-changing requests', () => {
  it('sends the token a cookie session was issued', async () => {
    const calls = installFetch((url) => (url.endsWith('/api/auth/csrf') ? json(200, { csrf_token: 'tok-1' }) : json(200, { ok: true })))
    const { api } = await import('./api')
    await api.updateInferenceSettings({} as never)
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.csrf).toBe('tok-1')
  })

  it('sends no header when the credential is a bearer token (csrf route answers 400)', async () => {
    const calls = installFetch((url) => (url.endsWith('/api/auth/csrf') ? json(400, { error: 'csrf token requires cookie-based session auth' }) : json(200, { ok: true })))
    const { api } = await import('./api')
    await api.updateInferenceSettings({} as never)
    expect(calls.find((c) => c.method === 'POST')!.csrf).toBeUndefined()
  })

  it('asks for the token once and reuses it', async () => {
    const calls = installFetch((url) => (url.endsWith('/api/auth/csrf') ? json(200, { csrf_token: 'tok-1' }) : json(200, { ok: true })))
    const { api } = await import('./api')
    await api.updateInferenceSettings({} as never)
    await api.updateInferenceSettings({} as never)
    expect(calls.filter((c) => c.url.endsWith('/api/auth/csrf'))).toHaveLength(1)
  })

  it('refreshes the token and retries once when the server rejects a stale one', async () => {
    let issued = 0
    const calls = installFetch((url, init) => {
      if (url.endsWith('/api/auth/csrf')) return json(200, { csrf_token: `tok-${++issued}` })
      const sent = (init.headers as Record<string, string>)['X-Cortex-CSRF-Token']
      return sent === 'tok-2' ? json(200, { ok: true }) : json(403, { error: 'missing or invalid CSRF token; GET /api/auth/csrf first' })
    })
    const { api } = await import('./api')
    await expect(api.updateInferenceSettings({} as never)).resolves.toMatchObject({ ok: true })
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.csrf)).toEqual(['tok-1', 'tok-2'])
  })

  it('does not loop: a second 403 is reported', async () => {
    installFetch((url) => (url.endsWith('/api/auth/csrf') ? json(200, { csrf_token: 'tok' }) : json(403, { error: 'forbidden' })))
    const { api } = await import('./api')
    await expect(api.updateInferenceSettings({} as never)).rejects.toThrow('forbidden')
  })
})
