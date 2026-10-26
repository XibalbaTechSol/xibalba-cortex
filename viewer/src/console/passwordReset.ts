// Password reset, the browser half. Pure helpers so the wording and the URL handling are tested.
//
// The server half (accounts.py, local_api.py) is:
//   POST /api/auth/password-reset/request  {email}
//     200 always for a well-formed request, whether or not the account exists -- the page must say the
//     same thing either way, or it becomes a way to learn which emails have accounts;
//     503 when no email delivery is configured (CORTEX_PASSWORD_RESET_URL unset or the mail failed);
//     429 after too many attempts for this address and client.
//   POST /api/auth/password-reset/confirm  {reset_token, new_password}
//     200 on success; 400 for a bad or expired token, or a password the policy refuses (10+ chars).
// The emailed link is CORTEX_PASSWORD_RESET_URL with `token=<secret>` appended, so the console reads
// `?token=` when it loads, then removes it from the address bar so the secret does not sit in history
// or get copied along with a screenshot of the page.

export const MIN_PASSWORD_LENGTH = 10

/** The reset secret in a query string, or null. Only a plausible token is accepted. */
export function resetTokenFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get('token')
  // token_urlsafe(32) is 43 URL-safe characters; accept a sane range rather than one exact length
  return value && /^[A-Za-z0-9_-]{16,128}$/.test(value) ? value : null
}

/** The same query string without `token`, with its other parameters (agent_id, store_id) intact. */
export function searchWithoutToken(search: string): string {
  const params = new URLSearchParams(search)
  params.delete('token')
  const rest = params.toString()
  return rest ? `?${rest}` : ''
}

export interface ResetNotice { tone: 'ok' | 'error'; text: string }

/** What to tell the person after asking for a link. Identical for "sent" and "no such account". */
export function requestNotice(status: number | null): ResetNotice {
  if (status === null || status === 200) {
    return { tone: 'ok', text: 'If an account exists for that address, a reset link is on its way. The link works for 30 minutes and can be used once.' }
  }
  if (status === 503) {
    return { tone: 'error', text: 'This server cannot send email, so it cannot send a reset link. Ask an administrator to reset your password.' }
  }
  if (status === 429) {
    return { tone: 'error', text: 'Too many attempts for this address. Wait a minute and try again.' }
  }
  return { tone: 'error', text: 'The request could not be sent. Check the address and try again.' }
}

/** What to tell the person after submitting a new password with a reset link. */
export function confirmNotice(status: number | null, serverMessage = ''): ResetNotice {
  if (status === null || status === 200) {
    return { tone: 'ok', text: 'Password changed. Sign in with the new password.' }
  }
  // a policy refusal arrives as 400 with its own wording; an unknown or used token is also 400
  if (status === 400 && /password must be/i.test(serverMessage)) {
    return { tone: 'error', text: `Choose a longer password: ${serverMessage}.` }
  }
  if (status === 400) {
    return { tone: 'error', text: 'This reset link is invalid or has expired. Request a new one.' }
  }
  if (status === 429) return { tone: 'error', text: 'Too many attempts. Wait a minute and try again.' }
  return { tone: 'error', text: 'The password could not be changed. Try again, or request a new link.' }
}

/** Client-side check before the request: the two fields match and meet the length rule. */
export function validateNewPassword(password: string, confirmation: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) return `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  if (password !== confirmation) return 'The two passwords do not match.'
  return null
}
