import { describe, expect, it } from 'vitest'
import { planRows, upgradeRefusal, paymentDestination, planAction, usageRows } from './billing'

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
  it('accepts only https Stripe checkout and billing hosts', () => {
    expect(paymentDestination('https://checkout.stripe.com/c/pay/x')).toBe('https://checkout.stripe.com/c/pay/x')
    expect(paymentDestination('https://billing.stripe.com/p/session/y')).toBe('https://billing.stripe.com/p/session/y')
    expect(() => paymentDestination('http://checkout.stripe.com/x')).toThrow('The payment service returned an invalid destination')
    expect(() => paymentDestination('https://evil.example/x')).toThrow('The payment service returned an invalid destination')
    expect(() => paymentDestination('not a url')).toThrow('The payment service returned an invalid destination')
  })
})

describe('usageRows', () => {
  it('reads used over allowed, treating an absent counter as zero', () => {
    expect(usageRows(plans[1], { month: '2026-10', used: { writes: 1200 } }, 3)).toEqual([
      { label: 'Stored memories', value: '3 / 25,000' },
      { label: 'Write requests', value: '1,200 / 5,000' },
      { label: 'Retrieval requests', value: '0 / 25,000' },
    ])
  })
})
