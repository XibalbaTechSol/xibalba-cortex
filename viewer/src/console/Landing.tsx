// The public landing page: the first thing an unauthenticated visitor sees.
//
// Cortex had one of these until the legacy viewer was archived, and it went with it -- the
// console then opened straight onto sign-in, which tells a first-time visitor nothing about
// what they are being asked to sign in to. This is that surface rebuilt on the Industry
// grammar the console already uses: same tokens, same frames, same registration marks, dark
// only. e2e/design-system.spec.ts sweeps this page as well as the signed-in console, so
// "same theme" is a measurement here, not an intention.
//
// Sourcing rule for everything stated below, because this page now makes commercial and
// comparative claims:
//
//   * Capability claims about Cortex come from this repository's spec, README and tool
//     surface, and name the tool that backs them.
//   * The comparison column for Supermemory comes only from its own published pricing page
//     (retrieved 2026-10-25, see COMPARISON_SOURCE). Anything that page does not describe is
//     "Not advertised" -- never "No". Where a competitor is ahead, the table says so; the
//     compliance row is the clearest case.
//   * Competitor prices are deliberately absent. They move, and a stale number here reads as
//     a misrepresentation.
//   * Tier contents separate what exists today from what does not: anything unbuilt carries
//     an explicit "Planned" marker rather than being implied.
//
// Two values are operator decisions, not facts from the repo, and are flagged as such:
// CONTACT_EMAIL and the Pilot tier's price.

import { useState } from 'react'
import { CONTACT_EMAIL, contactFields, contactMailto } from './contact'
import { IconCheck, IconGraph, IconIntegrity, IconLock, IconSearch, IconTimeline } from './icons'

const REPO = 'https://github.com/XibalbaTechSol/xibalba-cortex'
const WIKI = `${REPO}/wiki`
const BLOB = `${REPO}/blob/main`

// CONTACT_EMAIL lives in ./contact alongside the draft composition. OPERATOR DECISION: no
// public contact address appears anywhere in this repo or its siblings, so this one was chosen,
// not found. xibalba.dev is registered (OVH nameservers) and does carry Proton MX records, so
// the domain can receive mail -- but whether the `contact` mailbox itself is provisioned was
// not verified from here. Confirm it accepts mail before this page goes public.

/** What the store guarantees. One window each, in the order a reader meets them. */
const PRIMITIVES = [
  {
    icon: <IconIntegrity />,
    title: 'A verifiable history',
    body: 'Every write is an append-only event linked to the one before it, and Merkle roots are computed per domain. A caller can verify a subset of the graph without replaying the whole chain.',
    tool: 'memory_verify_chain',
  },
  {
    icon: <IconSearch />,
    title: 'Four signals, one ranking',
    body: 'Retrieval fuses lexical, vector, graph and temporal signals by Reciprocal Rank Fusion rather than betting on any one of them — and will tell you which signal surfaced a given result.',
    tool: 'memory_hybrid_retrieve',
  },
  {
    icon: <IconCheck />,
    title: 'Extraction proposes; it never writes',
    body: 'Entity and relationship extraction produces proposals that need an explicit decision before they reach the graph. Accepted proposals pass through the review lifecycle before entering the store.',
    tool: 'memory_claim_inference_task',
  },
] as const

/** How it runs, stated plainly enough that a reader can check it against the repo. */
const FACTS = [
  ['Runs', 'On your machine. SQLite under ~/.hermes/xibalba-cortex.'],
  ['Speaks', 'MCP, over stdio or streamable-HTTP.'],
  ['Bridges', 'Claude Code, Codex and agy, through one shared contract.'],
] as const

const COMPARISON_SOURCE = 'supermemory.ai/pricing, retrieved 2026-10-25'

