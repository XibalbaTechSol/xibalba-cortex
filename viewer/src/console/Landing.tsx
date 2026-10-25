// The public landing page: the first thing an unauthenticated visitor sees.
//
// Cortex had one of these until the legacy viewer was archived, and it went with it -- the
// console then opened straight onto sign-in, which tells a first-time visitor nothing about
// what they are being asked to sign in to. This is that surface rebuilt on the Industry
// grammar the console already uses: same tokens, same frames, same registration marks, dark
// only. It is held to the same conformance sweep (e2e/design-system.spec.ts) for exactly that
// reason -- "same theme" is a measurement here, not an intention.
//
// Everything stated below is drawn from the repo's own spec and README. No pricing, no hosted
// service and no adoption claims: none of those exist yet, and a landing page is the worst
// place to get ahead of what is actually built.

import { IconCheck, IconGraph, IconIntegrity, IconLock, IconSearch, IconTimeline } from './icons'

const REPO = 'https://github.com/XibalbaTechSol/xibalba-cortex'

/** What the store guarantees. One window each, in the order a reader meets them. */
const PRIMITIVES = [
  {
    icon: <IconIntegrity />,
    title: 'Hash-chained, not just stored',
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
    body: 'Entity and relationship extraction produces proposals that need an explicit decision before they reach the graph. The review gate is the design, not a setting you can turn off.',
    tool: 'memory_claim_inference_task',
  },
] as const

/** How it runs, stated plainly enough that a reader can check it against the repo. */
const FACTS = [
  ['Runs', 'On your machine. SQLite under ~/.hermes/xibalba-cortex.'],
  ['Speaks', 'MCP, over stdio or streamable-HTTP.'],
  ['Bridges', 'Claude Code, Codex and agy, through one shared contract.'],
  ['Licence', 'MIT.'],
] as const

export function Landing({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="xc-landing">
      <header className="xc-landing-top">
        <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => e.preventDefault()}>
          <span className="xc-brand-mark"><img src="/cortex-mark.png" alt="" /></span>
          <b>Xibalba Cortex</b>
        </a>
        <nav className="xc-landing-nav" aria-label="Sections">
          <a className="xc-link" href="#what">What it is</a>
          <a className="xc-link" href="#how">How it runs</a>
          <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">Source</a>
        </nav>
        <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>Sign in</button>
      </header>

      <section className="xc-landing-hero" aria-labelledby="xc-hero-title">
        {/* The mark leads. It carries its own hero derivative rather than the rail's, which is
            built for 124px -- see viewer/scripts/invert_logo_to_white.py. */}
        <img className="xc-landing-mark" src="/cortex-lockup-hero.png" width={420} height={390} alt="" />
        <div className="xc-landing-hero-body">
          <p className="xc-eyebrow">Graph memory for agents</p>
          <h1 id="xc-hero-title">Your agents’ memory.<br />Provably yours.</h1>
          <p className="xc-landing-lead">
            A local-first memory server that records what your agents learned, where it came from, and
            whether it still holds — as a graph you can walk and a chain you can verify.
          </p>
          <div className="xc-landing-cta">
            <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>Open the console</button>
            <a className="xc-btn" href={REPO} target="_blank" rel="noreferrer noopener">Read the source</a>
          </div>
        </div>
      </section>

      <section className="xc-landing-section" id="what" aria-labelledby="xc-what-title">
        <p className="xc-eyebrow">What it is</p>
        <h2 className="xc-landing-h2" id="xc-what-title">Three guarantees, not a vector store</h2>
        <div className="xc-landing-grid">
          {PRIMITIVES.map((p) => (
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
        <h2 className="xc-landing-h2" id="xc-how-title">Local first, and legible</h2>
        <div className="xc-landing-split">
          <dl className="xc-landing-facts">
            {FACTS.map(([term, detail]) => (
              <div key={term}>
                <dt className="xc-meta">{term}</dt>
                <dd className="xc-copy">{detail}</dd>
              </div>
            ))}
          </dl>
          <article className="xc-win xc-landing-card">
            <div className="xc-landing-card-icon" aria-hidden="true"><IconGraph /></div>
            <h3 className="xc-title xc-title--sm">A console, not a log file</h3>
            <p className="xc-copy">
              The same store, read two ways: a force-directed graph of memories, entities, sessions and
              Merkle roots, and a timeline that places them on a real time axis. Select either and the
              detail dock shows the chain, the provenance and the inference behind it.
            </p>
            <p className="xc-landing-icons" aria-hidden="true"><IconGraph /><IconTimeline /><IconLock /></p>
          </article>
        </div>
      </section>

      <footer className="xc-landing-foot">
        <span className="xc-meta">Xibalba Cortex · MIT licensed</span>
        <span className="xc-spacer" />
        <a className="xc-link" href={REPO} target="_blank" rel="noreferrer noopener">github.com/XibalbaTechSol/xibalba-cortex</a>
      </footer>
    </div>
  )
}
