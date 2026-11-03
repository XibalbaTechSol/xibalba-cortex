// The sign-in wording the two editions used to duplicate.
//
// Before the consolidation there were two signed-out surfaces, each with its own copy of these
// strings: SignIn.tsx for `/api/auth/*` and HostedLanding.tsx for `/api/managed/*`. The second is
// gone, so the strings it carried that are NOT about a password reset live here, as pure values
// and pure functions, for the same reason passwordReset.ts exists -- wording a person reads after
// a refusal is behaviour, and behaviour is tested.

/** What the server's own refusal becomes when it means "verify your email first". */
export const UNVERIFIED = 'Your email is not verified yet. Open the newest “Verify your Cortex account” email, click its link, then sign in again.'

/** After a clicked verification link, which the hosted backend redirects to `?verified=1`. */
export const VERIFIED = 'Email verified. Sign in to open your workspace.'

/** After signup, on either edition: a new account verifies before its first sign-in. */
export const SIGNUP_PENDING = 'Check your email for a verification link. Verify your address before signing in.'

/* The two refusals that mean the same thing, from the two places that raise them:
   accounts.py:225 (`issue_account_session`, both editions) and managed/api.py:126
   (`authenticate`, once a session exists). Matched as whole strings rather than by keyword, so a
   different failure is never relabelled as a verification problem. */
const VERIFICATION_REFUSALS: readonly string[] = [
  'account requires email verification or administrator approval',
  'Account verification is required',
]

/** The message to show for a failed sign-in: the server's own, unless it is the refusal above. */
export function signInError(message: string): string {
  return VERIFICATION_REFUSALS.includes(message) ? UNVERIFIED : message
}

/** Did this page load come from a clicked verification link? (managed/api.py:227) */
export function verifiedFromSearch(search: string): boolean {
  return new URLSearchParams(search).has('verified')
}