/** Capability axes, not prices. `them` is strictly what Supermemory's own page states. */
const COMPARISON = [
  {
    axis: 'Where the data lives',
    us: 'Your machine. SQLite under ~/.hermes/xibalba-cortex, local-only by default.',
    them: 'Managed cloud. A self-hosted option appears on the Scale tier and above.',
  },
  {
    axis: 'Write integrity',
    us: 'Append-only events, each hash-linked to the one before it, with domain-separated Merkle roots a caller can check independently.',
    them: 'Not advertised.',
  },
  {
    axis: 'Why a result surfaced',
    us: 'The fusion of lexical, vector, graph and temporal signals is persisted as a re-readable trace naming the signals that contributed.',
    them: 'A search and memory API. Per-signal attribution is not advertised.',
  },
  {
    axis: 'Extraction safety gate',
    us: 'Extraction emits proposals only. Nothing enters the graph without an explicit review decision.',
    them: 'Not advertised.',
  },
  {
    axis: 'Compliance attestations',
    us: 'None. No SOC 2 report and no HIPAA BAA — the integrity primitives are mechanical, not audited.',
    them: 'SOC 2 and a HIPAA BAA on the Scale tier, GDPR terms at Enterprise.',
  },
  {
    axis: 'Harness integration',
    us: 'MCP over stdio or streamable-HTTP. Claude Code, Codex and agy ride one shared bridge contract.',
    them: 'Plugins for Claude Code, Cursor, Hermes and others.',
  },
  {
    axis: 'Third-party connectors',
    us: 'None. Ingestion is through MCP tools and the local API.',
    them: 'A Gmail connector, and S3 and web-crawler connectors, gated by tier.',
  },
  {
    axis: 'Metering',
    us: 'None. It runs on your hardware, so there is no per-call balance to draw down.',
    them: 'Usage-based: every store, search and index call draws from a monthly dollar balance.',
  },
] as const

/** Three tiers. "Planned" is load-bearing: it marks what is not built yet. */
const TIERS = [
  {
    name: 'Local',
    price: '$0',
    cadence: 'self-hosted, always',
    pitch: 'The whole store, on your hardware, with no account and no metering.',
    items: [
      'The full MCP tool surface — 81 tools today — over stdio or streamable-HTTP',
      'Hash-chained events and domain-separated Merkle roots',
      'Hybrid retrieval with persisted, re-readable traces',
      'Proposal-only extraction with the full review lifecycle',
      'The graph and timeline console you are looking at',
    ],
    cta: { label: 'Read the source', href: REPO },
    featured: false,
    note: null,
  },
  {
    name: 'Pilot',
    // OPERATOR DECISION -- indicative, not a quoted price. Nothing is billable today.
    price: '$500',
    cadence: 'per month, indicative',
    pitch: 'A supported deployment for one team, with the people who built it on the other end.',
    items: [
      'Everything in Local',
      'Supported installation, upgrade and migration path',
      'Operator-provisioned access tokens for a team',
      'Redaction and retention policy reviewed against your data',
      'Planned: session-root anchoring beyond the Base Sepolia testnet',
      'Planned: hosted control plane with federated identity',
    ],
    cta: { label: 'Start a pilot', href: '#contact' },
    featured: true,
    note: 'Indicative while the hosted control plane is in development.',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    cadence: 'scoped per deployment',
    pitch: 'Air-gapped, regulated or multi-tenant estates, scoped against your controls.',
    items: [
      'Everything in Pilot',
      'Air-gapped and offline installation support',
      'Custom retention tiers and redaction policy',
      'Deployment and threat-model review with our engineers',
      'Planned: SSO, tenant-bound membership and scoped sessions',
      'Planned: uptime SLA and compliance attestations',
    ],
    cta: { label: 'Talk to us', href: '#contact' },
    featured: false,
    note: null,
  },
] as const

