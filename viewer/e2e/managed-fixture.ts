import type { Page } from '@playwright/test'

const plans = [
  { id: 'free', name: 'Free', monthly_cents: 0, max_memories: 1000, writes_per_month: 250, retrievals_per_month: 1000 },
  { id: 'pro', name: 'Pro', monthly_cents: 2900, max_memories: 25000, writes_per_month: 5000, retrievals_per_month: 25000 },
  { id: 'team', name: 'Team', monthly_cents: 14900, max_memories: 250000, writes_per_month: 50000, retrievals_per_month: 250000 },
]

/* What the hosted edition declares at GET /api/managed/me (MANAGED_DESTINATIONS in
   src/xibalba_cortex/managed/api.py). Without it the console would resolve a hosted session to
   the self-hosted set, which has no `billing` -- so the fixture would be testing a deployment
   that does not exist. `destinations` overrides it for a test that needs a narrower list. */
const MANAGED_DESTINATIONS = ['graph', 'timeline', 'memories', 'recall', 'settings', 'agents', 'billing']

const fixtureSession = { external_session_id: 'fixture-session', agent_id: 'did:integrity:fixture', started_at: '2026-10-20 09:00:00', ended_at: null, memories: 1 }

/** The graph payload for the memories the fixture holds, plus the session that wrote them. A
 *  `memory:` node id is what `buildModel` strips to get the memory id the Inspector then reads. */
function graphPayload(memories: Array<Record<string, unknown>>) {
  return {
    nodes: [
      { id: 'session:fixture-session', type: 'session', label: 'fixture-session', started_at: '2026-10-20 09:00:00' },
      ...memories.map((m) => ({ id: `memory:${m.id}`, type: 'memory', label: String(m.content).slice(0, 40), status: 'active', evidence_class: 'declared_intent', created_at: '2026-10-20T10:00:00Z', observed_at: '2026-10-20T10:00:00Z', session_id: 'fixture-session' })),
    ],
    edges: memories.map((m) => ({ source: 'session:fixture-session', target: `memory:${m.id}`, type: 'contains' })),
  }
}

/* One stored memory, in the shape `GraphStore.list_memories` returns and the console's readers
   expect: the Memories table reads `created_at`, `content_hash`, `source.kind` and
   `evidence_class`, and the timeline reads `source.observed_at` / `source.session_id`. */
function memoryRow(id: string, content: string) {
  return {
    id, content, status: 'active', evidence_class: 'declared_intent',
    content_hash: 'f'.repeat(64), created_at: '2026-10-20T10:00:00Z',
    source: { kind: 'direct_user', agent_id: 'did:integrity:fixture', observed_at: '2026-10-20T10:00:00Z', session_id: 'fixture-session' },
  }
}

export async function managedFixture(page: Page, { billing = false, signedIn = false, plan = 'free', writable = true, destinations = MANAGED_DESTINATIONS, seed = 0 } = {}) {
  let session = signedIn
  const memories: Array<Record<string, unknown>> = Array.from({ length: seed }, (_, i) => memoryRow(`seed-${i}`, `Seeded memory ${i}`))
  let keys: Array<{ id: string; label: string; expires_at: string }> = []
  const calls: Array<{ path: string; method: string; body: Record<string, unknown>; key?: string }> = []
  await page.route('**/api/managed/**', async (route) => {
    const req = route.request(), path = new URL(req.url()).pathname.split('/api/managed/')[1]
    const body = req.postDataJSON() ?? {}
    calls.push({ path, method: req.method(), body, key: req.headers()['idempotency-key'] })
    const send = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === 'plans') return send({ plans, billing_configured: billing, signup_enabled: true, hosted_inference_enabled: false })
    if (path === 'signup' || path.startsWith('recovery/')) return send({ message: 'Check your email.' }, 202)
    if (path === 'login') { session = true; return send({ account: {}, csrf_token: 'fixture-csrf' }) }
    if (path === 'logout') { session = false; return send({ ok: true }) }
    if (!session) return send({ error: 'Sign in' }, 401)
    if (path === 'me') return send({ destinations, account: { display_name: 'Operator', email: 'operator@example.com' }, entitlement: { plan: plans.find((p) => p.id === plan), status: writable ? 'free' : 'canceled', writable, period_end: null, cancel_at_period_end: false }, usage: { month: '2026-10', used: { writes: memories.length } }, counts: { memories: memories.length }, csrf_token: 'fixture-csrf' })
    if (path === 'memories' && req.method() === 'POST') { memories.push(memoryRow('m-' + memories.length, String(body.content))); return send(memories.at(-1), 201) }
    if (path === 'memories') {
      const q = new URL(req.url()).searchParams.get('q') ?? ''
      return send({ memories: q ? memories.filter((m) => String(m.content).includes(q)) : memories })
    }
    /* The routes the console's data layer maps onto (src/hostedApi.ts). Without them every hosted
       read answers "Unknown fixture route" and the fixture would be testing a backend that serves
       less than the real one. Each shape is managed/api.py's own: `graph` is the graph payload,
       `timeline` is `{sessions, nodes}`, a single memory is `{memory}`. */
    if (path === 'graph') return send(graphPayload(memories))
    if (path === 'timeline') return send({ sessions: [fixtureSession], nodes: graphPayload(memories).nodes })
    if (/^memories\/[^/]+\/verify$/.test(path)) return send({ memory_id: path.split('/')[1], valid: true, events: 1, chain_head: 'a'.repeat(64) })
    if (/^memories\/[^/]+$/.test(path)) {
      const found = memories.find((m) => m.id === decodeURIComponent(path.split('/')[1]))
      return found ? send({ memory: found }) : send({ error: 'No such memory' }, 404)
    }
    if (path === 'agent0/search') return send({ agents: [{ agentId: 'did:integrity:fixture', name: 'Fixture agent' }], source: 'agent0', query: new URL(req.url()).searchParams.get('q') ?? '' })
    if (path.startsWith('agent0/agent/')) return send({ agent: { agentId: decodeURIComponent(path.split('/').at(-1)!), name: 'Fixture agent' }, source: 'agent0' })
    if (path.startsWith('agent0/reputation/')) return send({ agent_id: decodeURIComponent(path.split('/').at(-1)!), reputation: { score: 0 }, source: 'agent0' })
    if (path === 'keys' && req.method() === 'POST') { keys.push({ id: 'key-1', label: 'managed-api:agent', expires_at: '2026-11-25T00:00:00Z' }); return send({ token: 'fixture-only-managed-key', expires_in_days: 30 }, 201) }
    if (path === 'keys') return send({ keys })
    if (path === 'keys/revoke') { keys = []; return send({ revoked: true }) }
    if (path === 'checkout') return send({ url: 'https://checkout.stripe.com/test-fixture' })
    if (path === 'portal') return send({ url: 'https://billing.stripe.com/test-fixture' })
    return send({ error: 'Unknown fixture route' }, 404)
  })
  await page.route('https://checkout.stripe.com/**', (route) => route.fulfill({ body: 'Stripe checkout fixture' }))
  await page.route('https://billing.stripe.com/**', (route) => route.fulfill({ body: 'Stripe portal fixture' }))
  return calls
}
