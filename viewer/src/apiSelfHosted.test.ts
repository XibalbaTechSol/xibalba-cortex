// The self-hosted wire contract, recorded as a table rather than asserted one call at a time.
//
// This exists because the console's data layer is about to learn a second edition. The only way
// "self-hosted did not change" is a measurement and not a claim is to write this table BEFORE that
// change, commit it green against the unmodified api.ts, and require it to stay green afterwards.
// A table written after the change would be a snapshot of the change, which proves nothing.
//
// What it records per `api` method is the request METHOD and the exact URL, in call order, plus the
// `GET /api/auth/csrf` the first cookie-authenticated write fetches its token from. The base URL is
// '' under test (no VITE_LOCAL_API_URL, not DEV), so every path below is the bare `/api/*` path
// local_api.py serves.
//
// api.ts touches sessionStorage at import, so the test stubs it and loads the module afterwards.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The dev base: vitest runs with `import.meta.env.DEV` true, so api.ts's default base is the
// Vite proxy prefix. In a production self-hosted build it is '' and these become bare `/api/*`.
const BASE = '/cortex-api'

const file = { name: 'notes.md', type: 'text/markdown', size: 12 } as unknown as File

function installFetch(): string[] {
  const seen: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    seen.push(`${init.method ?? 'GET'} ${url}`)
    // a token on the csrf route, `{ready:true}` for /readyz, and an empty object everywhere else
    const body = String(url).endsWith('/api/auth/csrf') ? { csrf_token: 'tok' } : { ready: true, checks: [] }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return seen
}

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) })
  vi.resetModules()
})
afterEach(() => vi.unstubAllGlobals())

