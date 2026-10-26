import { useState, type FormEvent } from 'react'

const REPO = 'https://github.com/XibalbaTechSol/xibalba-cortex'
const DOCS = `${REPO}/blob/main`
export const CONTACT_EMAIL = 'jacob.v.universe@gmail.com'
const plans = [
  { name: 'Free', price: 0, purpose: 'Explore a dedicated memory workspace.', memories: '1,000', writes: '250', reads: '1,000' },
  { name: 'Pro', price: 29, purpose: 'Connect agents to a larger working memory.', memories: '25,000', writes: '5,000', reads: '25,000' },
  { name: 'Team', price: 149, purpose: 'More capacity for demanding agent workloads.', memories: '250,000', writes: '50,000', reads: '250,000' },
]
const comparisons = [
  ['Primary focus', 'Source tracking, verifiable memory history, and an inspectable graph.', 'Managed memory that extracts facts, updates user profiles, and retrieves context.'],
  ['Retrieval', 'Local edition: lexical + vector retrieval. Managed preview: lexical search.', 'Hybrid semantic search, graph traversal, filtering, and reranking.'],
  ['Deployment', 'Run the local server yourself. Separate managed workspaces are in preview.', 'Cloud service, local runtime, and dedicated deployment options.'],
  ['Memory history', 'Recompute event-chain hashes and inspect the evidence behind a memory. A valid chain does not prove a claim is true.', 'A memory lifecycle that updates, extends, and forgets facts while preserving history.'],
  ['Subscription model', 'Free / $29 Pro / $149 Team, with explicit storage and monthly request limits. Paid signup is not live yet.', 'Free and paid plans use included credits with usage-based billing. Check current pricing for limits and rates.'],
]

