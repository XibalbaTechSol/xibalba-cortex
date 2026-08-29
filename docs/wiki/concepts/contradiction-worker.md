---
title: Contradiction Worker and Proposal Lifecycle
acronyms: [MCP]
created: 2026-08-13
updated: 2026-08-13
type: concept
tags: [provenance, compliance, infrastructure]
confidence: high
source_files:
  - src/xibalba_cortex/contradiction_worker.py
  - src/xibalba_cortex/store.py
  - tests/test_contradiction_worker.py
  - tests/test_task_contract_migration.py
---

# Contradiction Worker and Proposal Lifecycle

## Table of contents

- [Current implementation](#current-implementation)
- [Verification](#verification)
- [Boundaries and open gaps](#boundaries-and-open-gaps)

## Current implementation

`process_contradiction_tasks()` claims bounded `detect_contradictions` tasks with a claim owner and
claim token, checks the source-memory content hash, and obtains candidate memories only from the
contract's explicit `evidence_scope` through bounded evidence retrieval. Candidate output becomes a
reviewable `extraction_proposals` row; it does not directly mutate canonical memory.

`GraphStore.decide_extraction_proposal()` requires status `proposed` before accepting or dismissing
 a proposal. Acceptance checks the subject source content hash and, for newly generated contradiction
 proposals, the captured `contradicting_content_hash` of the candidate memory. If either memory has
 changed, the proposal is marked `stale` and no contradiction edge is written. Acceptance applies
 the contradiction edge only inside the proposal transaction. Repeated acceptance is rejected,
 preventing duplicate durable contradiction records.

## Verification

Focused verification on 2026-08-13:

```text
.venv/bin/python -m pytest -q -o addopts='' tests/test_contradiction_worker.py tests/test_extraction_proposals.py tests/test_task_contract_migration.py tests/test_providers.py
27 passed
```

The tests cover explicit evidence scope, out-of-scope candidate exclusion, no-candidate completion,
source preservation, proposal acceptance, task-contract migration, and failure-class validation.

## Boundaries and open gaps

This evidence is local focused execution, not live Model Context Protocol (MCP) integration or proof
of a real external model run. Candidate discovery is intentionally outside the worker: the trusted
task creator must persist candidate IDs and their observed hashes in `evidence_scope` before queueing.
The worker must not fall back to unrestricted similarity retrieval. Tasks without explicit scope fail
closed.

The full suite remains affected by fixed test ports and daemon-thread lifecycle contamination. A
full run observed address-in-use failures and HTTP 500 responses from colliding test servers. That
is tracked separately as test-isolation work and is not attributed to the contradiction worker.
