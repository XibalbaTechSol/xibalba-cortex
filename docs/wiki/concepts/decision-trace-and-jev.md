---
title: DecisionTrace and Jev Advisory Correlation
acronyms: [Jev, LLM, Merkle]
created: 2026-10-04
updated: 2026-10-04
type: concept
tags: [provenance, compliance, infrastructure]
confidence: high
source_files:
  - src/xibalba_cortex/jev_gateway.py
  - src/xibalba_cortex/decision_trace_view.py
  - src/xibalba_cortex/hermes_observer.py
  - src/xibalba_cortex/local_api.py
---

# DecisionTrace and Jev Advisory Correlation

Cortex exposes a redacted, parent-linked view of observable agent transitions. It is a correlation
surface for auditors and operators, not a hidden chain-of-thought store and not a causal proof
system. Cortex remains the governed memory/provenance product; Integrity remains the verification
substrate and Shield remains the enforcement authority. See [`Integrity and Merkle Evidence`](integrity-and-merkle-evidence.md)
and [`Sessions and Exchanges`](../entities/sessions-and-exchanges.md).

## Table of contents

- [Gateway contract](#gateway-contract)
- [Rendered audit view](#rendered-audit-view)
- [API boundary](#api-boundary)
- [Evidence limits](#evidence-limits)

## Gateway contract

`JevGateway.analyze(event)` accepts an Integrity `DecisionEnvelope` and returns a validated
`JevAnalysis`. The gateway accepts a deterministic `FixtureJevProvider` for offline operation and
`HttpJevProvider` for an optional JSON service. Provider failures become `unavailable` or
`rejected` advisory status; they do not invalidate the observed event or change policy.

`HttpJevProvider` enforces a response-size bound, requires a JSON object, binds the returned
analysis to the observed event hash, and sets `causal_claim` to `false`. The gateway sends the
already-redacted envelope body; raw prompts, completions, tool arguments, and chain-of-thought are
outside this projection.

## Rendered audit view

`render_decision_trace_html(projection)` renders the trace ID, local verification status,
domain-separated root, event sequence, parent hashes, provider status, transition probabilities,
and an explicit authority boundary. The view labels every probability as observational and shows
that deterministic Shield/OPA/BCC remains responsible for enforcement.

## API boundary

The local API serves a read-only projection at:

```text
GET /api/session/{id}/decision-trace?trace_id=<trace-id>
```

The projection is profile/store scoped before it is returned. It can include event detail, advisory
status, transition probabilities, the trace root, and inclusion proofs. It does not grant write
access, alter memory, approve an action, or replace Cortex content provenance.

## Evidence limits

Parent links establish a declared or observed sequence. Merkle roots and inclusion proofs establish
integrity and inclusion of the recorded projection. Neither establishes that one model step caused
another, that a probability is calibrated, or that an action was authorized. Those claims require
separate policy, receipt, approval, and outcome evidence.
