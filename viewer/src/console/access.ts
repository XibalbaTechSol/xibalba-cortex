// Settings → Access and Profile: pure helpers, so the wording a person relies on to decide ("what
// can this token do?", "is that destination set?") is tested rather than inlined in JSX.
//
// The rules these mirror live on the server (console_admin.py): a role carries a fixed set of
// scopes, a caller can only grant roles it holds, a token's secret is shown once, and the profile
// configuration view never carries a path or a secret.

import type { ApiTokenRecord, ProfileConfig } from '../api'

/** What each role lets a credential do, in the words an operator would use. */
export const ROLE_DESCRIPTION: Record<string, string> = {
  reader: 'Read memories, sessions and the graph. Cannot write.',
  writer: 'Read, and record memories and exchanges. Cannot decide reviews.',
  reviewer: 'Read, and accept or reject proposals. Cannot write memories.',
  operator: 'Read, write and forget memories, and decide reviews. Cannot manage accounts.',
  admin: 'Everything, including approving accounts and issuing admin tokens.',
}

export function describeRole(role: string): string {
  return ROLE_DESCRIPTION[role] ?? 'A custom role; see the profile configuration.'
}

/** Lifetimes offered at issue time. A token without an end date is not offered: a leaked one would never stop working. */
export const LIFETIMES: Array<{ hours: number; label: string }> = [
  { hours: 24, label: '1 day' },
  { hours: 24 * 7, label: '7 days' },
  { hours: 24 * 30, label: '30 days (default)' },
  { hours: 24 * 90, label: '90 days' },
  { hours: 24 * 365, label: '1 year' },
]
export const DEFAULT_LIFETIME_HOURS = 24 * 30

export interface TokenRow {
  id: string
  label: string
  role: string
  scopes: string
  created: string
  lastUsed: string
  ends: string
  state: ApiTokenRecord['state']
  /** a plain word for the state tag; colour is never the only signal */
  stateWord: string
  canRevoke: boolean
}

const dayOf = (iso: string | null): string => (iso ? iso.slice(0, 10) : '')

/** Shape the token list: active first, then by newest; revoked and expired ones stay visible but cannot be revoked again. */
export function tokenRows(tokens: ApiTokenRecord[]): TokenRow[] {
  const rank: Record<string, number> = { active: 0, expired: 1, revoked: 2 }
  return [...tokens]
    .sort((a, b) => rank[a.state] - rank[b.state] || (a.created_at < b.created_at ? 1 : -1))
    .map((t) => ({
      id: t.id,
      label: t.label,
      role: t.roles.join(', ') || 'none',
      scopes: t.scopes.join(', ') || 'none',
      created: dayOf(t.created_at),
      lastUsed: t.last_used_at ? dayOf(t.last_used_at) : 'never used',
      ends: t.revoked_at ? `revoked ${dayOf(t.revoked_at)}` : t.expires_at ? `${t.state === 'expired' ? 'expired' : 'expires'} ${dayOf(t.expires_at)}` : 'no end date',
      state: t.state,
      stateWord: t.state === 'active' ? 'active' : t.state === 'expired' ? 'expired' : 'revoked',
      canRevoke: t.state === 'active',
    }))
}

/** A label must be non-empty, at most 80 characters, and not reserved for browser sessions. */
export function validateTokenLabel(label: string): string | null {
  const trimmed = label.trim()
  if (!trimmed) return 'Give the token a label, so you can tell it apart in this list.'
  if (trimmed.length > 80) return 'Use 80 characters or fewer.'
  if (trimmed.startsWith('account:')) return 'Labels starting with "account:" are reserved for browser sessions.'
  return null
}

/** What to say when a request is refused: 403 is "you may not", not "something broke". */
export function adminRefusal(status: number | undefined, message: string): string {
  if (status === 403) return `Your credential may not do this: ${message}`
  return message
}

// ---- profile configuration -----------------------------------------------------------------------------

export interface DestinationRow { id: string; label: string; set: boolean; word: string; what: string }

/**
 * The places the server uses and the browser is never told. The browser only learns whether each one
 * is set, because the actions that depend on them (backup, vault lookup, link verification, anchoring)
 * send an id or a hash, never a path.
 */
export function destinationRows(d: ProfileConfig['destinations']): DestinationRow[] {
  const row = (id: keyof ProfileConfig['destinations'], label: string, what: string): DestinationRow => ({ id, label, set: d[id], word: d[id] ? 'configured' : 'not configured', what })
  return [
    row('backup', 'Backup destination', 'Where Backup writes its verified copy.'),
    row('vault', 'Trust vault', 'The vault a leaf-hash lookup reads.'),
    row('integrity_dag', 'Integrity DAG', 'Where Verify a link looks up cited nodes.'),
    row('anchor_service', 'Anchor service', 'Where a session root is pushed when you anchor it.'),
    row('oracle', 'Integrity oracle', 'Where agent identities are resolved.'),
  ]
}

/** Feature switches as sorted rows, enabled ones first, so what is off is easy to see. */
export function featureRows(features: Record<string, boolean>): Array<{ name: string; on: boolean }> {
  return Object.entries(features)
    .map(([name, on]) => ({ name: name.replace(/_/g, ' '), on: Boolean(on) }))
    .sort((a, b) => Number(b.on) - Number(a.on) || a.name.localeCompare(b.name))
}
