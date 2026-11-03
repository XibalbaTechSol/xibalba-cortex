// The hosted wire contract: what the console asks the managed backend for, and what it refuses to
// ask it for at all.
//
// The sibling of src/apiSelfHosted.test.ts. That one records the bare `/api/*` table and must stay
// green; this one records the hosted mapping. Together they are the claim "one app, two backends"
// stated as two measurements.
//
// api.ts touches sessionStorage at import, so the test stubs it and loads the module afterwards.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { READ_ONLY_WORKSPACE } from './console/billing'

interface Call { url: string; method: string; csrf?: string; idempotency?: string; body?: string }

/** The payload `GET /api/managed/me` answers with, as managed/api.py's `me` builds it. */
const ME = {
  account: { display_name: 'Operator', email: 'operator@example.com', profile_id: 'profile-7' },
  entitlement: { plan: { id: 'free', name: 'Free' }, status: 'free', writable: true, cancel_at_period_end: false },
  usage: { month: '2026-10', used: { writes: 1 } },
  counts: { memories: 3 },
  csrf_token: 'csrf-from-me',
  destinations: ['graph', 'timeline', 'memories', 'recall', 'settings', 'agents', 'billing'],
}

function installFetch(answer: (path: string) => unknown = () => ({})): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = (init.headers ?? {}) as Record<string, string>
    calls.push({
      url,
      method: init.method ?? 'GET',
      csrf: headers['X-Cortex-CSRF-Token'],
      idempotency: headers['Idempotency-Key'],
      body: typeof init.body === 'string' ? init.body : undefined,
    })
    const path = String(url).replace('/api/managed/', '').split('?')[0]
    return new Response(JSON.stringify(answer(path)), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) })
  vi.resetModules()
})
afterEach(() => vi.unstubAllGlobals())

/** api.ts plus the hosted mapping installed, which is what ConsoleApp does on a hosted boot. */
async function hostedModules() {
  const hosted = await import('./hostedApi')
  const { api, ...rest } = await import('./api')
  hosted.installHostedTransport()
  return { api, hosted, rest }
}

