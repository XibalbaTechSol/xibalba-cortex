// Billing: the hosted edition's plans and subscription, as an ordinary console page. It reads the
// existing /api/managed/{plans,me} routes and starts a payment through /api/managed/{checkout,portal}.
// A self-hosted server does not list this destination, so it never renders there.

import { useState } from 'react'
import { useAsync } from '../useAsync'
import { IconWarn } from '../icons'
import { paymentDestination, planAction, planRows, upgradeRefusal, usageRows, type Plan } from '../billing'
import { Page } from './Page'

interface Catalog { plans: Plan[]; billing_configured: boolean }
interface Me {
  entitlement: { plan: Plan; status: string; writable: boolean; cancel_at_period_end: boolean }
  usage: { month: string; used: Record<string, number> }
  counts: Record<string, number>
  csrf_token: string
}

async function managed<T>(path: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const response = await fetch(`/api/managed/${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-Cortex-CSRF-Token': csrf } : {}), ...init.headers },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data as T
}

export function BillingPage() {
  const state = useAsync(async () => {
    const [catalog, me] = await Promise.all([managed<Catalog>('plans'), managed<Me>('me')])
    return { catalog, me }
  }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const start = async (kind: 'checkout' | 'portal', planId: string, csrf: string) => {
    setError('')
    setBusy(true)
    try {
      const result = await managed<{ url: string }>(kind, { method: 'POST', body: JSON.stringify(kind === 'checkout' ? { plan: planId } : {}) }, csrf)
      location.assign(paymentDestination(result.url))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  const { catalog, me } = state.data ?? { catalog: null, me: null }
  const refusal = catalog ? upgradeRefusal(catalog.billing_configured, '') : null
  const rows = catalog && me ? planRows(catalog.plans, me.entitlement.plan.id) : []

  return (
    <Page eyebrow="System" title="Billing" note="Plans and the subscription for this workspace. Limits reset monthly in UTC.">
      {state.loading && <p className="xc-note" role="status">Loading plans…</p>}
      {state.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{state.error}</div>}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {catalog && me && (
        <>
          {!me.entitlement.writable && <div className="xc-callout xc-callout--review" role="status"><IconWarn />This workspace is read-only. Your existing memories remain available to read. Update billing to resume writes.</div>}
          <section className="xc-win" aria-label="Subscription">
            <h2 className="xc-title">Subscription</h2>
            <p className="xc-note">Plan: {me.entitlement.plan.name} · status: {me.entitlement.status}{me.entitlement.cancel_at_period_end ? ' · cancels at the end of the paid period' : ''}</p>
            <dl className="xc-kv" aria-label={`Usage for ${me.usage.month} UTC`}>
              {usageRows(me.entitlement.plan, me.usage, me.counts.memories ?? 0).map((u) => <div key={u.label}><dt>{u.label}</dt><dd>{u.value}</dd></div>)}
            </dl>
            <button type="button" className="xc-btn" disabled={busy || refusal !== null} onClick={() => void start('portal', '', me.csrf_token)}>Manage billing</button>
          </section>
          {rows.map((row) => {
            const plan = catalog.plans.find((p) => p.id === row.id)!
            const action = planAction(me.entitlement.plan.id, plan)
            return (
              <section key={row.id} className="xc-win" aria-label={`${row.name} plan`}>
                <p className="xc-eyebrow">{row.name}</p>
                <h2 className="xc-title">{row.price}</h2>
                <dl className="xc-kv">
                  {row.limits.map((l) => <div key={l.label}><dt>{l.label}</dt><dd>{l.value}</dd></div>)}
                </dl>
                <button type="button" className="xc-btn xc-btn--primary" disabled={busy || action.disabled || refusal !== null || action.kind === null} onClick={() => action.kind && void start(action.kind, row.id, me.csrf_token)}>{action.label}</button>
              </section>
            )
          })}
          {refusal && <p className="xc-note">{refusal}</p>}
        </>
      )}
    </Page>
  )
}