describe('the self-hosted wire contract', () => {
  it('reads the bare /api/* paths local_api.py serves', async () => {
    const seen = installFetch()
    const { api } = await import('./api')
    await api.stats()
    await api.status()
    await api.operations()
    await api.readiness()
    await api.metrics()
    await api.integrityLinks(50)
    await api.sessions(200, { agentId: 'a1', storeId: 's1' })
    await api.sessionsPage(50, 0)
    await api.agents(200)
    await api.agent0Search('x')
    await api.agent0Agent('did:integrity:z', true)
    await api.agent0Reputation('did:integrity:z')
    await api.agentSummary('a1', 's1')
    await api.agentDevices()
    await api.graph(500, 0.75, { agentId: 'a1', storeId: 's1' })
    await api.search('q', 20, {})
    await api.memories({ limit: 40, offset: 0, statuses: ['active'], agentId: 'a1', storeId: 's1', query: 'q' })
    await api.memory('m1', {})
    await api.similar('m1', 10, {})
    await api.neighbors('m1', {})
    await api.memoryEvents('m1', {})
    await api.memoryOtel('m1', {})
    await api.attachments('m1', {})
    await api.contradictions('m1', {})
    await api.entityNeighbors('Alice', 1, {})
    await api.entityPath('Alice', 'Bob', 3, {})
    await api.sessionReplay('s1', {})
    await api.sessionOtel('s1', {})
    await api.kernelIntents('s1', {})
    await api.decisionTrace('s1', 't1', {})
    await api.invocations(500)
    await api.sessionExchanges('s1', {})
    await api.sessionMerkleProof('s1', 0, {})
    await api.memoryVerifyChain('m1', {})
    await api.memoryProvenance('m1', false, {})
    await api.sessionVerifyChain('s1', {})
    await api.sessionMemories('s1', {})
    await api.sessionOtelSummary('s1', {})
    await api.sessionMerkleRoot('s1', {})
    await api.inferenceManifest()
    await api.inferenceTasks('pending', 50, {})
    await api.paraClassifications('proposed', 50)
    await api.extractionProposals('proposed', 50)
    await api.retrievalTrace('r1')
    await api.retrievalTraceEvidence('r1', 0)
    await api.projectionCheckpoints('p1', 50)
    await api.embeddingModels()
    await api.profileConfig()
    await api.runtimes()
    await api.workers()
    await api.connectors()
    await api.vaultLeaf('abc')
    await api.backups()
    await api.authTokens()
    await api.pendingAccounts()
    await api.inferenceSettings()

    expect(seen).toEqual([
      `GET ${BASE}/api/stats`,
      `GET ${BASE}/api/status`,
      `GET ${BASE}/api/operations`,
      `GET ${BASE}/readyz`,
      `GET ${BASE}/metrics`,
      `GET ${BASE}/api/integrity-links?limit=50`,
      `GET ${BASE}/api/sessions?limit=200&agent_id=a1&store_id=s1`,
      `GET ${BASE}/api/sessions/page?limit=50&offset=0`,
      `GET ${BASE}/api/agents?limit=200`,
      `GET ${BASE}/api/agent0/search?q=x`,
      `GET ${BASE}/api/agent0/agent/did%3Aintegrity%3Az?full=true`,
      `GET ${BASE}/api/agent0/reputation/did%3Aintegrity%3Az`,
      `GET ${BASE}/api/agent/a1/summary?limit=0&store_id=s1`,
      `GET ${BASE}/api/agent-devices`,
      `GET ${BASE}/api/graph?limit=500&similarity_threshold=0.75&agent_id=a1&store_id=s1`,
      `GET ${BASE}/api/search?q=q&limit=20`,
      `GET ${BASE}/api/memories?limit=40&offset=0&status=active&agent_id=a1&store_id=s1&q=q`,
      `GET ${BASE}/api/memory/m1?`,
      `GET ${BASE}/api/memory/m1/similar?limit=10`,
      `GET ${BASE}/api/memory/m1/neighbors?`,
      `GET ${BASE}/api/memory/m1/events?`,
      `GET ${BASE}/api/memory/m1/otel?`,
      `GET ${BASE}/api/memory/m1/attachments?`,
      `GET ${BASE}/api/memory/m1/contradictions?`,
      `GET ${BASE}/api/entity/Alice/neighbors?max_depth=1`,
      `GET ${BASE}/api/entity/path?from=Alice&to=Bob&max_depth=3`,
      `GET ${BASE}/api/session/s1/replay?`,
      `GET ${BASE}/api/session/s1/otel?`,
      `GET ${BASE}/api/session/s1/kernel-intents?`,
      `GET ${BASE}/api/session/s1/decision-trace?trace_id=t1`,
      `GET ${BASE}/api/invocations?limit=500`,
      `GET ${BASE}/api/session/s1/exchanges?`,
      `GET ${BASE}/api/session/s1/merkle-proof?index=0`,
      `GET ${BASE}/api/memory/m1/verify-chain?`,
      `GET ${BASE}/api/memory/m1/provenance?include_forgotten=0`,
      `GET ${BASE}/api/session/s1/verify-chain?`,
      `GET ${BASE}/api/session/s1/memories?`,
      `GET ${BASE}/api/session/s1/otel-summary?`,
      `GET ${BASE}/api/session/s1/merkle-root?`,
      `GET ${BASE}/api/inference/manifest`,
      `GET ${BASE}/api/inference/tasks?status=pending&limit=50`,
      `GET ${BASE}/api/para/classifications?status=proposed&limit=50`,
      `GET ${BASE}/api/extraction-proposals?status=proposed&limit=50`,
      `GET ${BASE}/api/retrieval/trace/r1`,
      `GET ${BASE}/api/retrieval/trace/r1/evidence?rank=0`,
      `GET ${BASE}/api/projections/p1/checkpoints?limit=50`,
      `GET ${BASE}/api/embedding/models`,
      `GET ${BASE}/api/profile/config`,
      `GET ${BASE}/api/runtimes`,
      `GET ${BASE}/api/workers`,
      `GET ${BASE}/api/connectors`,
      `GET ${BASE}/api/vault/leaf?leaf_hash=abc`,
      `GET ${BASE}/api/backups`,
      `GET ${BASE}/api/auth/tokens`,
      `GET ${BASE}/api/auth/admin/pending`,
      `GET ${BASE}/api/settings/inference`,
    ])
  })

  it('writes to the bare /api/* paths, taking its CSRF token from /api/auth/csrf once', async () => {
    const seen = installFetch()
    const { api } = await import('./api')
    await api.associateAgentDevice('a1', 'd1', 'Laptop')
    await api.renameAgentDevice('d1', 'Laptop')
    await api.detachAgentDevice('d1')
    await api.revokeAgentDevice('d1')
    await api.buildSessionExchanges('s1')
    await api.assembleContext({ query: 'q' })
    await api.recordModelExchange({} as never)
    await api.requestInferenceTask({})
    await api.extractStructural('m1')
    await api.createProposition({ content: 'c' })
    await api.linkEntities({})
    await api.markContradiction({})
    await api.supersedeMemory('m1', {})
    await api.forgetMemory('m1')
    await api.decidePara('t1', 'accept')
    await api.decideExtractionProposal('p1', 'accept')
    await api.hybridRetrieve({ query: 'q' })
    await api.createProjectionCheckpoint('p1')
    await api.reconcileProjectionCheckpoint('p1')
    await api.rebuildProjectionCheckpoint('p1')
    await api.backupNow()
    await api.reconcileBackup('b1')
    await api.exportProvenance(['m1'])
    await api.endSession('s1')
    await api.verifyIntegrityLink('m1')
    await api.anchorSession('s1')
    await api.attachFile('m1', file)
    await api.importDocument(file, 'a1')
    await api.issueAuthToken({ label: 'l', role: 'operator', ttl_hours: 1 })
    await api.revokeAuthToken('t1')
    await api.approveAccount('a@example.com')
    await api.kernelBridgeSelfTest('s1')
    await api.updateInferenceSettings({} as never)

    expect(seen).toEqual([
      // the token is fetched once, before the first write, and reused by every write after it
      `GET ${BASE}/api/auth/csrf`,
      `POST ${BASE}/api/agent-devices/associate`,
      `POST ${BASE}/api/agent-devices/d1/rename`,
      `POST ${BASE}/api/agent-devices/d1/detach`,
      `POST ${BASE}/api/agent-devices/d1/revoke`,
      `POST ${BASE}/api/session/s1/exchanges/build`,
      `POST ${BASE}/api/context/assemble`,
      `POST ${BASE}/api/exchanges/model`,
      `POST ${BASE}/api/inference/tasks`,
      `POST ${BASE}/api/memory/m1/extract-structural`,
      `POST ${BASE}/api/memory/propositions`,
      `POST ${BASE}/api/memory/link-entities`,
      `POST ${BASE}/api/memory/contradictions`,
      `POST ${BASE}/api/memory/m1/supersede`,
      `POST ${BASE}/api/memory/m1/forget`,
      `POST ${BASE}/api/para/classifications/t1/decision`,
      `POST ${BASE}/api/extraction-proposals/p1/decision`,
      `POST ${BASE}/api/retrieval/hybrid`,
      `POST ${BASE}/api/projections/p1/checkpoint`,
      `POST ${BASE}/api/projections/p1/reconcile`,
      `POST ${BASE}/api/projections/p1/rebuild`,
      `POST ${BASE}/api/backup`,
      `POST ${BASE}/api/backup/reconcile`,
      `POST ${BASE}/api/provenance/export`,
      `POST ${BASE}/api/session/s1/end`,
      `POST ${BASE}/api/memory/m1/verify-link`,
      `POST ${BASE}/api/session/s1/anchor`,
      `POST ${BASE}/api/memory/m1/attachments?filename=notes.md`,
      `POST ${BASE}/api/import?filename=notes.md&workspace_agent_id=a1`,
      `POST ${BASE}/api/auth/tokens`,
      `POST ${BASE}/api/auth/tokens/revoke`,
      `POST ${BASE}/api/auth/admin/approve`,
      `POST ${BASE}/api/kernel-bridge/self-test`,
      `POST ${BASE}/api/settings/inference`,
    ])
  })

  it('reads the account routes, and the blob and html-view paths, unchanged', async () => {
    const seen = installFetch()
    const api = await import('./api')
    await api.accountMe().catch(() => {})
    await api.accountSessions()
    await api.accountEvents()
    await api.accountAuth('login', { email: 'a@example.com', password: 'p' })
    await api.accountRequestPasswordReset('a@example.com')
    await api.accountConfirmPasswordReset('r', 'p')
    await api.accountLogout()
    await api.connectLocalDev()
    await api.api.attachmentFile('at1', {})
    expect(api.api.decisionTraceHtmlUrl('s1', 't1', {})).toBe(`${BASE}/api/session/s1/decision-trace.html?trace_id=t1`)
    await api.accountRevokeSession('sess1')
    await api.accountChangePassword('old', 'new')

    expect(seen).toEqual([
      `GET ${BASE}/api/auth/me`,
      `GET ${BASE}/api/auth/sessions`,
      `GET ${BASE}/api/auth/events`,
      `POST ${BASE}/api/auth/login`,
      `POST ${BASE}/api/auth/password-reset/request`,
      `POST ${BASE}/api/auth/password-reset/confirm`,
      `POST ${BASE}/api/auth/logout`,
      `GET ${BASE}/api/status`,
      `GET ${BASE}/api/attachment/at1/file?`,
      `GET ${BASE}/api/auth/csrf`,
      `POST ${BASE}/api/auth/sessions/revoke`,
      `POST ${BASE}/api/auth/password`,
    ])
  })

  /* Method and URL are not the whole wire contract. Task 5d rewrote how `credentials`, the
     headers and the body are composed at thirteen call sites, and none of that is visible in the
     tables above. `console.spec.ts` cannot see it either: the dev proxy injects a bearer token, so
     nothing there exercises the cookie credential. This records the rest. */
  it('sends the session cookie on every request, and composes write headers and bodies unchanged', async () => {
    const full: Array<{ url: string; method: string; credentials?: string; type?: string; csrf?: string; body?: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      full.push({
        url, method: init.method ?? 'GET', credentials: init.credentials,
        type: headers['Content-Type'], csrf: headers['X-Cortex-CSRF-Token'],
        body: typeof init.body === 'string' ? init.body : init.body === undefined ? undefined : 'raw',
      })
      return new Response(JSON.stringify(String(url).endsWith('/api/auth/csrf') ? { csrf_token: 'tok' } : {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const api = await import('./api')
    await api.api.stats()
    await api.api.createProposition({ content: 'c' })
    await api.api.importDocument(file, 'a1')
    await api.accountAuth('login', { email: 'a@example.com', password: 'p' })
    await api.accountLogout()

    // every request carries the cookie: local_api.py authenticates the browser with an HttpOnly,
    // SameSite=Strict session cookie and nothing else
    expect(full.every((c) => c.credentials === 'include')).toBe(true)
    expect(full.map((c) => `${c.method} ${c.url}`)).toEqual([
      `GET ${BASE}/api/stats`,
      `GET ${BASE}/api/auth/csrf`,
      `POST ${BASE}/api/memory/propositions`,
      `POST ${BASE}/api/import?filename=notes.md&workspace_agent_id=a1`,
      `POST ${BASE}/api/auth/login`,
      `POST ${BASE}/api/auth/logout`,
    ])
    // the JSON write: declared type, the CSRF token from the csrf route, the payload verbatim
    const write = full.find((c) => c.url.endsWith('/api/memory/propositions'))!
    expect(write.type).toBe('application/json')
    expect(write.csrf).toBe('tok')
    expect(write.body).toBe(JSON.stringify({ content: 'c' }))
    // the raw upload: the file's own media type, the bytes as the body, not a JSON envelope
    const upload = full.find((c) => c.url.includes('/api/import'))!
    expect(upload.type).toBe('text/markdown')
    expect(upload.body).toBe('raw')
    // sign-in declares JSON and needs no token (it has no session to forge against yet)
    const login = full.find((c) => c.url.endsWith('/api/auth/login'))!
    expect(login.type).toBe('application/json')
    expect(login.csrf).toBeUndefined()
    expect(login.body).toBe(JSON.stringify({ email: 'a@example.com', password: 'p' }))
    // logout posts with no body and no declared type, exactly as it did
    const logout = full.find((c) => c.url.endsWith('/api/auth/logout'))!
    expect(logout.body).toBeUndefined()
    expect(logout.type).toBeUndefined()
  })
})
