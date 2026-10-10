// Pure helpers for Settings → Account: the account routes return loosely-typed rows (account
// columns, token metadata, auth_events), so show them without inventing structure.

/** Render any JSON scalar for a key/value list: null is "none", objects are compact JSON. */
export function asText(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'none'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

export interface SessionRow {
  id: string
  label: string
  created: string
  lastUsed: string
  revoked: boolean
}

/**
 * Shape rows from GET /api/auth/sessions (ingest_tokens metadata: id, label, created_at,
 * last_used_at, revoked_at, expires_at). Newest first; a row without an id cannot be revoked and
 * is dropped rather than shown with a button that would act on nothing.
 */
export function sessionRows(sessions: Array<Record<string, unknown>>): SessionRow[] {
  return sessions
    .filter((s) => typeof s.id === 'string' && s.id !== '')
    .map((s) => ({
      id: s.id as string,
      label: asText(s.label),
      created: asText(s.created_at),
      lastUsed: s.last_used_at ? asText(s.last_used_at) : 'never',
      revoked: Boolean(s.revoked_at),
    }))
    .sort((a, b) => (a.created < b.created ? 1 : a.created > b.created ? -1 : 0))
}
