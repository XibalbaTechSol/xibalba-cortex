# Decision Memo — Does Integrity Protocol Need a Reasoning Engine?

**Written:** 2026-08-13
**Type:** Strategic decision memo, not an implementation plan. No code changes proposed here.
**Trigger:** Semantica competitive analysis (`docs/plans/2026-08-13-semantica-parity.md`).

## The question

Semantica's deepest technical capability is deterministic reasoning over recorded facts —
forward chaining, a Rete network, Datalog, and SPARQL, with "fully explainable paths, not black
boxes." Should Integrity Protocol build something comparable?

This is not a feature-parity question. It's a bet about what kind of explainability the buyer
actually needs, and building a rule engine well is a large, multi-month lift with real ongoing
maintenance cost (rule authoring, conflict resolution between rules, performance at scale). This
memo lays out the choice; it doesn't decide it.

## What Semantica's reasoning engine actually answers

Given a set of recorded facts, a Rete/Datalog engine can answer "why do you believe X" with a
derivation chain: X follows from facts A and B via rule R. This is explainability of *inference
over recorded knowledge* — it presupposes the facts are already trustworthy and answers "given
what we know, why this conclusion."

## What Integrity Protocol already answers, differently

Integrity Protocol's evidence chain answers a different question: not "why do you believe X" but
"how do we know this record wasn't altered, and who is accountable for it." AIS's
`entropy^wE · grounding^wG · sacrifice^wS · compliance^wC · ZK_boost` derivation is already fully
retrievable per-agent, per-period, component-by-component (`GET /v1/agent/{id}/ais` returns the
full breakdown, not just the aggregate — confirmed against `integrity-oracle/backend/src/
handlers.rs`), and every component is either independently server-recomputed from signed
telemetry or backed by a real ZK proof. The PROV-O export scoped in the parity plan adds
fact-to-source traceability on top of that. None of this is *rule-based inference* — but it's
arguably a stronger claim for a regulator: not "here's the logical derivation of our conclusion"
but "here's cryptographic proof this evidence is genuine and hasn't been altered since it was
recorded." Semantica cannot make that second claim at all — it has no cryptographic backing on
any of its provenance.

## The actual tradeoff

| | Rule-engine explainability (Semantica's bet) | Cryptographic evidence (Integrity Protocol's current bet) |
|---|---|---|
| Answers | "Why does this conclusion follow from these facts?" | "How do we know these facts/scores are genuine and unaltered?" |
| Trust model | Trusts the facts, explains the inference | Trusts nothing by default, proves the facts |
| Buyer-facing framing | Legible, familiar (rule engines are a known compliance-tooling pattern) | Less familiar, requires explaining crypto/on-chain concepts |
| Build cost | Large — rule authoring, conflict resolution, engine maintenance | Already substantially built |
| Applies to | Facts about the world the agent recorded | Facts about the agent's own behavior/evidence integrity |

The two aren't actually substitutes for the same claim — a reasoning engine explains conclusions
*given* trusted facts; Integrity Protocol's evidence chain establishes *whether the facts can be
trusted in the first place*. A sophisticated buyer evaluating both seriously would likely want
both eventually. The question this memo is actually posing is sequencing and whether "eventually"
is now.

## Options

1. **Don't build it. Lean into the cryptographic-evidence framing as the differentiator, not a
   gap to close.** Message it explicitly: "we don't just explain our reasoning, we prove our
   evidence." Risk: a buyer who's already anchored on Semantica's "explainable reasoning"
   framing may perceive the absence as a real gap regardless of the counter-argument, especially
   if a bake-off puts both products in the same room and only one has a rule-engine demo.

2. **Build a narrow rule layer scoped to compliance-control mapping**, not general-purpose
   reasoning. This is smaller than Semantica's engine and has a natural home:
   `integrity-core/docs/design/evidence-export.md`'s Phase B (`reason_code/intent_type →
   {framework, control_id, control_title}` control map) is already scoped as a static table for
   v1 — a small forward-chaining layer over that table (if event matches control X and agent's
   verification tier is Y, then compliance status is Z, with a stated derivation) would give a
   real, honest "here's the explainable rule that produced this compliance finding" without
   building a general Rete/Datalog engine. This directly answers a related open question too
   (see `integrity-core/docs/design/ontology-primitive-question.md`) — a control map plus a
   small rule layer over it is close to a minimal ontology already.

3. **Build the full thing eventually, not now.** Treat it as a real roadmap item once the
   cheaper parity work (PROV-O export, conflict detection, entity resolution) ships and there's
   evidence from actual sales conversations about whether the "explainable reasoning" gap is
   costing deals specifically, versus being a hypothetical concern.

## Recommendation

Option 3, with option 2 as a fallback if the compliance-control-mapping need becomes concrete
sooner (it's already partially scoped in evidence-export.md regardless of this decision). Option
1 alone is risky as a permanent position — the counter-argument is sound but requires the buyer
to sit through an explanation, and RFP checklists don't always allow for that. But building a
general reasoning engine now, before the cheaper and more directly load-bearing parity work
ships, would be solving the second-order problem before the first-order one.

This is a call for whoever owns the product roadmap, not something this memo settles.
