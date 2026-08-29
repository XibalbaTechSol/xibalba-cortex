---
title: Hybrid Extraction and Retrieval
acronyms: [MCP, RRF]
created: 2026-08-13
updated: 2026-08-19
type: concept
tags: [storage, provenance, mcp, compliance]
confidence: high
source_files:
  - spec/latest-hybrid-extraction.md
  - src/xibalba_cortex/hermes_worker.py
  - src/xibalba_cortex/providers.py
  - src/xibalba_cortex/store.py
  - src/xibalba_cortex/events.py
  - src/xibalba_cortex/projection_reconcile.py
  - tests/test_extraction_proposals.py
  - tests/test_hermes_worker_isolation.py
  - tests/test_retrieval_trace_fields.py
  - tests/test_projection_checkpoints.py
  - tests/test_merkle_domains.py
---

## Table of contents

- [Overview](#overview)
- [Hermes extraction](#hermes-extraction)
- [Hybrid retrieval and traces](#hybrid-retrieval-and-traces)
- [Projection checkpoints](#projection-checkpoints)
- [Merkle evidence boundary](#merkle-evidence-boundary)
- [Verification evidence](#verification-evidence)
- [Related pages](#related-pages)

## Overview

# Hybrid Retrieval, Hermes Extraction, and Projection Reconciliation

**Status:** Implemented vertical slices; locally verified. This page records repository evidence, not a claim of production deployment or external anchoring.

## Hermes extraction

The dedicated `xibalba-cortex-worker` profile provides an isolated Hermes worker path from inference-task claim through structured extraction validation and claim-token completion. The profile disables persistent memory and limits the Cortex Model Context Protocol (MCP) surface to the four task/evidence tools needed by the worker.

A live, unmocked round trip against a throwaway store completed an extraction task and produced three entities. The server validated the input snapshot hash, output schema, and evidence-quote containment before inserting reviewable `extraction_proposals`. Extraction remains proposal-only: acceptance is explicit, source memories are not mutated, and stale source hashes become `stale` rather than being promoted. The earlier diagnostic that returned unrelated recalled-context quotes remains documented as a fail-closed isolation finding in `spec/latest-hybrid-extraction.md`.

## Hybrid retrieval and traces

Hybrid retrieval exposes lexical, vector, graph, and temporal channels, fuses available ranks with Reciprocal Rank Fusion (RRF), and persists a reproducible retrieval trace. Trace version 2 records the profile domain, query-vector hash, embedding model metadata, filters, candidate-pool sizes, RRF parameters, graph evidence, per-channel ranks/raw scores, result leaf hashes, and the projection checkpoint observed at retrieval time. Missing vector or graph channels are explicit; lexical retrieval remains available in degraded mode.

Each trace has a domain-separated Merkle root over its result leaves. `retrieval_trace_evidence(trace_id, rank=...)` returns an inclusion proof for an individual result, allowing selective verification without treating the entire trace payload as trusted.

## Projection checkpoints

Projection checkpoints are computed from canonical SQLite tables (`memories`, `entities`, and `relations`), not from a derived cache. The store supports checkpoint history, latest-checkpoint lookup, reconciliation, and rebuild. Reconciliation compares a fresh canonical recomputation with the recorded projection root, persists a reconciliation record, and marks a checkpoint `degraded` on mismatch. Rebuild performs an independent second recomputation before accepting the new checkpoint.

Canonical-left comparison reports root mismatch, omitted leaves, and reordering, with a rebuild recommendation on divergence. This is projection consistency evidence, not proof that a projection is complete beyond the committed set.

## Merkle evidence boundary

Domain-separated roots use explicit domains and leaf positions so projection and retrieval commitments cannot collide and same-pair swaps are detectable. Legacy session-exchange Merkle primitives remain unchanged. A root or inclusion proof establishes only defined byte-inclusion properties under the declared construction; it does not prove truth, authorization, identity ownership, execution, completeness outside the committed set, or external finality.

## Verification evidence

The session evidence recorded a full Cortex test result of `273 passed, 1 skipped, 1 warning`, plus focused extraction, worker-isolation, retrieval-trace, projection-checkpoint, and Merkle-domain coverage. These are local test results from the session and do not establish a released build, multi-replica delivery guarantee, or live external Model Context Protocol provider round trip beyond the bounded worker test described above.

## Related pages

- [Inference Queue and Recovery](../architecture/inference-queue.md)
- [Integrity and Merkle Evidence](integrity-and-merkle-evidence.md)
- [Hybrid Local-First Providers](../architecture/hybrid-local-first-providers.md)
- [PARA Classification Worker](para-classification.md)
- [Graph Store](graph-store.md)
