# Hybrid Retrieval, Hermes Extraction, and Projection Reconciliation

**Status:** Implemented partial vertical slice; locally verified.

The latest extension adds a bounded Hermes worker path from inference-task claim through structured extraction validation and claim-token completion. Entity and relation outputs require a versioned schema and an input snapshot hash matching the current subject memory. Invalid results fail closed as task evidence; no durable fact is promoted automatically.

Hybrid retrieval now exposes lexical, vector, graph, and temporal channels, fuses available ranks, persists a retrieval trace, and returns per-result content hash, source identifier, evidence class, lifecycle status, and signal membership. Vector and graph absence is explicit and lexical retrieval remains available in degraded mode.

Projection comparison is canonical-left. Root mismatch, omitted leaves, and reordering are reported; divergence produces a rebuild recommendation. Merkle roots are limited byte-commitment evidence and do not prove truth, completeness, authorization, identity ownership, or external finality.

See:

- `spec/latest-hybrid-extraction.md`
- `docs/plans/2026-08-13-latest-hybrid-extraction.md`
- `src/xibalba_cortex/hermes_worker.py`
- `src/xibalba_cortex/projection_reconcile.py`
- `tests/test_hybrid_extraction_latest.py`

The live worker command boundary and production projection apply loop remain follow-up work. The current focused test evidence is four passing tests; the pre-existing full suite was 229 passed, 1 skipped before the latest additive changes.
