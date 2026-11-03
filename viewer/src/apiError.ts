// The error every data call rejects with, in its own module so that both the self-hosted client
// (api.ts) and the hosted transport (hostedApi.ts) can throw the same type without importing each
// other. api.ts re-exports it, so `import { ApiError } from '../api'` keeps working everywhere.

/**
 * A failed data call, with the HTTP status attached. The server's message alone cannot say whether
 * the session ended: local_api.py answers "invalid or revoked token" for an expired cookie and
 * for a bad bearer token alike, so the console reacts to the status, not to the text.
 */
export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
