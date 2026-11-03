// The hosted edition's signed-out page: the public landing, with the hosted pricing section, the
// plan cards and the account forms as its children.
//
// This content used to live in ManagedApp, passed into the same `<Landing hosted>` from the
// second UI. It is re-homed here, on the console's own signed-out path, so that deleting that UI
// costs the hosted deployment nothing: without it a hosted visitor would arrive at a page with no
// prices, no plan choice and no way to create an account.
//
// Plan wording is not reimplemented -- `planRows`, `Plan` and `BILLING_UNAVAILABLE` are the same
// helpers and the same string the signed-in Billing page uses, so the two surfaces cannot word a
// plan differently. `upgradeRefusal` is deliberately NOT used: it refuses every plan when billing
// is unconfigured, and signed out the free plan must still offer "Start free".
// The layout reuses the landing's own Industry primitives (`xc-landing-*`, `xc-win`, `xc-btn`,
// `xc-field`, `xc-input`): none of the second UI's layout classes are carried over, and no new
// CSS is added.

import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Landing } from './Landing'
import { BILLING_UNAVAILABLE, planRows, type Plan } from './billing'
import { hostedRequest } from './hostedWorkspace'

interface Catalog { plans: Plan[]; billing_configured: boolean; signup_enabled: boolean }

type AuthMode = 'login' | 'signup' | 'forgot-password' | 'resend-verification' | 'reset'

const AUTH_ANCHOR = 'hosted-auth'
const SIGNUP_UNAVAILABLE = 'New workspace registration is not available yet.'
const VERIFIED = 'Email verified. Sign in to open your workspace.'
const UNVERIFIED = 'Your email is not verified yet. Open the newest “Verify your Cortex account” email, click its link, then sign in again.'
const AUTH_NOTICE_KEY = 'xibalba-cortex.auth-notice'

const TITLE: Record<AuthMode, string> = {
  login: 'Sign in to managed Cortex',
  signup: 'Create your workspace',
  'forgot-password': 'Reset your password',
  'resend-verification': 'Resend verification email',
  reset: 'Set a new password',
}

const SUBMIT: Record<AuthMode, string> = {
  login: 'Sign in',
  signup: 'Create workspace',
  'forgot-password': 'Send email',
  'resend-verification': 'Send email',
  reset: 'Set password',
}

/** A recovery mode asks the server to send an email; it never opens a session. */
const RECOVERY: readonly AuthMode[] = ['forgot-password', 'resend-verification', 'reset']

function query(): URLSearchParams {
  return new URLSearchParams(typeof location === 'undefined' ? '' : location.search)
}