export function ProductSections({ showPricing }: { showPricing: boolean }) {
  const [interest, setInterest] = useState('General inquiry')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null)

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (busy) return
    const form = e.currentTarget
    const data = new FormData(form)
    setBusy(true); setFeedback(null)
    try {
      const response = await fetch('/api/contact', {
        method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(20000),
        body: JSON.stringify({ name: data.get('name'), email: data.get('email'), organization: data.get('organization'),
          message: `Interest: ${interest}\n\n${data.get('message')}`, website: data.get('website') }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.error || 'Your message could not be delivered. Try again or email us directly.')
      setFeedback({ ok: true, text: body.message || 'Your inquiry has been sent.' }); form.reset()
    } catch (error) {
      setFeedback({ ok: false, text: error instanceof Error && error.name !== 'TimeoutError' ? error.message : 'Delivery timed out. Please try again or email us directly.' })
    } finally { setBusy(false) }
  }

  return <>
    {showPricing && <section className="xc-landing-section" id="pricing" aria-labelledby="pricing-title">
      <p className="xc-eyebrow">Managed Cortex · preview</p>
      <h2 className="xc-landing-h2" id="pricing-title">A clear plan for each stage</h2>
      <p className="xc-copy xc-product-intro">Start with a small workspace. Add capacity as your agents grow. All prices are USD, billed monthly when subscriptions become available.</p>
      <div className="xc-product-plans">
        {plans.map((plan) => <article className="xc-win xc-product-plan" key={plan.name} aria-label={`${plan.name} subscription`}>
          <p className="xc-eyebrow">{plan.name}</p>
          <h3 className="xc-product-price">${plan.price}<span> / month</span></h3>
          <p className="xc-copy">{plan.purpose}</p>
          <dl><div><dt>Stored memories</dt><dd>{plan.memories}</dd></div><div><dt>Writes / month</dt><dd>{plan.writes}</dd></div><div><dt>Retrievals / month</dt><dd>{plan.reads}</dd></div></dl>
          <p className="xc-note">Isolated storage · API keys · lexical retrieval · chain verification · export</p>
          <a className={`xc-btn${plan.name === 'Pro' ? ' xc-btn--primary' : ''}`} href="#contact" onClick={() => setInterest(`${plan.name} plan`)}>Request {plan.name} access</a>
        </article>)}
      </div>
      <p className="xc-note xc-product-intro">Managed subscriptions are in preview; paid checkout is not live. Hosted inference and shared user seats are not included. Team provides higher capacity in one owner workspace. Monthly request limits reset in UTC.</p>
      <a className="xc-link" href={`${DOCS}/docs/operations/managed-memory-service.md`} target="_blank" rel="noreferrer noopener">Read the managed service guide ↗</a>
    </section>}

    <section className="xc-landing-section" id="compare" aria-labelledby="compare-title">
      <p className="xc-eyebrow">Choose for your workload</p>
      <h2 className="xc-landing-h2" id="compare-title">Cortex and Supermemory</h2>
      <p className="xc-copy xc-product-intro">Cortex emphasizes memory you can inspect and verify. Supermemory offers a broader managed memory and retrieval platform. Choose by deployment needs, retrieval features, and how you want to audit an agent’s memory.</p>
      <table className="xc-product-compare">
        <caption className="xc-note">Feature comparison, reviewed October 25, 2026. This is a product comparison, not a performance benchmark.</caption>
        <thead><tr><th scope="col">Area</th><th scope="col">Xibalba Cortex</th><th scope="col">Supermemory</th></tr></thead>
        <tbody>{comparisons.map(([area, cortex, supermemory]) => <tr key={area}><th scope="row">{area}</th><td data-label="Cortex">{cortex}</td><td data-label="Supermemory">{supermemory}</td></tr>)}</tbody>
      </table>
      <p className="xc-note xc-product-sources">Sources: <a className="xc-link" href={`${REPO}/blob/main/README.md`} target="_blank" rel="noreferrer noopener">Cortex documentation</a> · <a className="xc-link" href="https://supermemory.ai/product/" target="_blank" rel="noreferrer noopener">Supermemory product</a> · <a className="xc-link" href="https://supermemory.ai/pricing/" target="_blank" rel="noreferrer noopener">Supermemory pricing</a>. Features and prices may change.</p>
    </section>

    <section className="xc-landing-section" id="docs" aria-labelledby="docs-title">
      <p className="xc-eyebrow">Build with Cortex</p>
      <h2 className="xc-landing-h2" id="docs-title">Documentation that gets you moving</h2>
      <div className="xc-landing-grid">
        {[
          ['Start locally', 'Install Cortex, connect an agent, and inspect your first memories.', `${REPO}#readme`],
          ['Connect your tools', 'Set up the Cindy plugin and supported agent integrations.', `${DOCS}/docs/operations/cortex-plugin-distribution.md`],
          ['Managed service', 'Understand plans, workspace limits, API keys, and deployment setup.', `${DOCS}/docs/operations/managed-memory-service.md`],
        ].map(([title, copy, href]) => <article className="xc-win xc-landing-card" key={title}><h3 className="xc-title xc-title--sm">{title}</h3><p className="xc-copy">{copy}</p><a className="xc-link" href={href} target="_blank" rel="noreferrer noopener">Read the guide ↗</a></article>)}
      </div>
    </section>

    <section className="xc-landing-section xc-product-contact" id="contact" aria-labelledby="contact-title">
      <div><p className="xc-eyebrow">Talk to Xibalba Solutions</p><h2 className="xc-landing-h2" id="contact-title">Put memory to work.</h2><p className="xc-copy">Tell us what you’re building. We can discuss local setup, managed access, or moving an existing agent workflow to Cortex.</p><a className="xc-link" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a><p className="xc-note">Your contact details are used to reply to this inquiry. Please keep passwords, API keys, and sensitive records out of your message.</p></div>
      <form className="xc-win xc-product-contact-form" onSubmit={submit} aria-label="Contact Cortex">
        <div className="xc-product-fields"><label className="xc-field">Name<input className="xc-input" name="name" autoComplete="name" required maxLength={120} /></label><label className="xc-field">Email<input className="xc-input" name="email" type="email" autoComplete="email" required maxLength={254} /></label></div>
        <label className="xc-field">Organization <span className="xc-note">(optional)</span><input className="xc-input" name="organization" autoComplete="organization" maxLength={160} /></label>
        <label className="xc-field">Interested in<select className="xc-input" value={interest} onChange={(e) => setInterest(e.target.value)}>{['General inquiry', 'Free plan', 'Pro plan', 'Team plan', 'Local deployment', 'Migration'].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="xc-field">Message<textarea className="xc-input" name="message" required minLength={20} maxLength={4500} rows={5} /></label>
        <label className="xc-product-honey" aria-hidden="true">Website<input name="website" tabIndex={-1} autoComplete="off" /></label>
        <button className="xc-btn xc-btn--primary" type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send inquiry'}</button>
        {feedback && <p className={feedback.ok ? 'xc-note' : 'xc-callout'} role={feedback.ok ? 'status' : 'alert'}>{feedback.text}</p>}
      </form>
    </section>
  </>
}

export function ProductFooter() {
  return <footer className="xc-landing-foot xc-product-footer">
    <div className="xc-product-footer-grid"><div><p className="xc-eyebrow">Xibalba Cortex</p><p className="xc-copy">Memory with a verifiable foundation.</p><p className="xc-note">Built by Xibalba Solutions LLC.</p></div>
      <nav aria-label="Product links"><b>Product</b><a className="xc-link" href="#what">Features</a><a className="xc-link" href="#pricing">Plans</a><a className="xc-link" href="#compare">Compare</a></nav>
      <nav aria-label="Documentation links"><b>Developers</b><a className="xc-link" href="#docs">Documentation</a><a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">Source code</a><a className="xc-link" href={`${REPO}/issues`} target="_blank" rel="noreferrer noopener">Report an issue</a></nav>
      <nav aria-label="Company links"><b>Company</b><a className="xc-link" href="https://xibalbatechsol.github.io/" target="_blank" rel="noreferrer noopener">Xibalba Solutions</a><a className="xc-link" href="#contact">Contact</a><a className="xc-link" href={`mailto:${CONTACT_EMAIL}`}>Email us</a></nav></div>
    <div className="xc-product-footer-bottom"><span className="xc-note">© {new Date().getFullYear()} Xibalba Solutions LLC</span><span className="xc-note">Local control. Traceable memory.</span></div>
  </footer>
}
