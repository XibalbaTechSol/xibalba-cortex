// The one place that knows what the HOSTED backend serves, and how the console's calls reach it.
//
// Why this exists: there is one application now (main.tsx boots ConsoleApp for both editions), but
// two backends. The console's data layer speaks the bare `/api/*` routes local_api.py serves, and
// the hosted backend serves 23 routes, all under `/api/managed/`, answering any other `/api/*` with
// 404. Rendering the console at `/managed` therefore pointed a whole data layer at routes that do
// not exist. Every hosted e2e runs behind the Vite dev proxy, which supplies a real local API, so
// the hybrid under test never existed in production and nothing went red.
//
// The rule: ONE table, read by one transport. No call site anywhere asks which edition it is in.
//   - a console path WITH a hosted equivalent is rewritten to it, its query narrowed to the
//     parameters that route actually reads, and its response reshaped to what the console's reader
//     expects (the shapes differ -- see each entry);
//   - a console path WITHOUT one is refused LOCALLY, before any fetch, with a stated reason. The
//     hosted console therefore fires no known-404s: it degrades by design rather than by accident,
//     which is exactly how `loadConsoleData` already treats everything but the graph.
//
// Self-hosted never reaches any of this. The transport is INSTALLED by ConsoleApp, and only when
// the edition is hosted; with nothing installed `hostedActive()` is false and api.ts takes the same
// path it always took. src/apiSelfHosted.test.ts is the recorded proof of that, written and
// committed green before this module existed.

import { ApiError } from './apiError'
import { READ_ONLY_WORKSPACE } from './console/billing'

/** A console path the hosted backend has no route for. Refused locally: nothing is sent. */
export class HostedUnsupported extends ApiError {
  constructor(what: string) {
    // 501, not 404: nothing was asked of the server. The reason names the call so an error that
    // reaches a panel says which capability this edition does not serve.
    super(`The hosted edition does not serve ${what}.`, 501)
    this.name = 'HostedUnsupported'
  }
}

/** A hosted write the workspace's own entitlement forbids. Refused locally: no 402 round-trip. */
export class HostedReadOnly extends ApiError {
  constructor() {
    super(READ_ONLY_WORKSPACE, 402)
    this.name = 'HostedReadOnly'
  }
}

// --- the table ----------------------------------------------------------------------------------

interface Json { [key: string]: unknown }

interface HostedRoute {
  /** the managed path, `$1`/`$2` filled from the console path's wildcard segments */
  to: string
  /** query parameters the managed route reads. Everything else is dropped: sending
   *  `similarity_threshold` or `agent_id` to a route that ignores them only misleads. */
  keep?: readonly string[]
  /** reshape the managed response into what the console's reader expects */
  adapt?: (data: Json) => unknown
  /** rewrite the request body for the managed contract */
  body?: (data: Json) => unknown
  /** a write: gated on the entitlement and carries an Idempotency-Key */
  write?: true
}

/** `/api/memory/*` -> a RegExp over the path with `*` as one path segment. */
function pattern(path: string): RegExp {
  return new RegExp(`^${path.replace(/[.]/g, '\\.').replace(/\*/g, '([^/]+)')}$`)
}

/**
 * Console path (method + path, no query) -> hosted route.
 *
 * Shapes, all verified against src/xibalba_cortex/managed/api.py rather than assumed:
 *  - `graph` returns the same `{nodes, edges}` payload, but reads only `limit` and fixes the
 *    similarity threshold at 0.75;
 *  - `timeline` is `{sessions, nodes}`, so `/api/sessions` takes its `sessions`;
 *  - `memories` (GET) is `{memories}` with NO `has_more`, capped at 50, and it ignores `offset`,
 *    `status` and the workspace scope -- one page is everything this edition will serve, so the
 *    adapter says so rather than leaving `has_more` undefined for a pager to read as false;
 *  - `memories/{id}` is `{memory}`, so it is unwrapped;
 *  - `memories/{id}/verify` is the same `verify_chain` dict `/api/memory/{id}/verify-chain` returns;
 *  - the agent0 trio returns byte-identical envelopes (`{agents,source,query}`, `{agent,source}`,
 *    `{agent_id,reputation,source}`) because both editions call the same gateway;
 *  - `/api/agents` has no hosted route at all, and `useWorkspace` derives `canWrite` from it. On
 *    hosted there is exactly ONE workspace and its writability is the subscription entitlement, so
 *    `me` is reshaped into that single workspace row. Without this, a hosted console is read-only
 *    forever (finding 4) and fires `/api/agents` on every mount;
 *  - `POST /api/memory/propositions` becomes `POST memories {content}`: the hosted route takes only
 *    content and stores it `active`, so the chosen status and evidence class do not survive.
 */
