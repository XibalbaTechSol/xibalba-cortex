// Sign-in for the console, laid out like Shield's: a story panel (brand, eyebrow, headline, one
// reassurance) beside a form panel (lock mark, Sign in / Create account tabs, labelled fields,
// one primary action, a note on how the session is held).
//
// The credential is an HttpOnly session cookie set by /api/auth/{login,signup}; this code never
// sees or stores a token. Only a non-secret "signed in" hint and the account summary go to
// sessionStorage. There are no quick-fill credentials: a password does not belong in source.
//
// Four modes share the one form: sign in, create account, "forgot password" (ask for an emailed
// link) and "reset password" (the page the emailed link opens, `?token=` in the address). The
// wording for the last two lives in passwordReset.ts so it is tested; in particular, asking for a
// link answers identically whether or not the account exists.

import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, accountAuth, accountConfirmPasswordReset, accountMe, accountRequestPasswordReset, api, connectLocalDev, getApiBaseUrl, setApiBaseUrl } from '../api'
import { IconArrowRight, IconIntegrity, IconLock } from './icons'
import { confirmNotice, requestNotice, resetTokenFromSearch, searchWithoutToken, validateNewPassword, type ResetNotice } from './passwordReset'

type Mode = 'login' | 'signup' | 'forgot' | 'reset'

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [error, setError] = useState(() => {
    try { return sessionStorage.getItem('xibalba-cortex.auth-notice') ?? '' } catch { return '' }
  })
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<ResetNotice | null>(null)
  // the secret from an emailed reset link, held in memory only
  const [resetToken, setResetToken] = useState<string | null>(null)

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

  const submitForgot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const email = String(new FormData(event.currentTarget).get('email') ?? '').trim()
    setBusy(true)
    setError('')
    setNotice(null)
    try {
      await accountRequestPasswordReset(email)
      setNotice(requestNotice(200))
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
      const me = await accountMe()
      try {
        sessionStorage.setItem('xibalba-cortex.account', JSON.stringify({ ...(me.account ?? payload.account), session_expires_at: me.session_expires_at }))
        sessionStorage.removeItem('xibalba-cortex.auth-notice')
      } catch { /* the account summary is a convenience */ }
      await api.status() // prove the endpoint is a Cortex profile before opening the workspace
      onSignedIn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
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
        <a className="xc-brand" href="#" onClick={(e) => e.preventDefault()}>
          <span className="xc-brand-mark"><img src="/cortex-mark.png" alt="" /></span>
          <b>Xibalba <i>Cortex</i></b>
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
        <form className="xc-auth-form" onSubmit={mode === 'forgot' ? submitForgot : mode === 'reset' ? submitReset : submit} aria-labelledby="signin-title">
          <span className="xc-lock" aria-hidden="true"><IconLock /></span>
          {import.meta.env.DEV && (mode === 'login' || mode === 'signup') && (
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
            {mode === 'signup' ? 'Create your Cortex account' : mode === 'forgot' ? 'Reset your password' : mode === 'reset' ? 'Choose a new password' : 'Welcome back'}
          </h2>
          <p className="xc-auth-lede">
            {mode === 'signup' ? 'Create an operator account for this Cortex profile.'
              : mode === 'forgot' ? 'Enter your account email. If it has an account, we email a link that works for 30 minutes.'
              : mode === 'reset' ? `Use at least 10 characters. The link you followed can be used once.`
              : 'Enter your email and password to continue.'}
          </p>

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
          {(mode === 'login' || mode === 'signup') && <details className="xc-auth-advanced">
            <summary>Profile endpoint</summary>
            <label className="xc-field">Optional; the default is the same origin
              <input className="xc-input xc-input--mono" name="endpoint" type="text" inputMode="url" autoCapitalize="none" autoCorrect="off" defaultValue={getApiBaseUrl()} />
            </label>
          </details>}

          {notice && <div className={`xc-callout ${notice.tone === 'ok' ? 'xc-callout--anchored' : 'xc-callout--conflict'}`} role="status">{notice.text}</div>}
          {error && <div className="xc-callout xc-callout--conflict" role="alert">{error}</div>}

          <button className="xc-btn xc-btn--primary xc-auth-submit" type="submit" disabled={busy}>
            {busy ? (mode === 'forgot' || mode === 'reset' ? 'Working…' : 'Connecting…')
              : mode === 'signup' ? 'Create account'
              : mode === 'forgot' ? 'Send reset link'
              : mode === 'reset' ? 'Change password'
              : 'Sign in'} <IconArrowRight />
          </button>
          {(mode === 'forgot' || mode === 'reset') && (
            <button type="button" className="xc-link xc-auth-forgot" onClick={() => { setResetToken(null); switchMode('login') }}>Back to sign in</button>
          )}
          <small className="xc-auth-note"><IconLock /> HttpOnly session cookie</small>
        </form>
      </section>
    </main>
  )
}
