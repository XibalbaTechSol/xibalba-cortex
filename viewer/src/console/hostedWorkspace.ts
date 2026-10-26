// Pure helpers for the two hosted-workspace capabilities that used to live only in the second UI:
// issuing a DID-bound API key (Agents) and exporting every memory in the workspace (Memories).
//
// The gate is `offersHostedWorkspace`, and it reads the server-declared destination list rather
// than any edition flag: `billing` is the one destination a self-hosted server never declares
// (nav.ts keeps it out of `BUILT` for exactly that reason), so its presence in the resolved list
// is the session saying it is a hosted workspace. An absent declaration resolves to `DESTINATIONS`,
// which has no `billing`, so self-hosted is false without a network call of any kind.

import type { Destination } from './nav'

/** True when this session is a hosted workspace, judged only by what the server declared. */
export function offersHostedWorkspace(list: readonly Destination[]): boolean {
  return list.some((d) => d.id === 'billing')
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

/** A call to the hosted account API, shaped exactly like BillingPage's: same-origin cookie session,
 *  and the CSRF token (read from `me`) on every mutation. Only reached from a hosted session. */
export async function hostedRequest<T>(path: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const response = await fetch(`/api/managed/${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-Cortex-CSRF-Token': csrf } : {}), ...init.headers },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data as T
}

export const EXPORT_STARTED = 'Your memory export download has started.'
export const EXPORT_FILENAME = 'cortex-memories.json'
export const EXPORT_DOWNLOAD_PATH = '/api/managed/export-download'
