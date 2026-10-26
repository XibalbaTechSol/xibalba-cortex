// Pure helpers for the two hosted-workspace capabilities that used to live only in the second UI:
// issuing a DID-bound API key (Agents) and exporting every memory in the workspace (Memories).
//
// The gate is `workspaceSession`, and the signal it reads is explicit: the hosted account API
// answered for this browser. It used to be inferred from the nav list instead -- `billing` is the
// one destination a self-hosted server never declares -- which overloaded one signal: a hosted
// deployment that stopped declaring `billing` would have silently lost its API keys and its
// export. So the two questions are now separate. "Is this a hosted workspace?" is answered by the
// session; "did it declare its billing destination?" is a check on the declaration, and a hosted
// session missing it reports a fault instead of quietly dropping a surface.
//
// Self-hosted reaches none of this: `workspaceSession(null)` is the whole path, and no network
// call of any kind is made.

import { hostedFetch } from '../hostedApi'
import { DESTINATIONS, destinationsFrom, type Destination } from './nav'

/** True when a resolved destination list contains the hosted-only destination. The declaration
 *  check, not the capability gate -- see `workspaceSession`. */
export function offersHostedWorkspace(list: readonly Destination[]): boolean {
  return list.some((d) => d.id === 'billing')
}

export const BILLING_UNDECLARED = 'This hosted workspace did not declare its billing destination, so Billing is unreachable. The server’s destination list is wrong.'

/** What `GET /api/managed/me` tells the console about the session itself. */
export interface HostedMe {
  destinations?: readonly string[] | null
  /** Needed to sign out: the hosted API requires it on every mutation. */
  csrf_token?: string
}

export interface WorkspaceSession {
  /** True only because the hosted account API answered -- never because of what it listed. */
  hosted: boolean
  /** The destinations to navigate, resolved through nav.ts. */
  destinations: readonly Destination[]
  /** Set when a hosted session's declaration is missing `billing`. */
  fault: string | null
}

/** The session, from the hosted `me` payload or `null` when there is no hosted session. */
export function workspaceSession(me: HostedMe | null): WorkspaceSession {
  if (!me) return { hosted: false, destinations: DESTINATIONS, fault: null }
  const destinations = destinationsFrom(me.destinations)
  return { hosted: true, destinations, fault: offersHostedWorkspace(destinations) ? null : BILLING_UNDECLARED }
}

const DECLARATION = /^MANAGED_DESTINATIONS\s*=\s*\(([^)]*)\)/m

/** The ids `MANAGED_DESTINATIONS` declares, read out of the Python source that defines them.
 *  Used by the test that guards the real declaration: a list copied into a test cannot catch the
 *  backend dropping one. Throws rather than returning an empty list, which would pass vacuously. */
export function declaredDestinations(source: string): string[] {
  const match = DECLARATION.exec(source)
  if (!match) throw new Error('MANAGED_DESTINATIONS is not declared in the source given')
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
}

export const AGENT_DID_REQUIRED = 'Enter at least one agent DID'

export type AgentDids = { ok: true; agentIds: string[] } | { ok: false; error: string }

/** The DIDs a key will be bound to: one per line or comma-separated, trimmed, de-duplicated.
 *  An empty result is refused rather than issuing a credential bound to nothing. */
export function parseAgentDids(input: string): AgentDids {
  const agentIds = [...new Set(input.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean))]
  if (agentIds.length === 0) return { ok: false, error: AGENT_DID_REQUIRED }
  return { ok: true, agentIds }
}

export interface ApiKey {
  id: string
  label: string
  expires_at: string
  agent_ids?: string[]
}

export interface KeyRow {
  id: string
  label: string
  /** "1 agent" / "N agents", or "unbound" when the key names none. */
  agents: string
  expires: string
}

/** One readable row per issued key. The date is fixed to en-US/UTC so the row reads the same on
 *  every machine -- the server stores the expiry in UTC, and a local rendering shifted it a day. */
export function keyRows(keys: readonly ApiKey[]): KeyRow[] {
  return keys.map((key) => {
    const count = key.agent_ids?.length ?? 0
    return {
      id: key.id,
      label: key.label.replace(/^managed-api:/, ''),
      agents: count === 0 ? 'unbound' : `${count} agent${count === 1 ? '' : 's'}`,
      expires: new Date(key.expires_at).toLocaleDateString('en-US', { timeZone: 'UTC' }),
    }
  })
}

// --- the one impure part: the hosted API call these surfaces make -------------------------------

export interface HostedSession { csrf_token: string }

/** A call to the hosted account API. This used to be its own fetch, byte-identical to the one in
 *  BillingPage; both are now the single transport in hostedApi.ts, which owns the same-origin
 *  cookie session, the CSRF token, the `Idempotency-Key` on writes, and the `ApiError` type the
 *  console's 401 handling reads. Only reached from a hosted session. */
export const hostedRequest = hostedFetch

export const EXPORT_STARTED = 'Your memory export download has started.'
export const EXPORT_FILENAME = 'cortex-memories.json'
export const EXPORT_DOWNLOAD_PATH = '/api/managed/export-download'
