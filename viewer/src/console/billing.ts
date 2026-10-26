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

/** Used / allowed for the month, one row per limit the plan sets. */
export function usageRows(plan: Plan, usage: Usage, memoryCount: number): Array<{ label: string; value: string }> {
  const n = (v: number) => v.toLocaleString('en-US')
  return [
    { label: 'Stored memories', value: `${n(memoryCount)} / ${n(plan.max_memories)}` },
    { label: 'Write requests', value: `${n(usage.used.writes ?? 0)} / ${n(plan.writes_per_month)}` },
    { label: 'Retrieval requests', value: `${n(usage.used.retrievals ?? 0)} / ${n(plan.retrievals_per_month)}` },
  ]
}