describe('hostedTarget', () => {
  it('rewrites the calls the managed backend serves, and narrows the query to what each route reads', async () => {
    const { hostedTarget } = await import('./hostedApi')
    const at = (method: string, path: string) => hostedTarget(method, path)?.path
    // the managed graph route reads `limit` and fixes the threshold at 0.75; scope is not a concept there
    expect(at('GET', '/api/graph?limit=500&similarity_threshold=0.75&agent_id=a1&store_id=s1')).toBe('graph?limit=500')
    expect(at('GET', '/api/sessions?limit=200&agent_id=a1')).toBe('timeline?limit=200')
    expect(at('GET', '/api/memories?limit=40&offset=40&status=active&q=hello')).toBe('memories?q=hello')
    expect(at('GET', '/api/search?q=hello&limit=20')).toBe('memories?q=hello')
    expect(at('GET', '/api/memory/m1?')).toBe('memories/m1')
    expect(at('GET', '/api/memory/m1/verify-chain?')).toBe('memories/m1/verify')
    expect(at('GET', '/api/agent0/search?q=x')).toBe('agent0/search?q=x')
    expect(at('GET', '/api/agent0/agent/did%3Aintegrity%3Az?full=true')).toBe('agent0/agent/did%3Aintegrity%3Az?full=true')
    expect(at('GET', '/api/agent0/reputation/did%3Aintegrity%3Az')).toBe('agent0/reputation/did%3Aintegrity%3Az')
    expect(at('GET', '/api/agents?limit=200')).toBe('me')
    expect(at('POST', '/api/memory/propositions')).toBe('memories')
  })

  it('maps every auth path the console calls and the managed backend serves', async () => {
    const { hostedTarget } = await import('./hostedApi')
    const at = (method: string, path: string) => hostedTarget(method, path)?.path ?? null
    expect(at('POST', '/api/auth/login')).toBe('login')
    expect(at('POST', '/api/auth/signup')).toBe('signup')
    expect(at('POST', '/api/auth/logout')).toBe('logout')
    expect(at('GET', '/api/auth/me')).toBe('me')
    expect(at('POST', '/api/auth/password-reset/request')).toBe('recovery/forgot-password')
    expect(at('POST', '/api/auth/password-reset/confirm')).toBe('recovery/reset')
    expect(at('GET', '/api/auth/tokens')).toBe('keys')
    expect(at('POST', '/api/auth/tokens')).toBe('keys')
    expect(at('POST', '/api/auth/tokens/revoke')).toBe('keys/revoke')
  })

  /* Resend-verification is the one piece of HostedLanding's auth surface with no `/api/auth/*`
     equivalent on the self-hosted backend: local_api.py serves no such route. Deleting the
     duplicate form would have deleted the only way a pilot user who lost the verification email
     can ask for another, so it is mapped and `supports()` is made to answer honestly for BOTH
     editions -- true on hosted, false on self-hosted, which is the converse of its default. */
  it('maps resend-verification, and says self-hosted does not serve it', async () => {
    const { hostedTarget, supports, installHostedTransport, clearHostedTransport } = await import('./hostedApi')
    expect(hostedTarget('POST', '/api/auth/verification/resend')?.path).toBe('recovery/resend-verification')
    clearHostedTransport()
    expect(supports('POST', '/api/auth/verification/resend')).toBe(false)
    // and the default for a path local_api.py DOES serve is still "self-hosted serves everything"
    expect(supports('POST', '/api/auth/password-reset/request')).toBe(true)
    installHostedTransport()
    expect(supports('POST', '/api/auth/verification/resend')).toBe(true)
    clearHostedTransport()
  })

  it('still refuses /api/auth/csrf, because managed carries the token in its payloads instead', async () => {
    const { hostedTarget } = await import('./hostedApi')
    // Mapping this to something would invent a route; the hosted CSRF token arrives on `login`
    // and `me`, and `setHostedSession` is what stores it.
    expect(hostedTarget('GET', '/api/auth/csrf')).toBeNull()
  })

  it('has no route for the calls the managed backend answers 404, so they are never sent', async () => {
    const { hostedTarget } = await import('./hostedApi')
    // every one of these is a real console call; `managed/api.py` serves none of them
    for (const path of ['/api/stats', '/api/status', '/api/operations', '/api/invocations?limit=500',
      '/api/sessions/page?limit=50&offset=0', '/api/entity/Alice/neighbors?max_depth=1',
      '/api/memory/m1/events?', '/api/memory/m1/similar?limit=10', '/api/memory/m1/attachments?',
      '/api/auth/csrf', '/api/profile/config', '/api/runtimes', '/api/workers',
      '/api/integrity-links?limit=50', '/api/extraction-proposals?status=proposed&limit=50',
      '/readyz', '/metrics']) {
      expect(hostedTarget('GET', path), path).toBeNull()
    }
    for (const path of ['/api/memory/m1/forget', '/api/memory/m1/supersede', '/api/import?filename=a.md',
      '/api/backup', '/api/retrieval/hybrid', '/api/context/assemble']) {
      expect(hostedTarget('POST', path), path).toBeNull()
    }
    // the method matters: `memories` serves GET and POST, `graph` only GET
    expect(hostedTarget('POST', '/api/graph')).toBeNull()
  })
})

