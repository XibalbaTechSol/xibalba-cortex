// The hosted edition's public landing: the shared landing page, with the hosted pricing section
// and the server's own plan cards as its children.
//
// This content used to live in ManagedApp, passed into the same `<Landing hosted>` from the second
// UI. It is re-homed here, on the console's own signed-out path, so that deleting that UI costs
// the hosted deployment nothing: without it a hosted visitor would arrive at a page with no prices
// and no plan choice.
//
// What this file NO LONGER carries, as of Task 5 Step 6: the login / signup / forgot-password /
// reset / resend-verification form. That was a second copy of `SignIn`, and it existed only
// because the console spoke `/api/auth/*` while the hosted backend served `/api/managed/*`.
// hostedApi.ts maps those paths now, so `SignIn` works on hosted and is the ONE sign-in surface
// for both editions; every control here opens it. The pieces of that form which were not
// duplicates moved with it: `?reset_token=` and `?verified=1` are read by passwordReset.ts and
// authNotice.ts, resend-verification is a `supports()`-gated control in `SignIn`, and the
// expired-session notice is shown by `SignIn`, which already did that for self-hosted.
//
// Plan wording is not reimplemented -- `planRows`, `Plan` and `BILLING_UNAVAILABLE` are the same
// helpers and the same string the signed-in Billing page uses, so the two surfaces cannot word a
// plan differently. `upgradeRefusal` is deliberately NOT used: it refuses every plan when billing
// is unconfigured, and signed out the free plan must still offer "Start free".
// The layout reuses the landing's own Industry primitives (`xc-landing-*`, `xc-win`, `xc-btn`):
// none of the second UI's layout classes are carried over, and no new CSS is added.

import { useEffect, useState } from 'react'
import { Landing } from './Landing'
import { BILLING_UNAVAILABLE, planRows, type Plan } from './billing'
import { hostedRequest } from './hostedWorkspace'

interface Catalog { plans: Plan[]; billing_configured: boolean; signup_enabled: boolean }

const SIGNUP_UNAVAILABLE = 'New workspace registration is not available yet.'

export function HostedLanding({ onSignIn, onSignUp }: { onSignIn: () => void; onSignUp: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    hostedRequest<Catalog>('plans')
      .then((plans) => { if (alive) setCatalog(plans) })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [])

  // Signed out, no plan is current, so every card offers the way in rather than a plan change.
  const rows = catalog ? planRows(catalog.plans, '') : []

  return (
    <Landing hosted onSignIn={onSignIn}>
      <section className="xc-landing-section" id="pricing" aria-labelledby="hosted-plans-title">
        <p className="xc-eyebrow">Managed memory</p>
        <h2 className="xc-landing-h2" id="hosted-plans-title">Choose the capacity you need</h2>
        <div aria-live="polite">
          {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
        </div>
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
              {/* The card is still the gate on registration: a server that says `signup_enabled:
                  false` offers no way in, and a paid plan needs billing configured. `SignIn` does
                  not repeat that check -- the server refuses the signup itself, in its own
                  words -- so this is the one place the catalog is consulted. */}
              <button
                type="button"
                className="xc-btn xc-btn--primary"
                disabled={!catalog?.signup_enabled || (row.id !== 'free' && !catalog?.billing_configured)}
                onClick={onSignUp}
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
    </Landing>
  )
}
