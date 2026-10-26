// Shared public entry. Each edition describes only its implemented capabilities.

import type { ReactNode } from 'react'
import { IconCheck, IconGraph, IconIntegrity, IconLock, IconSearch, IconTimeline } from './icons'

const REPO = 'https://github.com/XibalbaTechSol/xibalba-cortex'

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

export function Landing({ onSignIn, children, managed = false }: { onSignIn: () => void; children?: ReactNode; managed?: boolean }) {
  const primitives = managed ? [
    PRIMITIVES[0],
    { icon: <IconSearch />, title: 'Search what your agents recorded', body: 'Find matching memories through bounded lexical search. Each request stays within the authenticated workspace and its monthly allowance.', tool: 'GET /api/managed/memories' },
    { icon: <IconLock />, title: 'An isolated workspace', body: 'Each customer has a separate memory store. Workspace-scoped API keys connect agents without granting access to billing or other customers’ memories.', tool: 'Workspace-scoped access' },
  ] : PRIMITIVES
  const facts = managed ? [
    ['Storage', 'A separate persistent memory store for each workspace.'],
    ['Access', 'An authenticated API and a managed web workspace.'],
    ['Billing', 'Monthly subscriptions, with payment details handled by Stripe.'],
  ] : FACTS
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
          <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">Source</a>
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

      {children}
      </main>
      <footer className="xc-landing-foot">
        <span className="xc-meta">Xibalba Cortex · Graph memory for agents</span>
        <span className="xc-spacer" />
        <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">github.com/XibalbaTechSol/xibalba-cortex</a>
      </footer>
    </div>
  )
}
