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

export async function managedFixture(page: Page, { billing = false, signedIn = false, plan = 'free', writable = true, destinations = MANAGED_DESTINATIONS } = {}) {
  let session = signedIn
  const memories: Array<{ id: string; content: string; status: string }> = []
  let keys: Array<{ id: string; label: string; expires_at: string }> = []
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  await page.route('**/api/managed/**', async (route) => {
    const req = route.request(), path = new URL(req.url()).pathname.split('/api/managed/')[1]
    const body = req.postDataJSON() ?? {}
    calls.push({ path, method: req.method(), body })
    const send = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === 'plans') return send({ plans, billing_configured: billing, signup_enabled: true, hosted_inference_enabled: false })
    if (path === 'signup' || path.startsWith('recovery/')) return send({ message: 'Check your email.' }, 202)
    if (path === 'login') { session = true; return send({ account: {}, csrf_token: 'fixture-csrf' }) }
    if (path === 'logout') { session = false; return send({ ok: true }) }
    if (!session) return send({ error: 'Sign in' }, 401)
    if (path === 'me') return send({ destinations, account: { display_name: 'Operator', email: 'operator@example.com' }, entitlement: { plan: plans.find((p) => p.id === plan), status: writable ? 'free' : 'canceled', writable, period_end: null, cancel_at_period_end: false }, usage: { month: '2026-10', used: { writes: memories.length } }, counts: { memories: memories.length }, csrf_token: 'fixture-csrf' })
    if (path === 'memories' && req.method() === 'POST') { memories.push({ id: 'm-' + memories.length, content: String(body.content), status: 'active' }); return send(memories.at(-1), 201) }
    if (path === 'memories') return send({ memories })
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