/** Documentation. Every URL below was checked to resolve to a real page, not a wiki stub. */
const DOCS = [
  { title: 'The normative spec', body: 'xibalba-cortex v1 — the highest authority in the repository. Store schema, hash-chain format and the MCP core tool contract.', href: `${BLOB}/spec/xibalba-cortex-v1.md` },
  { title: 'MCP tool surface', body: 'Every tool the server exposes, with its arguments and what it guarantees.', href: `${WIKI}/mcp-tool-surface` },
  { title: 'Hash chain and Merkle roots', body: 'How events are linked, how roots are domain-separated, and what a verification actually proves.', href: `${WIKI}/hash-chain-and-merkle-roots` },
  { title: 'Hybrid extraction and retrieval', body: 'Reciprocal Rank Fusion across four signals, and the proposal lifecycle extraction runs through.', href: `${WIKI}/hybrid-extraction-and-retrieval` },
  { title: 'Store schema overview', body: 'The SQLite tables behind the graph: memories, entities, sessions, events and roots.', href: `${WIKI}/store-schema-overview` },
  { title: 'Viewer and local API', body: 'The localhost HTTP API this console reads, and how to point your own surface at it.', href: `${WIKI}/viewer-and-local-api` },
  { title: 'Ecosystem role', body: 'Where Cortex sits next to Xibalba Shield and the Integrity Protocol, and what it is deliberately not.', href: `${WIKI}/ecosystem-role` },
  { title: 'Full wiki index', body: 'Every published page, grouped by concept, architecture and query.', href: `${WIKI}/WIKI_INDEX` },
] as const

/** A contact form with no server behind it: it composes a mail draft the visitor sends. */
function ContactForm() {
  const [sent, setSent] = useState(false)

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    window.location.href = contactMailto(contactFields(new FormData(e.currentTarget)))
    setSent(true)
  }

  return (
    <form className="xc-landing-form" onSubmit={onSubmit} noValidate={false}>
      <div className="xc-landing-form-row">
        <label className="xc-field" htmlFor="xc-contact-name">
          Name
          <input className="xc-input" id="xc-contact-name" name="name" type="text" required autoComplete="name" />
        </label>
        <label className="xc-field" htmlFor="xc-contact-email">
          Email
          <input className="xc-input" id="xc-contact-email" name="email" type="email" required autoComplete="email" />
        </label>
      </div>
      <div className="xc-landing-form-row">
        <label className="xc-field" htmlFor="xc-contact-org">
          <span className="xc-landing-label">Organisation <span className="xc-landing-optional">optional</span></span>
          <input className="xc-input" id="xc-contact-org" name="org" type="text" autoComplete="organization" />
        </label>
        <label className="xc-field" htmlFor="xc-contact-topic">
          Interest
          <select className="xc-input" id="xc-contact-topic" name="topic" defaultValue="Pilot">
            <option value="Pilot">Starting a pilot</option>
            <option value="Enterprise">Enterprise deployment</option>
            <option value="Self-hosting">Self-hosting help</option>
            <option value="Other">Something else</option>
          </select>
        </label>
      </div>
      <label className="xc-field" htmlFor="xc-contact-message">
        What are you trying to build?
        <textarea className="xc-input xc-landing-textarea" id="xc-contact-message" name="message" rows={5} required />
      </label>
      <div className="xc-landing-form-foot">
        <button type="submit" className="xc-btn xc-btn--primary">Compose the message</button>
        <p className="xc-meta" role="status" aria-live="polite">
          {sent
            ? `Your mail client should have opened a draft to ${CONTACT_EMAIL}. If it did not, send it there directly.`
            : 'Opens a draft in your own mail client — nothing is submitted to a server from this page.'}
        </p>
      </div>
    </form>
  )
}

