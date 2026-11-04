// Sign-in for the console, laid out like Shield's: a story panel (brand, eyebrow, headline, one
// reassurance) beside a form panel (lock mark, Sign in / Create account tabs, labelled fields,
// one primary action, a note on how the session is held).
//
// The credential is an HttpOnly session cookie set by /api/auth/{login,signup}; this code never
// sees or stores a token. Only a non-secret "signed in" hint and the account summary go to
// sessionStorage. There are no quick-fill credentials: a password does not belong in source.
//
// Five modes share the one form: sign in, create account, "forgot password" (ask for an emailed
// link), "reset password" (the page the emailed link opens, `?token=` or managed's `?reset_token=`
// in the address) and "resend verification", which only the hosted backend serves. The wording for
// all of them lives in passwordReset.ts and authNotice.ts so it is tested; in particular, asking
// for a link answers identically whether or not the account exists.
//
// This is the ONE sign-in surface. The hosted edition used to render its own duplicate of this
// form (HostedLanding) because the console spoke `/api/auth/*` and the hosted backend served only
// `/api/managed/*`; hostedApi.ts's table removed that reason. What differs between the editions is
// therefore CAPABILITY, asked through `supports()`, never which component renders: a profile
// endpoint you can point at exists where `/api/status` does, and resend-verification exists where
// the hosted backend does.

import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, accountAuth, accountConfirmPasswordReset, accountMe, accountOAuthProviders, accountRequestPasswordReset, accountResendVerification, api, connectLocalDev, getApiBaseUrl, setApiBaseUrl, type OAuthProvider } from '../api'
import { supports } from '../hostedApi'
import { IconArrowRight, IconGitHub, IconGoogle, IconIntegrity, IconLock } from './icons'
import { SIGNUP_PENDING, VERIFIED, signInError, verifiedFromSearch } from './authNotice'
import { confirmNotice, requestNotice, resetTokenFromSearch, searchWithoutToken, validateNewPassword, type ResetNotice } from './passwordReset'

type Mode = 'login' | 'signup' | 'forgot' | 'reset' | 'resend'

/** `#signup` is how a plan card on the hosted landing opens this form on its second tab. */
const SIGNUP_HASH = '#signup'

