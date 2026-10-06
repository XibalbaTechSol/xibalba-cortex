// Sign-in for the console, laid out like Shield's: a story panel (brand, eyebrow, headline, one
// reassurance) beside a form panel (lock mark, Sign in / Create account tabs, labelled fields,
// one primary action, a note on how the session is held).
//
// Same contract as the legacy screen: the credential is an HttpOnly session cookie set by
// /api/auth/{login,signup}; this code never sees or stores a token. Only a non-secret "signed in"
// hint and the account summary go to sessionStorage. There are no quick-fill credentials: a
// password does not belong in source.

import { useState, type FormEvent } from 'react'
import { accountAuth, accountMe, api, connectLocalDev, getApiBaseUrl, setApiBaseUrl } from '../api'
import { IconArrowRight, IconIntegrity, IconLock } from './icons'

type Mode = 'login' | 'signup'

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [error, setError] = useState(() => {
    try { return sessionStorage.getItem('xibalba-cortex.auth-notice') ?? '' } catch { return '' }
  })
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    const endpoint = String(form.get('endpoint') ?? '').trim()
    if (endpoint) setApiBaseUrl(endpoint)
    try {
      const payload = await accountAuth(mode, {
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
        <form className="xc-auth-form" onSubmit={submit} aria-labelledby="signin-title">
          <span className="xc-lock" aria-hidden="true"><IconLock /></span>
          {import.meta.env.DEV && (
            <button className="xc-btn" type="button" disabled={busy} onClick={connectLocal}>
              <IconIntegrity /> Connect to local Cortex
            </button>
          )}
          <div className="xc-tabs" role="tablist" aria-label="Account">
            <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>Sign in</button>
            <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'signup'} onClick={() => setMode('signup')}>Create account</button>
          </div>
          <h2 id="signin-title" className="xc-auth-title">{mode === 'signup' ? 'Create your Cortex account' : 'Welcome back'}</h2>
          <p className="xc-auth-lede">{mode === 'signup' ? 'Create an operator account for this Cortex profile.' : 'Enter your email and password to continue.'}</p>

          <label className="xc-field">Email
            <input className="xc-input" name="email" type="email" autoComplete="username" required autoFocus placeholder="operator@organization.com" />
          </label>
          {mode === 'signup' && (
            <label className="xc-field">Display name
              <input className="xc-input" name="displayName" autoComplete="name" required placeholder="Alice Chen" />
            </label>
          )}
          <label className="xc-field">Password
            <input className="xc-input" name="password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={10} required placeholder="••••••••••••" />
          </label>
          <details className="xc-auth-advanced">
            <summary>Profile endpoint</summary>
            <label className="xc-field">Optional; the default is the same origin
              <input className="xc-input xc-input--mono" name="endpoint" type="text" inputMode="url" autoCapitalize="none" autoCorrect="off" defaultValue={getApiBaseUrl()} />
            </label>
          </details>

          {error && <div className="xc-callout xc-callout--conflict" role="alert">{error}</div>}

          <button className="xc-btn xc-btn--primary xc-auth-submit" type="submit" disabled={busy}>
            {busy ? 'Connecting…' : mode === 'signup' ? 'Create account' : 'Sign in'} <IconArrowRight />
          </button>
          <small className="xc-auth-note"><IconLock /> HttpOnly session cookie</small>
        </form>
      </section>
    </main>
  )
}
