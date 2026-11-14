// Billing: the hosted edition's plans and subscription, as an ordinary console page. It reads the
// existing /api/managed/{plans,me} routes and starts a payment through /api/managed/{checkout,portal}.
// A self-hosted server does not list this destination, so it never renders there.

import { useState } from 'react'
import { useAsync } from '../useAsync'
import { IconCheck, IconInfo, IconLock, IconWarn } from '../icons'
import {
  READ_ONLY_WORKSPACE,
  consumeBillingReturn,
  formatPeriodDate,
  paymentDestination,
  planAction,
  planRows,
  statusMeta,
  subscriptionStatusText,
  upgradeRefusal,
  usageRows,
  type Plan,
} from '../billing'
import { hostedRequest as managed } from '../hostedWorkspace'
import { Page } from './Page'

interface Catalog { plans: Plan[]; billing_configured: boolean }
interface Me {
  entitlement: {
    plan: Plan
    status: string
    writable: boolean
    cancel_at_period_end: boolean
    period_end?: number | null
  }
  usage: { month: string; used: Record<string, number> }
  counts: Record<string, number>
  csrf_token: string
}

export function BillingPage() {
  const state = useAsync(async () => {
    const [catalog, me] = await Promise.all([managed<Catalog>('plans'), managed<Me>('me')])
    return { catalog, me }
  }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retInfo] = useState(() => consumeBillingReturn())

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
  const usage = catalog && me ? usageRows(me.entitlement.plan, me.usage, me.counts.memories ?? 0) : []
  const anyAtLimit = usage.some((u) => u.atLimit)
  const anyNearLimit = usage.some((u) => u.nearLimit)
  const meta = me ? statusMeta(me.entitlement.status) : null

  return (
    <Page eyebrow="System" title="Billing" note="Plans and the subscription for this workspace. Limits reset monthly in UTC.">
      {state.loading && <p className="xc-note" role="status">Loading plans…</p>}
      {state.error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{state.error}</div>}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}

      {/* Stripe Checkout / Portal return alerts */}
      {retInfo === 'success' && (
        <div className="xc-callout xc-callout--anchored" role="status">
          <IconCheck />
          <div>
            <strong>Checkout completed successfully.</strong>
            <p>Your workspace plan has been upgraded. Subscription limits are updated immediately.</p>
          </div>
        </div>
      )}
      {retInfo === 'canceled' && (
        <div className="xc-callout xc-callout--review" role="status">
          <IconInfo />
          <div>
            <strong>Checkout canceled.</strong>
            <p>The Stripe checkout session was canceled. No changes were made to your subscription.</p>
          </div>
        </div>
      )}

      {catalog && !catalog.billing_configured && (
        <div className="xc-callout xc-callout--muted" role="status">
          <IconLock />
          <div>
            <strong>Stripe billing is not configured on this control plane.</strong>
            <p>The control plane is operating in local/evaluation mode. Memory reads and exports remain available.</p>
          </div>
        </div>
      )}

      {catalog && me && (
        <>
          {!me.entitlement.writable && <div className="xc-callout xc-callout--review" role="status"><IconWarn />{READ_ONLY_WORKSPACE}</div>}
          <section className="xc-win" aria-label="Subscription">
            <div className="xc-billing-card-header">
              <div>
                <h2 className="xc-title">Subscription & Quotas</h2>
                <p className="xc-note">{subscriptionStatusText(me.entitlement)}</p>
              </div>
              {meta && (
                <span className={`status-pill tone-${meta.tone}`}>
                  {meta.label}
                </span>
              )}
            </div>

            {anyAtLimit && (
              <div className="xc-callout xc-callout--conflict" role="alert">
                <IconWarn />Monthly quota reached on one or more resources. Writes may be suspended.
              </div>
            )}
            {!anyAtLimit && anyNearLimit && (
              <div className="xc-callout xc-callout--review" role="status">
                <IconWarn />Usage is at or above 80% of your plan quota.
              </div>
            )}

            <div className="xc-billing-metrics-grid">
              <div className="xc-metric-box">
                <span className="xc-metric-eyebrow">CURRENT TIER</span>
                <div className="xc-metric-value">{me.entitlement.plan.name}</div>
                <span className="xc-metric-meta">
                  {rows.find((r) => r.id === me.entitlement.plan.id)?.price || '$0 / month'}
                </span>
              </div>

              <div className="xc-metric-box">
                <span className="xc-metric-eyebrow">BILLING CYCLE</span>
                <div className="xc-metric-value">
                  {me.entitlement.period_end ? formatPeriodDate(me.entitlement.period_end) : `${me.usage.month} UTC`}
                </div>
                <span className="xc-metric-meta">
                  {me.entitlement.cancel_at_period_end
                    ? 'Cancels at period end'
                    : me.entitlement.period_end
                    ? 'Automatic renewal'
                    : 'Monthly reset'}
                </span>
              </div>

              <div className="xc-metric-box xc-metric-box--wide">
                <span className="xc-metric-eyebrow">RESOURCE ALLOCATION & USAGE</span>
                <dl className="xc-kv" aria-label={`Usage for ${me.usage.month} UTC`}>
                  {usage.map((u) => (
                    <div key={u.label} className="xc-usage-row">
                      <div className="xc-usage-header">
                        <dt>{u.label}</dt>
                        <dd>{u.value}</dd>
                      </div>
                      <div
                        className={`xc-meter ${u.atLimit ? 'xc-meter--conflict' : u.nearLimit ? 'xc-meter--review' : ''}`}
                        role="progressbar"
                        aria-valuenow={u.percent}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label={`${u.label}: ${u.percent}%`}
                      >
                        <i style={{ width: `${u.percent}%` }} />
                      </div>
                    </div>
                  ))}
                </dl>
              </div>
            </div>

            <div className="xc-billing-actions">
              <button
                type="button"
                className="xc-btn"
                disabled={busy || refusal !== null}
                onClick={() => void start('portal', '', me.csrf_token)}
              >
                Manage billing
              </button>
            </div>
          </section>

          <div className="xc-catalog-grid">
            {rows.map((row) => {
              const plan = catalog.plans.find((p) => p.id === row.id)!
              const action = planAction(me.entitlement.plan.id, plan)
              return (
                <section key={row.id} className={`xc-win ${row.current ? 'xc-win--current-plan' : ''}`} aria-label={`${row.name} plan`}>
                  <div className="xc-plan-header">
                    <p className="xc-eyebrow">{row.name}</p>
                    {row.current && <span className="status-pill tone-active">Current</span>}
                  </div>
                  <h2 className="xc-title">{row.price}</h2>
                  <dl className="xc-kv">
                    {row.limits.map((l) => (
                      <div key={l.label}>
                        <dt>{l.label}</dt>
                        <dd>{l.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <button
                    type="button"
                    className="xc-btn xc-btn--primary"
                    disabled={busy || action.disabled || refusal !== null || action.kind === null}
                    onClick={() => action.kind && void start(action.kind, row.id, me.csrf_token)}
                  >
                    {action.label}
                  </button>
                </section>
              )
            })}
          </div>
          {refusal && <p className="xc-note">{refusal}</p>}
        </>
      )}
    </Page>
  )
}