/** Where the local profile endpoint is a thing at all: the edition that serves `/api/status`. */
function localProfile(): boolean {
  return supports('GET', '/api/status')
}

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<Mode>(() => (typeof location !== 'undefined' && location.hash === SIGNUP_HASH ? 'signup' : 'login'))
  const [error, setError] = useState(() => {
    try { return sessionStorage.getItem('xibalba-cortex.auth-notice') ?? '' } catch { return '' }
  })
  const [busy, setBusy] = useState(false)
  // A clicked verification link lands here (managed/api.py:227 redirects to `?verified=1`).
  const [notice, setNotice] = useState<ResetNotice | null>(
    () => (typeof location !== 'undefined' && verifiedFromSearch(location.search) ? { tone: 'ok', text: VERIFIED } : null),
  )
  // the secret from an emailed reset link, held in memory only
  const [resetToken, setResetToken] = useState<string | null>(null)
  const [oauthProviders, setOauthProviders] = useState<OAuthProvider[]>([])

  useEffect(() => {
    accountOAuthProviders().then(setOauthProviders).catch(() => {})
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    const err = params.get('error')
    if (err) {
      if (err === 'unverified_email') {
        setError('Your social account does not have a verified email. Please verify it or sign up with email and password.')
      } else if (err === 'invalid_state') {
        setError('Sign-in request timed out or was invalid. Please try again.')
      } else {
        setError(err)
      }
    }
  }, [])

  // Opened from the emailed link: switch to the reset form and take the secret out of the address bar.
  useEffect(() => {
    const token = resetTokenFromSearch(window.location.search)
    if (!token) return
    setResetToken(token)
    setMode('reset')
    window.history.replaceState(null, '', `${window.location.pathname}${searchWithoutToken(window.location.search)}${window.location.hash}`)
  }, [])

  const switchMode = (next: Mode) => {
    setMode(next)
    setError('')
    setNotice(null)
  }

  /* Asking for an email: a reset link, or another verification link. One submit for both, because
     both must answer identically whether or not the account exists -- a different wording for the
     two would be a way to learn which addresses have accounts. */
  const submitForgot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const email = String(new FormData(event.currentTarget).get('email') ?? '').trim()
    const resend = mode === 'resend'
    setBusy(true)
    setError('')
    setNotice(null)
    try {
      await (resend ? accountResendVerification(email) : accountRequestPasswordReset(email))
      setNotice(resend ? { tone: 'ok', text: 'If this account needs this action, an email has been sent.' } : requestNotice(200))
    } catch (e) {
      const note = requestNotice(e instanceof ApiError ? e.status : 0)
      setError(note.text)
    } finally {
      setBusy(false)
    }
  }

  const submitReset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const password = String(form.get('password') ?? '')
    const problem = validateNewPassword(password, String(form.get('confirm') ?? ''))
    if (problem) { setError(problem); return }
    if (!resetToken) { setError(confirmNotice(400).text); return }
    setBusy(true)
    setError('')
    try {
      await accountConfirmPasswordReset(resetToken, password)
      setResetToken(null)
      setMode('login')
      setNotice(confirmNotice(200))
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0
      setError(confirmNotice(status, e instanceof Error ? e.message : '').text)
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    const endpoint = String(form.get('endpoint') ?? '').trim()
    if (endpoint) setApiBaseUrl(endpoint)
    try {
      const payload = await accountAuth(mode === 'signup' ? 'signup' : 'login', {
        email: String(form.get('email') ?? ''),
        password: String(form.get('password') ?? ''),
        display_name: String(form.get('displayName') ?? ''),
      })
      /* No account in the answer means no session was opened: the hosted backend answers signup
         202 and verifies the address first. There is nothing to ask `me` about, and opening a
         workspace here would 401 on its first read. */
      if (!payload.account) {
        setMode('login')
        setNotice({ tone: 'ok', text: SIGNUP_PENDING })
        return
      }
      const me = await accountMe()
      try {
        sessionStorage.setItem('xibalba-cortex.account', JSON.stringify({ ...(me.account ?? payload.account), session_expires_at: me.session_expires_at }))
        sessionStorage.removeItem('xibalba-cortex.auth-notice')
      } catch { /* the account summary is a convenience */ }
      /* Prove the endpoint is a Cortex profile before opening the workspace -- where that is
         provable. The hosted backend serves no `/api/status`, and `me` has just answered from the
         hosted account API, which proves the same thing for that edition. */
      if (localProfile()) await api.status()
      onSignedIn()
    } catch (e) {
      setError(signInError(e instanceof Error ? e.message : String(e)))
    } finally {
      setBusy(false)
    }
  }

  const connectLocal = async () => {
    setBusy(true)
    setError('')
    try {
      await connectLocalDev()
      onSignedIn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="xc-auth">
      <section className="xc-auth-story">
        <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => e.preventDefault()}>
          {/* Its own derivative, not the rail's. Both are inverted from the same dark-ink export
              by viewer/scripts/invert_logo_to_white.py, but the alpha stretch that makes the
              hairline strokes read as solid white has to be the last thing done to the pixels --
              so each size is built at the size it is painted. Scaling the rail's 248px asset up
              to 300 here would undo it. */}
          <img className="xc-brand-lockup" src="/cortex-lockup-hero.png" width={300} height={279} alt="" />
        </a>
        <div className="xc-auth-story-body">
          <p className="xc-eyebrow">Secure operator access</p>
          <h1>Your agents’ memory.<br />Provably yours.</h1>
          <p>Sign in to explore the knowledge graph and timeline, and the provenance behind every remembered fact.</p>
        </div>
        <aside>
          <IconIntegrity />
          <span>
            <b>Local-first authentication</b>
            <small>Your session is held in a secure cookie the browser cannot read.</small>
          </span>
        </aside>
      </section>

      <section className="xc-auth-formwrap">
        <form className="xc-auth-form" onSubmit={mode === 'forgot' || mode === 'resend' ? submitForgot : mode === 'reset' ? submitReset : submit} aria-labelledby="signin-title">
          <span className="xc-lock" aria-hidden="true"><IconLock /></span>
          {import.meta.env.DEV && localProfile() && (mode === 'login' || mode === 'signup') && (
            <button className="xc-btn" type="button" disabled={busy} onClick={connectLocal}>
              <IconIntegrity /> Connect to local Cortex
            </button>
          )}
          {(mode === 'login' || mode === 'signup') && (
            <div className="xc-tabs" role="tablist" aria-label="Account">
              <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'login'} onClick={() => switchMode('login')}>Sign in</button>
              <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'signup'} onClick={() => switchMode('signup')}>Create account</button>
            </div>
          )}
          <h2 id="signin-title" className="xc-auth-title">
            {mode === 'signup' ? 'Create your Cortex account' : mode === 'forgot' ? 'Reset your password' : mode === 'reset' ? 'Choose a new password' : mode === 'resend' ? 'Resend verification email' : 'Welcome back'}
          </h2>
          <p className="xc-auth-lede">
            {mode === 'signup' ? 'Create an operator account for this Cortex profile.'
              : mode === 'forgot' ? 'Enter your account email. If it has an account, we email a link that works for 30 minutes.'
              : mode === 'reset' ? `Use at least 10 characters. The link you followed can be used once.`
              : mode === 'resend' ? 'Enter your account email. If it still needs verifying, we send the link again.'
              : 'Enter your email and password to continue.'}
          </p>

          {(mode === 'login' || mode === 'signup') && oauthProviders.length > 0 && (
            <>
              <div className="xc-auth-social">
                {oauthProviders.map((p) => (
                  <a key={p.id} className="xc-btn xc-auth-social-btn" href={`/api/auth/oauth/${p.id}/authorize`}>
                    {p.id === 'google' && <IconGoogle />}
                    {p.id === 'github' && <IconGitHub />}
                    Continue with {p.name}
                  </a>
                ))}
              </div>
              <div className="xc-auth-divider">
                <span>or continue with email</span>
              </div>
            </>
          )}

          {mode !== 'reset' && (
            <label className="xc-field">Email
              <input className="xc-input" name="email" type="email" autoComplete="username" required autoFocus placeholder="operator@organization.com" />
            </label>
          )}
          {mode === 'signup' && (
            <label className="xc-field">Display name
              <input className="xc-input" name="displayName" autoComplete="name" required placeholder="Alice Chen" />
            </label>
          )}
          {(mode === 'login' || mode === 'signup') && (
            <label className="xc-field">Password
              <input className="xc-input" name="password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={10} required placeholder="••••••••••••" />
            </label>
          )}
          {mode === 'login' && (
            <button type="button" className="xc-link xc-auth-forgot" onClick={() => switchMode('forgot')}>Forgot password?</button>
          )}
          {/* Hosted only, and asked as a capability rather than as an edition: self-hosted verifies
              no addresses and local_api.py serves no such route. This is the one piece of the
              hosted edition's old duplicate form that `/api/auth/*` had no equivalent for. */}
          {(mode === 'login' || mode === 'signup') && supports('POST', '/api/auth/verification/resend') && (
            <button type="button" className="xc-link xc-auth-forgot" onClick={() => switchMode('resend')}>Resend verification email</button>
          )}
          {mode === 'reset' && (
            <>
              <label className="xc-field">New password
                <input className="xc-input" name="password" type="password" autoComplete="new-password" minLength={10} required autoFocus placeholder="••••••••••••" />
              </label>
              <label className="xc-field">Confirm new password
                <input className="xc-input" name="confirm" type="password" autoComplete="new-password" minLength={10} required placeholder="••••••••••••" />
              </label>
            </>
          )}
          {(mode === 'login' || mode === 'signup') && localProfile() && <details className="xc-auth-advanced">
            <summary>Profile endpoint</summary>
            <label className="xc-field">Optional; the default is the same origin
              <input className="xc-input xc-input--mono" name="endpoint" aria-label="Profile endpoint" type="text" inputMode="url" autoCapitalize="none" autoCorrect="off" defaultValue={getApiBaseUrl()} />
            </label>
          </details>}

          {notice && <div className={`xc-callout ${notice.tone === 'ok' ? 'xc-callout--anchored' : 'xc-callout--conflict'}`} role="status">{notice.text}</div>}
          {error && <div className="xc-callout xc-callout--conflict" role="alert">{error}</div>}

          <button className="xc-btn xc-btn--primary xc-auth-submit" type="submit" disabled={busy}>
            {busy ? (mode === 'login' || mode === 'signup' ? 'Connecting…' : 'Working…')
              : mode === 'signup' ? 'Create account'
              : mode === 'forgot' ? 'Send reset link'
              : mode === 'reset' ? 'Change password'
              : mode === 'resend' ? 'Send verification email'
              : 'Sign in'} <IconArrowRight />
          </button>
          {mode !== 'login' && mode !== 'signup' && (
            <button type="button" className="xc-link xc-auth-forgot" onClick={() => { setResetToken(null); switchMode('login') }}>Back to sign in</button>
          )}
          <small className="xc-auth-note"><IconLock /> HttpOnly session cookie</small>
        </form>
      </section>
    </main>
  )
}