export function HostedLanding({ onSignedIn }: { onSignedIn: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [mode, setMode] = useState<AuthMode | null>(() => (query().has('reset_token') ? 'reset' : null))
  const resetToken = useRef(query().get('reset_token') ?? '')
  const [busy, setBusy] = useState(false)
  // An expired hosted session leaves its reason here on the way out; it is this page's first message.
  const [error, setError] = useState(() => {
    try { const held = sessionStorage.getItem(AUTH_NOTICE_KEY) ?? ''; sessionStorage.removeItem(AUTH_NOTICE_KEY); return held } catch { return '' }
  })
  const [notice, setNotice] = useState(() => (query().has('verified') ? VERIFIED : ''))

  useEffect(() => {
    if (resetToken.current) history.replaceState(null, '', location.pathname)
    let alive = true
    hostedRequest<Catalog>('plans')
      .then((plans) => { if (alive) setCatalog(plans) })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [])

  // opening a form from a plan card scrolls it into view: the cards are above it
  useEffect(() => {
    if (mode) document.getElementById(AUTH_ANCHOR)?.scrollIntoView({ block: 'center' })
  }, [mode])

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!mode) return
    const fields = Object.fromEntries(new FormData(event.currentTarget))
    setBusy(true)
    setError('')
    setNotice('')
    const recovery = RECOVERY.includes(mode)
    const path = recovery ? `recovery/${mode}` : mode === 'signup' ? 'signup' : 'login'
    const body = { ...fields, ...(mode === 'reset' ? { token: resetToken.current } : {}) }
    hostedRequest(path, { method: 'POST', body: JSON.stringify(body) })
      .then(() => {
        if (mode === 'reset') {
          resetToken.current = ''
          setMode('login')
          setNotice('Password reset. Sign in with your new password.')
        } else if (recovery) {
          setNotice('If this account needs this action, an email has been sent.')
        } else if (mode === 'signup') {
          setNotice('Check your email for a verification link. Verify your address before signing in.')
        } else {
          onSignedIn()
        }
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : 'Request failed'
        setError(message === 'account requires email verification or administrator approval' ? UNVERIFIED : message)
      })
      .finally(() => setBusy(false))
  }

  const messages = (
    <div aria-live="polite">
      {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
      {notice && <p className="xc-callout">{notice}</p>}
    </div>
  )

  // Signed out, no plan is current, so every card offers the way in rather than a plan change.
  const rows = catalog ? planRows(catalog.plans, '') : []

  return (
    <Landing hosted onSignIn={() => setMode('login')}>
      <section className="xc-landing-section" id="pricing" aria-labelledby="hosted-plans-title">
        <p className="xc-eyebrow">Managed memory</p>
        <h2 className="xc-landing-h2" id="hosted-plans-title">Choose the capacity you need</h2>
        {!mode && messages}
        <div className="xc-landing-grid">
          {rows.map((row) => (
            <article className="xc-win xc-landing-card" key={row.id} aria-label={`${row.name} plan`}>
              <p className="xc-eyebrow">{row.name}</p>
              <h3 className="xc-title">{row.price}</h3>
              <p className="xc-note">USD · monthly subscription</p>
              <dl className="xc-kv">
                {row.limits.map((limit) => <div key={limit.label}><dt>{limit.label}</dt><dd>{limit.value}</dd></div>)}
              </dl>
              <p className="xc-copy">Isolated memory storage, a verifiable event history, lexical search, API keys, and data export.</p>
              <button
                type="button"
                className="xc-btn xc-btn--primary"
                disabled={busy || !catalog?.signup_enabled || (row.id !== 'free' && !catalog?.billing_configured)}
                onClick={() => setMode('signup')}
              >
                {row.id === 'free' ? 'Start free' : `Choose ${row.name}`}
              </button>
            </article>
          ))}
        </div>
        {catalog && !catalog.billing_configured && <p className="xc-note">{BILLING_UNAVAILABLE}</p>}
        {catalog && !catalog.signup_enabled && <p className="xc-note">{SIGNUP_UNAVAILABLE}</p>}
        <p className="xc-note">Limits reset monthly in UTC. Each memory supports up to 16 KiB of text. These plans cover memory storage and lexical retrieval; hosted inference is not included yet. Team provides higher workspace capacity; shared user seats are not offered in this release.</p>
      </section>

      {mode && (
        <section className="xc-landing-section" id={AUTH_ANCHOR} aria-labelledby="hosted-auth-title">
          <h2 className="xc-landing-h2" id="hosted-auth-title">{TITLE[mode]}</h2>
          {messages}
          <form onSubmit={submit}>
            {mode === 'signup' && <label className="xc-field">Name<input className="xc-input" name="display_name" autoComplete="name" required maxLength={120} /></label>}
            {mode !== 'reset' && <label className="xc-field">Email<input className="xc-input" name="email" type="email" autoComplete="username" required /></label>}
            {!RECOVERY.includes(mode) || mode === 'reset' ? (
              <label className="xc-field">Password<input className="xc-input" name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={10} required /></label>
            ) : null}
            <div className="xc-landing-cta">
              <button className="xc-btn xc-btn--primary" disabled={busy || (mode === 'signup' && !catalog?.signup_enabled)}>{busy ? 'Working…' : SUBMIT[mode]}</button>
              <button className="xc-btn" type="button" disabled={busy || (mode === 'login' && !catalog?.signup_enabled)} onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>{mode === 'login' ? 'Create an account' : 'I already have an account'}</button>
              <button className="xc-btn" type="button" disabled={busy} onClick={() => setMode('forgot-password')}>Forgot password</button>
              <button className="xc-btn" type="button" disabled={busy} onClick={() => setMode('resend-verification')}>Resend verification</button>
            </div>
          </form>
        </section>
      )}
    </Landing>
  )
}
