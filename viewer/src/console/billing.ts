// Pure helpers for the Billing page: how a plan is worded, which plan control is offered, and
// whether a payment redirect is trusted. The hosted edition's `/api/managed/plans` route returns
// these plans; api.ts has no type for them, so the shape is declared here.

export interface Plan {
  id: string
  name: string
  monthly_cents: number
  max_memories: number
  writes_per_month: number
  retrievals_per_month: number
}

export interface PlanRow {
  id: string
  name: string
  price: string
  current: boolean
  limits: Array<{ label: string; value: string }>
}

export const BILLING_UNAVAILABLE = 'Paid subscriptions are not available yet.'

export interface StatusMeta {
  label: string
  tone: 'active' | 'review' | 'conflict' | 'muted'
}

export function statusMeta(status: string | undefined): StatusMeta {
  switch (status) {
    case 'active':
      return { label: 'Active', tone: 'active' }
    case 'free':
      return { label: 'Free Tier', tone: 'muted' }
    case 'trialing':
      return { label: 'In Trial', tone: 'active' }
    case 'past_due':
      return { label: 'Past Due', tone: 'review' }
    case 'canceled':
      return { label: 'Canceled', tone: 'conflict' }
    case 'unpaid':
      return { label: 'Unpaid', tone: 'conflict' }
    default:
      return { label: status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown', tone: 'muted' }
  }
}

/** Consumes the ?billing= query or hash parameter after Stripe redirect, cleaning the URL. */
export function consumeBillingReturn(
  href?: string,
  replaceState?: (url: string) => void
): 'success' | 'canceled' | null {
  const currentHref = href ?? (typeof window !== 'undefined' ? window.location.href : null)
  if (!currentHref) return null
  try {
    const url = new URL(currentHref)
    let val = url.searchParams.get('billing')
    if (val === 'success' || val === 'canceled') {
      url.searchParams.delete('billing')
      const target = url.pathname + (url.search ? url.search : '') + url.hash
      if (replaceState) {
        replaceState(target)
      } else if (typeof window !== 'undefined') {
        window.history.replaceState({}, '', target)
      }
      return val
    }
    const hashIdx = currentHref.indexOf('#')
    if (hashIdx !== -1) {
      const hashPart = currentHref.slice(hashIdx)
      const qIdx = hashPart.indexOf('?')
      if (qIdx !== -1) {
        const hashParams = new URLSearchParams(hashPart.slice(qIdx + 1))
        val = hashParams.get('billing')
        if (val === 'success' || val === 'canceled') {
          const cleanHash = hashPart.slice(0, qIdx)
          const target = url.pathname + (url.search ? url.search : '') + cleanHash
          if (replaceState) {
            replaceState(target)
          } else if (typeof window !== 'undefined') {
            window.history.replaceState({}, '', target)
          }
          return val
        }
      }
    }
  } catch {
    return null
  }
  return null
}

/** The existing wording for a workspace whose subscription no longer permits writes. It was
 *  inline in BillingPage's callout; the data layer refuses a forbidden hosted write with this same
 *  sentence so the control and the explanation say one thing rather than two. (`BILLING_UNAVAILABLE`
 *  is about whether checkout is configured at all, which is a different refusal.) */
export const READ_ONLY_WORKSPACE = 'This workspace is read-only. Your existing memories remain available to read. Update billing to resume writes.'

export function planRows(plans: Plan[], currentPlanId: string): PlanRow[] {
  return plans.map((p) => ({
    id: p.id,
    name: p.name,
    price: `$${p.monthly_cents / 100} / month`,
    current: p.id === currentPlanId,
    limits: [
      { label: 'Stored memories', value: p.max_memories.toLocaleString('en-US') },
      { label: 'Write requests / month', value: p.writes_per_month.toLocaleString('en-US') },
      { label: 'Retrieval requests / month', value: p.retrievals_per_month.toLocaleString('en-US') },
    ],
  }))
}

/** The reason an upgrade control is unavailable, or null when it is available. */
export function upgradeRefusal(billingConfigured: boolean, _planId: string): string | null {
  return billingConfigured ? null : BILLING_UNAVAILABLE
}

export interface PlanAction {
  label: string
  /** checkout starts a new subscription; portal changes an existing one */
  kind: 'checkout' | 'portal' | null
  disabled: boolean
}

/** What a plan card offers a signed-in workspace. Only a free workspace can start checkout. */
export function planAction(currentPlanId: string, plan: { id: string; name: string }): PlanAction {
  if (plan.id === currentPlanId) return { label: 'Current plan', kind: null, disabled: true }
  if (plan.id === 'free') return { label: 'Manage through billing', kind: 'portal', disabled: true }
  if (currentPlanId === 'free') return { label: `Choose ${plan.name}`, kind: 'checkout', disabled: false }
  return { label: 'Change through billing', kind: 'portal', disabled: false }
}

const PAYMENT_HOSTS = ['checkout.stripe.com', 'billing.stripe.com']

/** The URL to send the browser to, or a throw: a payment redirect is only followed to Stripe over https. */
export function paymentDestination(url: string): string {
  const invalid = new Error('The payment service returned an invalid destination')
  let parsed: URL
  try { parsed = new URL(url) } catch { throw invalid }
  if (parsed.protocol !== 'https:' || !PAYMENT_HOSTS.includes(parsed.hostname)) throw invalid
  return parsed.href
}

export interface Usage { month: string; used: Record<string, number> }

export interface UsageRow {
  label: string
  value: string
  used: number
  limit: number
  percent: number
  nearLimit: boolean
  atLimit: boolean
}

/** Used / allowed for the month with percentages and threshold indicators. */
export function usageRows(plan: Plan, usage: Usage, memoryCount: number): UsageRow[] {
  const n = (v: number) => v.toLocaleString('en-US')
  const metrics = [
    { label: 'Stored memories', used: memoryCount, limit: plan.max_memories },
    { label: 'Write requests', used: usage.used.writes ?? 0, limit: plan.writes_per_month },
    { label: 'Retrieval requests', used: usage.used.retrievals ?? 0, limit: plan.retrievals_per_month },
  ]
  return metrics.map(({ label, used, limit }) => {
    const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
    return {
      label,
      value: `${n(used)} / ${n(limit)}`,
      used,
      limit,
      percent,
      nearLimit: percent >= 80 && percent < 100,
      atLimit: percent >= 100,
    }
  })
}

/** Format a unix timestamp in seconds to a human-readable date, e.g. "Nov 14, 2026". */
export function formatPeriodDate(timestampSeconds: number | null | undefined): string | null {
  if (!timestampSeconds || typeof timestampSeconds !== 'number' || isNaN(timestampSeconds) || timestampSeconds <= 0) {
    return null
  }
  const date = new Date(timestampSeconds * 1000)
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date)
}

/** Builds the descriptive status note for a subscription. */
export function subscriptionStatusText(entitlement: {
  plan: { id: string; name: string }
  status: string
  cancel_at_period_end?: boolean
  period_end?: number | null
}): string {
  const parts = [`Plan: ${entitlement.plan.name}`, `status: ${entitlement.status}`]
  const date = formatPeriodDate(entitlement.period_end)
  if (entitlement.plan.id === 'free') {
    return parts.join(' · ')
  }
  if (entitlement.cancel_at_period_end) {
    parts.push(date ? `cancels at end of period on ${date}` : 'cancels at the end of the paid period')
  } else if (date) {
    parts.push(`renews on ${date}`)
  }
  return parts.join(' · ')
}