export function Landing({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="xc-landing">
      <header className="xc-landing-top">
        <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => { e.preventDefault(); document.querySelector('.xc-landing')?.scrollTo({ top: 0, behavior: 'auto' }) }}>
          <span className="xc-brand-mark"><img src="/cortex-rail-mark.png" alt="" /></span>
          <b>Xibalba Cortex</b>
        </a>
        <nav className="xc-landing-nav" aria-label="Sections">
          <a className="xc-link" href="#what">What it is</a>
          <a className="xc-link" href="#how">How it runs</a>
          <a className="xc-link" href="#compare">Compare</a>
          <a className="xc-link" href="#pricing">Pricing</a>
          <a className="xc-link" href="#docs">Docs</a>
          <a className="xc-link" href="#contact">Contact</a>
        </nav>
        <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>Sign in</button>
      </header>

      <main>
      <section className="xc-landing-hero" aria-labelledby="xc-hero-title">
        {/* The mark leads. It carries its own hero derivative rather than the rail's, which is
            built for 124px -- see viewer/scripts/invert_logo_to_white.py. */}
        <img className="xc-landing-mark" src="/cortex-lockup-hero.png" width={420} height={390} alt="" />
        <div className="xc-landing-hero-body">
          <p className="xc-eyebrow">{managed ? 'Managed memory for agents' : 'Graph memory for agents'}</p>
          <h1 id="xc-hero-title">Your agents’ memory.<br />Provably yours.</h1>
          <p className="xc-landing-lead">
            {managed ? 'An isolated workspace for recording agent memories, searching them through an authenticated API, and retaining a verifiable event history.' : <>A local-first memory server that records what your agents learned, where it came from, and whether it still holds — as a graph you can walk and a chain you can verify.</>}
          </p>
          <div className="xc-landing-cta">
            <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>{managed ? 'Open your workspace' : 'Open the console'}</button>
            <a className="xc-btn" href={REPO} target="_blank" rel="noreferrer noopener">Read the source</a>
          </div>
        </div>
      </section>

      <section className="xc-landing-section" id="what" aria-labelledby="xc-what-title">
        <p className="xc-eyebrow">What it is</p>
        <h2 className="xc-landing-h2" id="xc-what-title">Memory with a verifiable foundation</h2>
        <div className="xc-landing-grid">
          {primitives.map((p) => (
            <article className="xc-win xc-landing-card" key={p.title}>
              <div className="xc-landing-card-icon" aria-hidden="true">{p.icon}</div>
              <h3 className="xc-title xc-title--sm">{p.title}</h3>
              <p className="xc-copy">{p.body}</p>
              <p className="xc-meta">{p.tool}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="xc-landing-section" id="how" aria-labelledby="xc-how-title">
        <p className="xc-eyebrow">How it runs</p>
        <h2 className="xc-landing-h2" id="xc-how-title">{managed ? 'Hosted memory, clear boundaries' : 'Local first, and legible'}</h2>
        <div className="xc-landing-split">
          <dl className="xc-landing-facts">
            {facts.map(([term, detail]) => (
              <div key={term}>
                <dt className="xc-meta">{term}</dt>
                <dd className="xc-copy">{detail}</dd>
              </div>
            ))}
          </dl>
          <article className="xc-win xc-landing-card">
            <div className="xc-landing-card-icon" aria-hidden="true"><IconGraph /></div>
            <h3 className="xc-title xc-title--sm">{managed ? 'A workspace for your agents' : 'Explore the memory graph'}</h3>
            <p className="xc-copy">
              {managed ? 'Record and retrieve memories, monitor your usage, connect agents with revocable API keys, and manage your subscription. Existing memories remain available to read and export if a subscription becomes read-only.' : <>The same store, read two ways: a force-directed graph of memories, entities, sessions and Merkle roots, and a timeline that places them on a real time axis. Select either and the detail dock shows the chain, the provenance and the inference behind it.</>}
            </p>
            <p className="xc-landing-icons" aria-hidden="true"><IconGraph /><IconTimeline /><IconLock /></p>
          </article>
        </div>
      </section>

      <section className="xc-landing-section" id="compare" aria-labelledby="xc-compare-title">
        <p className="xc-eyebrow">Compare</p>
        <h2 className="xc-landing-h2" id="xc-compare-title">Against a hosted memory API</h2>
        <p className="xc-landing-lead">
          Most agent memory products store embeddings and serve similarity. Cortex stores evidence and
          serves a chain you can check. Supermemory is the clearest hosted contrast — and it is ahead
          of us on connectors and on compliance paperwork, which is why both rows are here.
        </p>

        {/* The table scrolls inside its own frame rather than widening the page: the landing
            spec measures .xc-landing for horizontal overflow down to 320px. On a narrow screen
            the third column starts off-frame, so the scroll has to be announced -- an
            affordance nobody can see is the same as no affordance. */}
        <p className="xc-meta xc-landing-scrollhint">Scroll the table sideways to compare both columns.</p>
        <div className="xc-landing-tablewrap" tabIndex={0} role="group" aria-labelledby="xc-compare-title">
          <table className="xc-landing-table">
            <caption className="xc-meta">Capability comparison. Prices are deliberately omitted — see the tiers below for ours.</caption>
            <thead>
              <tr>
                <th scope="col">Capability</th>
                <th scope="col">Xibalba Cortex</th>
                <th scope="col">Supermemory</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.axis}>
                  <th scope="row">{row.axis}</th>
                  <td>{row.us}</td>
                  <td>{row.them}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="xc-meta xc-landing-footnote">
          Cortex column from this repository’s spec, README and tool surface. Supermemory column from{' '}
          <a className="xc-link" href="https://supermemory.ai/pricing" target="_blank" rel="noreferrer noopener">{COMPARISON_SOURCE}</a>;
          a capability that page does not describe is marked “Not advertised”, which is not a claim that it is absent.
        </p>
      </section>

      <section className="xc-landing-section" id="pricing" aria-labelledby="xc-pricing-title">
        <p className="xc-eyebrow">Pricing</p>
        <h2 className="xc-landing-h2" id="xc-pricing-title">Three ways to run it</h2>
        <p className="xc-landing-lead">
          The store itself is free and self-hosted, and it stays that way. What you can pay us for is
          support, policy review and the operational work of running it somewhere regulated.
        </p>
        <div className="xc-landing-tiers">
          {TIERS.map((t) => (
            <article
              className={`xc-win xc-landing-tier${t.featured ? ' xc-landing-tier--featured' : ''}`}
              key={t.name}
              aria-labelledby={`xc-tier-${t.name}`}
            >
              {t.featured ? <p className="xc-landing-tier-flag">Recommended</p> : null}
              <h3 className="xc-title xc-title--sm" id={`xc-tier-${t.name}`}>{t.name}</h3>
              <p className="xc-landing-tier-price">
                <b>{t.price}</b>
                <span className="xc-meta">{t.cadence}</span>
              </p>
              <p className="xc-copy">{t.pitch}</p>
              <ul className="xc-landing-tier-list">
                {t.items.map((item) => {
                  // A tick against a "Planned:" line would read as "included today", which is
                  // the one thing these lines exist to deny. They keep the indent, not the mark.
                  const planned = item.startsWith('Planned:')
                  return (
                    <li key={item} className={planned ? 'xc-landing-planned' : undefined}>
                      <span className="xc-landing-tick" aria-hidden="true">{planned ? null : <IconCheck />}</span>
                      <span>{item}</span>
                    </li>
                  )
                })}
              </ul>
              {t.note ? <p className="xc-meta xc-landing-tier-note">{t.note}</p> : null}
              <a
                className={`xc-btn${t.featured ? ' xc-btn--primary' : ''} xc-landing-tier-cta`}
                href={t.cta.href}
                {...(t.cta.href.startsWith('#') ? {} : { target: '_blank', rel: 'noreferrer noopener' })}
              >
                {t.cta.label}
              </a>
            </article>
          ))}
        </div>
        <p className="xc-meta xc-landing-footnote">
          Nothing on this page is billable yet: the Pilot figure is indicative while the hosted control
          plane is built, and items marked “Planned” are not available today.
        </p>
      </section>

      <section className="xc-landing-section" id="docs" aria-labelledby="xc-docs-title">
        <p className="xc-eyebrow">Documentation</p>
        <h2 className="xc-landing-h2" id="xc-docs-title">Read it before you trust it</h2>
        <p className="xc-landing-lead">
          The spec is the authority, not this page. Everything below is published alongside the source.
        </p>
        <div className="xc-landing-docs">
          {DOCS.map((d) => (
            <a className="xc-win xc-landing-doc" key={d.href} href={d.href} target="_blank" rel="noreferrer noopener">
              <h3 className="xc-title xc-title--sm">{d.title}</h3>
              <p className="xc-copy">{d.body}</p>
            </a>
          ))}
        </div>
      </section>

      <section className="xc-landing-section" id="contact" aria-labelledby="xc-contact-title">
        <p className="xc-eyebrow">Contact</p>
        <h2 className="xc-landing-h2" id="xc-contact-title">Tell us what you are building</h2>
        <div className="xc-landing-split">
          <div className="xc-landing-contact-aside">
            <p className="xc-copy">
              If you are putting an agent somewhere that has to answer “why did it believe that?” months
              later, we want to hear the shape of it. Pilots are scoped by hand, deliberately.
            </p>
            <dl className="xc-landing-facts">
              <div>
                <dt className="xc-meta">Email</dt>
                <dd className="xc-copy"><a className="xc-link" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></dd>
              </div>
              <div>
                <dt className="xc-meta">Issues</dt>
                <dd className="xc-copy"><a className="xc-link" href={`${REPO}/issues`} target="_blank" rel="noreferrer noopener">Open one on GitHub</a></dd>
              </div>
              <div>
                <dt className="xc-meta">From</dt>
                <dd className="xc-copy">Xibalba Solutions LLC</dd>
              </div>
            </dl>
          </div>
          <ContactForm />
        </div>
      </section>

      </main>
      {/* Labelled with aria-label rather than a visually-hidden heading: a 1px clipped
          element still reads as rendered text to the conformance sweep, which then reports it
          as clipped and off the type scale -- correctly, for an element that should not be
          carrying type at all. */}
      <footer className="xc-landing-foot" aria-label="Site footer">
        <div className="xc-landing-foot-cols">
          <div className="xc-landing-foot-brand">
            <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => { e.preventDefault(); document.querySelector('.xc-landing')?.scrollTo({ top: 0, behavior: 'auto' }) }}>
              <span className="xc-brand-mark"><img src="/cortex-rail-mark.png" alt="" /></span>
              <b>Xibalba Cortex</b>
            </a>
            <p className="xc-copy">
              Provenance-aware graph memory for agent harnesses. Local-first, MCP-native, verifiable.
            </p>
          </div>

          <nav className="xc-landing-foot-col" aria-labelledby="xc-foot-product">
            <p className="xc-meta" id="xc-foot-product">Product</p>
            <a className="xc-link" href="#what">What it is</a>
            <a className="xc-link" href="#how">How it runs</a>
            <a className="xc-link" href="#compare">Comparison</a>
            <a className="xc-link" href="#pricing">Pricing</a>
          </nav>

          <nav className="xc-landing-foot-col" aria-labelledby="xc-foot-docs">
            <p className="xc-meta" id="xc-foot-docs">Documentation</p>
            <a className="xc-link" href={`${BLOB}/spec/xibalba-cortex-v1.md`} target="_blank" rel="noreferrer noopener">The spec</a>
            <a className="xc-link" href={`${WIKI}/mcp-tool-surface`} target="_blank" rel="noreferrer noopener">Tool surface</a>
            <a className="xc-link" href={`${WIKI}/hash-chain-and-merkle-roots`} target="_blank" rel="noreferrer noopener">Hash chain</a>
            <a className="xc-link" href={`${WIKI}/WIKI_INDEX`} target="_blank" rel="noreferrer noopener">Wiki index</a>
          </nav>

          <nav className="xc-landing-foot-col" aria-labelledby="xc-foot-project">
            <p className="xc-meta" id="xc-foot-project">Project</p>
            <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">Source</a>
            <a className="xc-link" href={`${BLOB}/README.md`} target="_blank" rel="noreferrer noopener">README</a>
            <a className="xc-link" href={`${REPO}/issues`} target="_blank" rel="noreferrer noopener">Issues</a>
            <a className="xc-link" href={`${WIKI}/ecosystem-role`} target="_blank" rel="noreferrer noopener">Ecosystem</a>
          </nav>

          <nav className="xc-landing-foot-col" aria-labelledby="xc-foot-contact">
            <p className="xc-meta" id="xc-foot-contact">Contact</p>
            <a className="xc-link" href="#contact">Start a pilot</a>
            <a className="xc-link" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          </nav>
        </div>

        <div className="xc-landing-foot-base">
          <span className="xc-meta">© 2026 Xibalba Solutions LLC · Graph memory for agents</span>
          <span className="xc-spacer" />
          <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">github.com/XibalbaTechSol/xibalba-cortex</a>
        </div>
      </footer>
    </div>
  )
}
