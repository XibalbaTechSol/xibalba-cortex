# Latest Hybrid Extraction Implementation Plan

> **For Hermes:** Execute task-by-task with test-driven development and verify every postcondition.

**Goal:** Complete and verify the controlled Hermes extraction vertical slice plus hybrid retrieval evidence and projection reconciliation.

**Architecture:** Keep frozen v1 GraphStore/MCP contracts additive. Add a bounded Hermes worker, retrieval trace tables/API, and a pure canonical-left reconciliation module. Use SQLite as evidence authority and Merkle roots only as limited byte-commitment evidence.

**Tech Stack:** Python 3.12, SQLite/FTS5/sqlite-vec, Hermes CLI, pytest, React/Vite viewer.

---

### Task 1: Establish failing vertical-slice tests

Files: `tests/test_hybrid_extraction_latest.py`

Write tests for persisted four-channel retrieval traces, root divergence, Hermes-shaped extraction completion, and snapshot mismatch rejection. Run:

```bash
.venv/bin/python -m pytest -q -o addopts='' tests/test_hybrid_extraction_latest.py
```

Expected initial state: collection fails because the new worker and reconciliation modules do not exist.

### Task 2: Add extraction validation and worker

Files: `src/xibalba_cortex/hermes_worker.py`

Implement claim → bounded subject read → injected/configured Hermes runner → JSON parse → schema and source-hash validation → claim-token completion. Fail closed on malformed output and retain task failure evidence.

Verify the focused extraction tests pass.

### Task 3: Add retrieval trace persistence and fusion

Files: `src/xibalba_cortex/store.py`, `src/xibalba_cortex/server.py`

Add additive tables and methods. Generate lexical, vector, graph, and temporal candidates; fuse ranks; attach per-result provenance; persist a trace root; expose MCP read/write tools. Preserve lexical degraded mode.

Verify focused retrieval tests and existing store/API tests.

### Task 4: Add projection root comparison

Files: `src/xibalba_cortex/projection_reconcile.py`

Implement exact equality, missing leaves, reorder detection, and canonical-left rebuild decision. Do not add a remote write path.

Verify focused reconciliation tests.

### Task 5: Update normative specification and operational ledger

Files: `spec/latest-hybrid-extraction.md`, `SPECIFICATION.md`, `IMPLEMENTATION_PLAN.md`, `README.md`

Record implemented behavior, explicit limitations, root semantics, and measured commands. Do not mark live production or browser end-to-end behavior complete without evidence.

### Task 6: Build viewer and collect live diagnostics

Files: `viewer/`

Run the existing viewer build, local API smoke checks, MCP discovery check if available, and full Python tests. Record exact outputs and warnings. If a dependency or service is unavailable, record the gap rather than substituting a claim.
