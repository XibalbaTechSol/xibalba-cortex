import { describe, expect, it } from 'vitest'
import {
  consumeBillingReturn,
  formatPeriodDate,
  paymentDestination,
  planAction,
  planRows,
  statusMeta,
  subscriptionStatusText,
  upgradeRefusal,
  usageRows,
} from './billing'

const plans = [
  { id: 'free', name: 'Free', monthly_cents: 0, max_memories: 1000, writes_per_month: 250, retrievals_per_month: 1000 },
  { id: 'pro', name: 'Pro', monthly_cents: 2900, max_memories: 25000, writes_per_month: 5000, retrievals_per_month: 25000 },
]

describe('planRows', () => {
  it('carries a formatted price and marks the current plan', () => {
    const rows = planRows(plans, 'free')
    expect(rows.map((r) => r.price)).toEqual(['$0 / month', '$29 / month'])
    expect(rows.map((r) => r.current)).toEqual([true, false])
  })
  it('lists the three limits with thousands separators', () => {
    expect(planRows(plans, 'free')[1].limits).toEqual([
      { label: 'Stored memories', value: '25,000' },
      { label: 'Write requests / month', value: '5,000' },
      { label: 'Retrieval requests / month', value: '25,000' },
    ])
  })
})

describe('upgradeRefusal', () => {
  it('is refused with a reason when billing is unconfigured', () => {
    expect(upgradeRefusal(false, 'free')).toBe('Paid subscriptions are not available yet.')
    expect(upgradeRefusal(true, 'free')).toBeNull()
  })
})

describe('planAction', () => {
  const [free, pro] = plans
  it('only a free workspace can start checkout; paid ones go through the portal', () => {
    expect(planAction('free', pro)).toEqual({ label: 'Choose Pro', kind: 'checkout', disabled: false })
    expect(planAction('pro', pro)).toMatchObject({ label: 'Current plan', disabled: true })
    expect(planAction('pro', free)).toMatchObject({ label: 'Manage through billing', kind: 'portal', disabled: true })
    expect(planAction('pro', { id: 'team', name: 'Team' })).toMatchObject({ label: 'Change through billing', kind: 'portal', disabled: false })
    expect(planAction('free', free)).toMatchObject({ label: 'Current plan', disabled: true })
  })
})

describe('paymentDestination', () => {
  it('returns the normalised href, not the raw input', () => {
    expect(paymentDestination('https://CHECKOUT.stripe.com')).toBe('https://checkout.stripe.com/')
  })
  it('accepts only https Stripe checkout and billing hosts', () => {
    expect(paymentDestination('https://checkout.stripe.com/c/pay/x')).toBe('https://checkout.stripe.com/c/pay/x')
    expect(paymentDestination('https://billing.stripe.com/p/session/y')).toBe('https://billing.stripe.com/p/session/y')
    expect(() => paymentDestination('http://checkout.stripe.com/x')).toThrow('The payment service returned an invalid destination')
    expect(() => paymentDestination('https://evil.example/x')).toThrow('The payment service returned an invalid destination')
    expect(() => paymentDestination('https://checkout.stripe.com.evil.example/x')).toThrow('invalid destination')
    expect(() => paymentDestination('https://evil.example/checkout.stripe.com')).toThrow('invalid destination')
    expect(() => paymentDestination('https://evilstripe.com/x')).toThrow('invalid destination')
    expect(() => paymentDestination('https://stripe.com/x')).toThrow('invalid destination')
    expect(() => paymentDestination('https://evil.example/?stripe.com')).toThrow('invalid destination')
    expect(() => paymentDestination('not a url')).toThrow('The payment service returned an invalid destination')
  })
})