describe('the hosted mapping, through api.ts', () => {
  it('sends the graph to the one route that serves it, with the session cookie', async () => {
    const calls = installFetch(() => ({ nodes: [{ id: 'n1' }], edges: [] }))
    const { api } = await hostedModules()
    const graph = await api.graph(500, 0.75, { agentId: 'a1', storeId: 's1' })
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/managed/graph?limit=500'])
    expect(graph.nodes).toHaveLength(1)
  })

  it('unwraps the single memory, the session list and the search results the managed shapes nest', async () => {
    installFetch((path) => {
      if (path === 'memories/m1') return { memory: { id: 'm1', content: 'one' } }
      if (path === 'timeline') return { sessions: [{ external_session_id: 's1' }], nodes: [] }
      return { memories: [{ id: 'm2' }, { id: 'm3' }] }
    })
    const { api } = await hostedModules()
    expect((await api.memory('m1', {})).id).toBe('m1')
    expect(await api.sessions(200, {})).toHaveLength(1)
    expect(await api.search('x', 20, {})).toHaveLength(2)
    // the managed listing is one page of at most 50 with no `has_more`; the pager must not read an
    // absent field as "there is more", nor claim there is
    const list = await api.memories({ limit: 40, offset: 0 })
    expect(list).toEqual({ memories: [{ id: 'm2' }, { id: 'm3' }], has_more: false, offset: 0, limit: 2 })
  })

  it('makes the hosted workspace out of the subscription, so it is writable exactly when the plan is', async () => {
    installFetch(() => ME)
    const { api } = await hostedModules()
    const writable = await api.agents(200)
    expect(writable.agents).toEqual([{
      agent_id: 'profile-7', store_id: 'profile-7', profile_id: 'profile-7',
      agent_name: 'Operator', store_access: 'writable', writable: true, memories: 3, memories_counted: true,
      sessions: 0, sessions_counted: false, last_seen_at: null, on_chain: false, identity_verified: false,
    }])
    vi.resetModules()
    installFetch(() => ({ ...ME, entitlement: { ...ME.entitlement, writable: false, status: 'canceled' } }))
    const second = await hostedModules()
    expect((await second.api.agents(200)).agents[0].writable).toBe(false)
    expect((await second.api.agents(200)).agents[0].store_access).toBe('read_only')
  })

  /* The message is user-visible -- `useAsync` and MemoriesPage render `e.message` straight into
     a callout -- so it must not name an HTTP method or an internal route. The diagnostic pair
     lives on `.call`, which nothing renders. Both halves are asserted, because asserting only the
     message would let the diagnostic be dropped silently. */
  it('refuses a call the hosted backend has no route for without sending anything', async () => {
    const calls = installFetch()
    const { api, hosted } = await hostedModules()
    const error = (await api.stats().catch((e: unknown) => e)) as Error
    expect(error.message).toBe(hosted.HOSTED_UNSUPPORTED)
    expect(error.message).not.toMatch(/\/api\/|GET|POST/)
    expect((error as { call?: string }).call).toBe('GET /api/stats')
    expect((error as { status?: number }).status).toBe(501)
    expect(calls).toEqual([])
  })

  it('never asks /api/auth/csrf on a hosted write: the token comes from me', async () => {
    const calls = installFetch((path) => (path === 'me' ? ME : { id: 'm9' }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await api.createProposition({ content: 'a fact', status: 'candidate', evidence_class: 'declared_intent' })
    expect(calls.map((c) => c.url)).toEqual(['/api/managed/memories'])
    expect(calls[0].csrf).toBe('csrf-from-me')
    // the managed route takes content only; status and evidence class have no equivalent there
    expect(calls[0].body).toBe(JSON.stringify({ content: 'a fact' }))
  })
})

describe('the hosted write gate (finding 4)', () => {
  it('refuses a write a read-only subscription forbids, locally, in Billing’s own words', async () => {
    const calls = installFetch()
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession({ ...ME, entitlement: { ...ME.entitlement, writable: false } })
    const error = (await api.createProposition({ content: 'a fact' }).catch((e: unknown) => e)) as Error
    expect(error.message).toBe(READ_ONLY_WORKSPACE)
    expect((error as unknown as { status: number }).status).toBe(402)
    // the point of the gate: no round-trip, so the reason does not depend on the server answering
    expect(calls).toEqual([])
  })

  it('issues the same write once the subscription is active again', async () => {
    const calls = installFetch(() => ({ id: 'm9' }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await api.createProposition({ content: 'a fact' })
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['POST /api/managed/memories'])
  })

  it('does not gate reads: a read-only workspace still reads its memories', async () => {
    const calls = installFetch(() => ({ memories: [] }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession({ ...ME, entitlement: { ...ME.entitlement, writable: false } })
    await api.memories({ limit: 40 })
    expect(calls).toHaveLength(1)
  })
})

describe('the hosted Idempotency-Key (finding 5)', () => {
  it('carries one on every hosted write', async () => {
    const calls = installFetch(() => ({ id: 'm9' }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await api.createProposition({ content: 'a fact' })
    expect(calls[0].idempotency).toMatch(/^[\w-]{8,128}$/)
  })

  it('keeps the SAME key across retries of one logical write, and a different one per write', async () => {
    let fail = true
    const calls = installFetch()
    // the first attempt fails after the server may already have stored it: the retry must not
    // be able to store a second copy
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      calls.push({ url, method: init.method ?? 'GET', idempotency: headers['Idempotency-Key'], body: typeof init.body === 'string' ? init.body : undefined })
      if (fail) { fail = false; return new Response(JSON.stringify({ error: 'upstream timeout' }), { status: 502, headers: { 'Content-Type': 'application/json' } }) }
      return new Response(JSON.stringify({ id: 'm9' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await api.createProposition({ content: 'a fact' }).catch(() => {})
    await api.createProposition({ content: 'a fact' })
    await api.createProposition({ content: 'another fact' })
    const [first, retry, other] = calls.map((c) => c.idempotency!)
    expect(retry).toBe(first)
    expect(other).not.toBe(first)
  })

  it('keys on a digest, so a failed sign-in does not park a plaintext password in module state', async () => {
    /* The key has to follow the payload, and the obvious way to do that -- using the payload AS
       the Map key -- means a failed `login` or `signup` leaves the password in this module until
       something else succeeds. `digest` is what stops that, and only an assertion about the
       retained fingerprints can see it: every key-stability test passes either way. */
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Wrong password' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    const { hostedFetch, pendingWriteFingerprints } = await import('./hostedApi')
    await hostedFetch('login', { method: 'POST', body: JSON.stringify({ email: 'operator@example.com', password: 'correct-horse-battery' }) }).catch(() => {})
    const retained = pendingWriteFingerprints()
    // the failed write did keep a key, so the check below is over something
    expect(retained).toHaveLength(1)
    expect(retained.join(' ')).not.toContain('correct-horse-battery')
    expect(retained.join(' ')).not.toContain('operator@example.com')
  })

  it('starts a new key once a write succeeded, so writing the same text twice is two writes', async () => {
    const calls = installFetch(() => ({ id: 'm9' }))
    const { api, hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await api.createProposition({ content: 'a fact' })
    await api.createProposition({ content: 'a fact' })
    expect(calls[1].idempotency).not.toBe(calls[0].idempotency)
  })
})

describe('the shared hosted transport', () => {
  it('is the one fetch the console, Billing and the key surfaces all go through', async () => {
    const calls = installFetch(() => ME)
    const { hostedRequest } = await import('./console/hostedWorkspace')
    const { hostedFetch } = await import('./hostedApi')
    expect(hostedRequest).toBe(hostedFetch)
    await hostedRequest('me')
    expect(calls.map((c) => c.url)).toEqual(['/api/managed/me'])
  })

  it('learns the entitlement from any me that passes through it', async () => {
    installFetch(() => ({ ...ME, entitlement: { ...ME.entitlement, writable: false } }))
    const { hostedFetch, hostedWritable } = await import('./hostedApi')
    expect(hostedWritable()).toBeUndefined()
    await hostedFetch('me')
    expect(hostedWritable()).toBe(false)
  })

  it('rejects with an ApiError carrying the status, which is what ends an expired session', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Sign in' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    const { hostedFetch } = await import('./hostedApi')
    const { ApiError } = await import('./apiError')
    const error = await hostedFetch('me').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as InstanceType<typeof ApiError>).status).toBe(401)
    expect((error as Error).message).toBe('Sign in')
  })
  it('signs up without ever issuing a login call, because verification precedes first sign-in', async () => {
    const calls = installFetch(() => ({ message: 'Check your email.' }))
    const { rest } = await hostedModules()
    await rest.accountAuth('signup', { email: 'new@example.com', password: 'pw', display_name: 'New' })
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['POST /api/managed/signup'])
    expect(calls.filter((c) => c.url.includes('login'))).toHaveLength(0)
  })

  it('reshapes the managed key list into the token list the console renders', async () => {
    installFetch(() => ({ keys: [{ id: 'k1', label: 'managed-api:agent', agent_ids: [] }] }))
    const { api } = await hostedModules()
    const list = await api.authTokens()
    expect(list.tokens).toHaveLength(1)
    // managed mints one kind of key, so the console must not offer a role picker it cannot honour
    expect(list.grantable_roles).toEqual([])
  })
})

/* Task 5 Step 6: the 401 reset, preserved through the consolidation.
 *
 * The spec requires that managed's existing behaviour survives: a 401 returns the user to the
 * sign-in surface with NO stale session state. "No stale state" is three separate pieces of
 * state, in two modules, and each one is a separate way for an expired session to look live:
 *   - api.ts's non-secret `signed-in` hint, which decides whether the next boot renders a
 *     workspace before any request is made;
 *   - the account summary SignIn parks in sessionStorage;
 *   - the CSRF token and entitlement this transport holds, which belong to the dead session.
 * The user-visible half of the behaviour -- that SignIn is what they land on -- is a browser
 * fact and is asserted in e2e/managed.spec.ts; vitest runs in node with no DOM.
 */
describe('a 401 resets to sign-in with no stale session state (Step 6)', () => {
  it('forgets the signed-in hint and the account summary even when logout is itself refused', async () => {
    // the state a hosted session leaves behind, exactly as SignIn writes it
    sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    sessionStorage.setItem('xibalba-cortex.account', JSON.stringify({ email: 'operator@example.com' }))
    /* managed's `logout` authenticates with `mutate=True` (managed/api.py:252 -> owner), so an
       already-expired session is answered 401 -- the exact case where clearing matters most.
       Hosted `send` REJECTS on a non-2xx, so a logout that is refused used to skip the clear
       entirely and leave the next boot believing it was signed in. */
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Sign in to your managed workspace' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    const { rest } = await hostedModules()
    expect(rest.isSignedIn()).toBe(true) // the hint was really set, so the check below is over something
    await rest.accountLogout().catch(() => {})
    expect(rest.isSignedIn()).toBe(false)
    expect(sessionStorage.getItem('xibalba-cortex.signed-in')).toBeNull()
    expect(sessionStorage.getItem('xibalba-cortex.account')).toBeNull()
  })

  it('drops the CSRF token and the entitlement the expired session issued', async () => {
    const calls: Call[] = []
    let status = 401
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      calls.push({ url, method: init.method ?? 'GET', csrf: headers['X-Cortex-CSRF-Token'] })
      return new Response(JSON.stringify(status === 401 ? { error: 'Sign in to your managed workspace' } : {}), { status, headers: { 'Content-Type': 'application/json' } })
    }))
    const { hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    expect(hosted.hostedWritable()).toBe(true) // held state exists, so losing it is a measurement
    await hosted.hostedFetch('me').catch(() => {})
    expect(hosted.hostedWritable()).toBeUndefined()
    // and nothing from the dead session rides the next request
    status = 200
    await hosted.hostedFetch('plans')
    expect(calls.at(-1)!.csrf).toBeUndefined()
  })

  it('leaves a non-401 failure\'s session state alone, so the reset is the 401 and not every error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'upstream timeout' }), { status: 502, headers: { 'Content-Type': 'application/json' } })))
    const { hosted } = await hostedModules()
    hosted.setHostedSession(ME)
    await hosted.hostedFetch('me').catch(() => {})
    expect(hosted.hostedWritable()).toBe(true)
  })

  it('does not mark the browser signed in when signup only queued a verification email', async () => {
    /* managed answers signup 202 with `{message}` and no account: verification precedes the first
       sign-in. Marking the hint here would open a workspace for a session that does not exist,
       which is the same stale state a 401 has to clear -- so it must never be written. */
    installFetch(() => ({ message: 'Check your email to verify your account before signing in.' }))
    const { rest } = await hostedModules()
    const payload = await rest.accountAuth('signup', { email: 'new@example.com', password: 'a-long-enough-one', display_name: 'New Operator' })
    expect(payload.account).toBeUndefined()
    expect(rest.isSignedIn()).toBe(false)
    expect(sessionStorage.getItem('xibalba-cortex.signed-in')).toBeNull()
  })

  it('still marks the browser signed in when login returned an account', async () => {
    installFetch(() => ({ account: { email: 'operator@example.com' }, csrf_token: 'csrf-from-login' }))
    const { rest } = await hostedModules()
    await rest.accountAuth('login', { email: 'operator@example.com', password: 'a-long-enough-one' })
    expect(rest.isSignedIn()).toBe(true)
  })
})
