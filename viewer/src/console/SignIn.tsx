// Sign-in for the console. Same contract as the legacy screen: the credential is an HttpOnly
// session cookie set by /api/auth/{login,signup}; this code never sees or stores a token. Only a
// non-secret "signed in" hint and the account summary go to sessionStorage.

import { useState, type FormEvent } from 'react'
import { accountAuth, accountMe, api, getApiBaseUrl, setApiBaseUrl } from '../api'

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
    setApiBaseUrl(String(form.get('endpoint') ?? '').trim())
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

  return (
    <main className="xc-auth">
      <section className="xc-auth-story">
        <p className="xc-eyebrow">Private by architecture</p>
        <h1>Your agents’ memory.<br />Under your control.</h1>
        <p className="xc-copy" style={{ maxWidth: 460, fontSize: 16, lineHeight: 1.55 }}>
          Connect to a local Cortex profile and inspect the provenance behind every remembered fact. Your session is held in a secure cookie the browser cannot read.
        </p>
      </section>

      <form className="xc-win xc-auth-form" onSubmit={submit} aria-labelledby="signin-title">
        <div className="xc-tabs" role="tablist" aria-label="Account">
          <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>Sign in</button>
          <button type="button" role="tab" className="xc-tab" aria-selected={mode === 'signup'} onClick={() => setMode('signup')}>Create account</button>
        </div>
        <div>
          <p className="xc-eyebrow">Cortex</p>
          <h2 id="signin-title" className="xc-title" style={{ marginTop: 8 }}>{mode === 'signup' ? 'Create your account' : 'Connect to Cortex'}</h2>
        </div>

        <label className="xc-field">Profile endpoint <span className="xc-note">optional</span>
          <input className="xc-input xc-input--mono" name="endpoint" type="text" inputMode="url" autoCapitalize="none" autoCorrect="off" defaultValue={getApiBaseUrl()} placeholder="/cortex-api (recommended)" />
        </label>
        <label className="xc-field">Email
          <input className="xc-input" name="email" type="email" autoComplete="username" required autoFocus />
        </label>
        {mode === 'signup' && (
          <label className="xc-field">Display name
            <input className="xc-input" name="displayName" autoComplete="name" required />
          </label>
        )}
        <label className="xc-field">Password
          <input className="xc-input" name="password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={10} required />
        </label>

        {error && <div className="xc-callout xc-callout--conflict" role="alert">{error}</div>}

        <button className="xc-btn xc-btn--primary" type="submit" disabled={busy}>
          {busy ? 'Connecting…' : mode === 'signup' ? 'Create account' : 'Enter workspace'}
        </button>
        <p className="xc-note">HttpOnly session cookie. Password reset is not configured for this local deployment.</p>
      </form>
    </main>
  )
}