const ROUTES: ReadonlyArray<readonly [string, HostedRoute]> = [
  ['GET /api/graph', { to: 'graph', keep: ['limit'] }],

  ['GET /api/sessions', { to: 'timeline', keep: ['limit'], adapt: (d) => d.sessions ?? [] }],
  ['GET /api/memories', {
    to: 'memories',
    keep: ['q'],
    adapt: (d) => {
      const memories = (d.memories ?? []) as unknown[]
      return { memories, has_more: false, offset: 0, limit: memories.length }
    },
  }],
  ['GET /api/search', { to: 'memories', keep: ['q'], adapt: (d) => d.memories ?? [] }],
  ['GET /api/memory/*/verify-chain', { to: 'memories/$1/verify' }],
  ['GET /api/memory/*', { to: 'memories/$1', adapt: (d) => d.memory }],
  ['GET /api/agent0/search', { to: 'agent0/search', keep: ['q'] }],
  ['GET /api/agent0/agent/*', { to: 'agent0/agent/$1', keep: ['full'] }],
  ['GET /api/agent0/reputation/*', { to: 'agent0/reputation/$1' }],
  ['GET /api/agents', { to: 'me', adapt: workspaceFromMe }],
  ['POST /api/memory/propositions', { to: 'memories', write: true, body: (d) => ({ content: d.content ?? '' }) }],
]

const MATCHERS = ROUTES.map(([key, route]) => {
  const [method, path] = key.split(' ')
  return { method, re: pattern(path), route }
})

/** The single hosted workspace, as `useWorkspace` reads an `/api/agents` row. `store_access` and a
 *  boolean `writable` are what `hasVerifiedStoreScope` requires; without them the row is dropped
 *  (fail closed) and the console stays on the read-only primary profile. */
function workspaceFromMe(me: Json): unknown {
  const account = (me.account ?? {}) as Json
  const entitlement = (me.entitlement ?? {}) as Json
  const counts = (me.counts ?? {}) as Json
  const id = String(account.profile_id ?? 'managed')
  return {
    agents: [{
      agent_id: id,
      store_id: id,
      profile_id: id,
      agent_name: String(account.display_name || 'Your workspace'),
      store_access: entitlement.writable === true ? 'writable' : 'read_only',
      writable: entitlement.writable === true,
      memories: Number(counts.memories ?? 0),
      memories_counted: true,
      // `me` reports no session count and no identity attestation, and "not counted" is not zero:
      // every field the Agents card reads is present and honest rather than absent and undefined.
      sessions: 0,
      sessions_counted: false,
      last_seen_at: null,
      on_chain: false,
      identity_verified: false,
    }],
    oracle_reachable: false,
  }
}

export interface HostedTarget {
  /** the managed path, relative to `/api/managed/` */
  path: string
  route: HostedRoute
}

/** Where a console path goes on hosted, or null when the hosted backend has no route for it. */
export function hostedTarget(method: string, pathWithQuery: string): HostedTarget | null {
  const [path, query = ''] = pathWithQuery.split('?')
  for (const { method: m, re, route } of MATCHERS) {
    if (m !== method.toUpperCase()) continue
    const match = re.exec(path)
    if (!match) continue
    let to = route.to.replace(/\$(\d)/g, (_, n) => match[Number(n)] ?? '')
    const kept = new URLSearchParams()
    if (route.keep?.length) {
      const params = new URLSearchParams(query)
      for (const name of route.keep) {
        const value = params.get(name)
        if (value !== null && value !== '') kept.set(name, value)
      }
    }
    if ([...kept].length > 0) to += `?${kept.toString()}`
    return { path: to, route }
  }
  return null
}

// --- the session this transport speaks for ------------------------------------------------------

let active = false
let writable: boolean | undefined
let csrf: string | undefined
const writeKeys = new Map<string, string>()

/** Turn the hosted mapping on. Called by ConsoleApp when, and only when, the edition is hosted. */
export function installHostedTransport(): void {
  active = true
}

/** Turn it off and forget the session. Used by the tests, and on sign-out. */
export function clearHostedTransport(): void {
  active = false
  writable = undefined
  csrf = undefined
  writeKeys.clear()
}