describe('usageRows', () => {
  it('reads zero for every counter on a fresh month, where used has no keys', () => {
    expect(usageRows(plans[1], { month: '2026-10', used: {} }, 0)).toEqual([
      { label: 'Stored memories', value: '0 / 25,000', used: 0, limit: 25000, percent: 0, nearLimit: false, atLimit: false },
      { label: 'Write requests', value: '0 / 5,000', used: 0, limit: 5000, percent: 0, nearLimit: false, atLimit: false },
      { label: 'Retrieval requests', value: '0 / 25,000', used: 0, limit: 25000, percent: 0, nearLimit: false, atLimit: false },
    ])
  })
  it('reads used over allowed, calculating percentage and threshold limits', () => {
    expect(usageRows(plans[1], { month: '2026-10', used: { writes: 1200 } }, 3)).toEqual([
      { label: 'Stored memories', value: '3 / 25,000', used: 3, limit: 25000, percent: 0, nearLimit: false, atLimit: false },
      { label: 'Write requests', value: '1,200 / 5,000', used: 1200, limit: 5000, percent: 24, nearLimit: false, atLimit: false },
      { label: 'Retrieval requests', value: '0 / 25,000', used: 0, limit: 25000, percent: 0, nearLimit: false, atLimit: false },
    ])
  })
  it('flags nearLimit when usage is >= 80% and < 100%', () => {
    const rows = usageRows(plans[1], { month: '2026-10', used: { writes: 4200 } }, 20000)
    expect(rows[0].nearLimit).toBe(true)
    expect(rows[0].atLimit).toBe(false)
    expect(rows[0].percent).toBe(80)
    expect(rows[1].nearLimit).toBe(true)
    expect(rows[1].percent).toBe(84)
  })
  it('flags atLimit and caps percent at 100% when usage is >= 100%', () => {
    const rows = usageRows(plans[1], { month: '2026-10', used: { writes: 6000 } }, 25000)
    expect(rows[0].atLimit).toBe(true)
    expect(rows[0].percent).toBe(100)
    expect(rows[1].atLimit).toBe(true)
    expect(rows[1].percent).toBe(100)
  })
})

describe('formatPeriodDate', () => {
  it('formats epoch seconds into UTC date strings', () => {
    expect(formatPeriodDate(1797206400)).toBe('Dec 14, 2026')
  })
  it('returns null for null, undefined, 0, or invalid timestamps', () => {
    expect(formatPeriodDate(null)).toBeNull()
    expect(formatPeriodDate(undefined)).toBeNull()
    expect(formatPeriodDate(0)).toBeNull()
    expect(formatPeriodDate(-100)).toBeNull()
    expect(formatPeriodDate(NaN)).toBeNull()
  })
})

describe('subscriptionStatusText', () => {
  it('formats free plan without renewal date', () => {
    expect(subscriptionStatusText({ plan: { id: 'free', name: 'Free' }, status: 'free' })).toBe('Plan: Free · status: free')
  })
  it('formats active paid plan with renewal date', () => {
    expect(subscriptionStatusText({
      plan: { id: 'pro', name: 'Pro' },
      status: 'active',
      period_end: 1797206400,
      cancel_at_period_end: false,
    })).toBe('Plan: Pro · status: active · renews on Dec 14, 2026')
  })
  it('formats canceling paid plan with cancellation notice', () => {
    expect(subscriptionStatusText({
      plan: { id: 'pro', name: 'Pro' },
      status: 'active',
      period_end: 1797206400,
      cancel_at_period_end: true,
    })).toBe('Plan: Pro · status: active · cancels at end of period on Dec 14, 2026')
  })
  it('formats paid plan when period_end is not available', () => {
    expect(subscriptionStatusText({
      plan: { id: 'pro', name: 'Pro' },
      status: 'active',
      cancel_at_period_end: false,
    })).toBe('Plan: Pro · status: active')
  })
})

describe('statusMeta', () => {
  it('maps plan statuses to human labels and design system tones', () => {
    expect(statusMeta('active')).toEqual({ label: 'Active', tone: 'active' })
    expect(statusMeta('free')).toEqual({ label: 'Free Tier', tone: 'muted' })
    expect(statusMeta('trialing')).toEqual({ label: 'In Trial', tone: 'active' })
    expect(statusMeta('past_due')).toEqual({ label: 'Past Due', tone: 'review' })
    expect(statusMeta('canceled')).toEqual({ label: 'Canceled', tone: 'conflict' })
    expect(statusMeta('unpaid')).toEqual({ label: 'Unpaid', tone: 'conflict' })
    expect(statusMeta('custom_status')).toEqual({ label: 'Custom_status', tone: 'muted' })
    expect(statusMeta(undefined)).toEqual({ label: 'Unknown', tone: 'muted' })
  })
})

describe('consumeBillingReturn', () => {
  it('extracts billing=success from URL and replaces window history', () => {
    let replaced = ''
    const val = consumeBillingReturn('http://localhost:5173/managed#billing?billing=success', (t) => {
      replaced = t
    })
    expect(val).toBe('success')
    expect(replaced).toBe('/managed#billing')
  })
  it('extracts billing=canceled from URL search params', () => {
    let replaced = ''
    const val = consumeBillingReturn('http://localhost:5173/managed?billing=canceled#billing', (t) => {
      replaced = t
    })
    expect(val).toBe('canceled')
    expect(replaced).toBe('/managed#billing')
  })
  it('returns null when no billing return param exists', () => {
    let replaced = ''
    const val = consumeBillingReturn('http://localhost:5173/managed#billing', (t) => {
      replaced = t
    })
    expect(val).toBeNull()
    expect(replaced).toBe('')
  })
})