export function hostedActive(): boolean {
  return active
}

/** What `GET /api/managed/me` tells the data layer: the CSRF token every mutation needs, and
 *  whether the subscription may still be written to. Fed from ConsoleApp's own `me` call and
 *  refreshed by every `me` that passes through this transport, so there is one copy of it. */
export function setHostedSession(me: { entitlement?: { writable?: boolean } | null; csrf_token?: string } | null): void {
  if (!me) { writable = undefined; csrf = undefined; return }
  if (typeof me.entitlement?.writable === 'boolean') writable = me.entitlement.writable
  if (typeof me.csrf_token === 'string') csrf = me.csrf_token
}

/** True / false / undefined when no `me` has been seen yet. */
export function hostedWritable(): boolean | undefined {
  return writable
}

// --- idempotency keys ---------------------------------------------------------------------------

function newKey(): string {
  try { return crypto.randomUUID() } catch { /* no WebCrypto: fall through */ }
  return `write-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

/**
 * The `Idempotency-Key` for one LOGICAL write, keyed on what is being written.
 *
 * The hosted backend requires the header on `memories` and `import`, fingerprints the body under
 * it, and refuses a reused key carrying different content -- so the key has to follow the payload,
 * not the attempt. A retry of the same write (same path, same body) gets the SAME key, so a write
 * that failed after the server stored it cannot double-store; a different write gets a different
 * one. `releaseWriteKey` is called on success, so writing the same text twice on purpose is two
 * writes rather than a silently swallowed duplicate.
 */
export function writeKeyFor(fingerprint: string): string {
  const existing = writeKeys.get(fingerprint)
  if (existing) return existing
  const key = newKey()
  writeKeys.set(fingerprint, key)
  return key
}

export function releaseWriteKey(fingerprint: string): void {
  writeKeys.delete(fingerprint)
}

// --- the transport ------------------------------------------------------------------------------

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * One call to the hosted account API, by its managed-relative path (`me`, `keys`, `memories`).
 * This is the only fetch to `/api/managed/*` in the app: the console's own `hostedRequest` and the
 * Billing page's `managed()` were two identical copies of it, and both now come through here, so
 * the CSRF token, the idempotency key and the error type have one definition.
 *
 * Same-origin cookie session; the CSRF token comes from `me` (passed in, or the one this transport
 * already holds) and is required on every hosted mutation.
 */
export async function hostedFetch<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const sent = token ?? csrf
  const fingerprint = `${method} ${path} ${typeof init.body === 'string' ? init.body : ''}`
  const idempotency: Record<string, string> = method === 'POST' ? { 'Idempotency-Key': writeKeyFor(fingerprint) } : {}
  const response = await fetch(`/api/managed/${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { ...JSON_HEADERS, ...(sent ? { 'X-Cortex-CSRF-Token': sent } : {}), ...idempotency, ...(init.headers as Record<string, string> | undefined) },
  })
  const data = (await response.json().catch(() => ({}))) as Json
  if (!response.ok) throw new ApiError(String(data.error || `Request failed (${response.status})`), response.status)
  if (method === 'POST') releaseWriteKey(fingerprint)
  // one copy of the session state: whoever asks `me` refreshes the entitlement for everyone
  if (path === 'me') setHostedSession(data as Parameters<typeof setHostedSession>[0])
  return data as T
}

/**
 * api.ts's transport when the hosted mapping is installed: resolve the console path through the
 * table, refuse locally when there is no route, and hand back a Response carrying the ADAPTED
 * body, so api.ts's own `getJson`/`postJson` keep working untouched.
 */
export async function hostedSend(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const target = hostedTarget(method, path)
  if (!target) throw new HostedUnsupported(`${method} ${path.split('?')[0]}`)
  // fail fast, locally, with the reason: do not spend a round-trip on a write the subscription
  // already forbids, and do not leave the explanation on a different page from the control
  if (target.route.write && writable === false) throw new HostedReadOnly()

  const body = target.route.body && typeof init.body === 'string'
    ? JSON.stringify(target.route.body(JSON.parse(init.body) as Json))
    : init.body

  const sent = { ...init, body }
  const data = await hostedFetch<Json>(target.path, sent)
  const adapted = target.route.adapt ? target.route.adapt(data) : data
  return new Response(JSON.stringify(adapted ?? null), { status: 200, headers: JSON_HEADERS })
}
