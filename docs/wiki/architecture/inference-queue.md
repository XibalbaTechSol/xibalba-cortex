---
title: Inference Queue and Recovery
acronyms: [PARA]
created: 2026-08-13
updated: 2026-08-13
type: architecture
tags: [storage, provenance, infrastructure, compliance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - src/xibalba_cortex/para_worker.py
  - src/xibalba_cortex/operator.py
  - tests/test_store.py
  - tests/test_para_worker.py
  - viewer/src/api.ts
---

# Inference Queue and Recovery

The implementation described on this page exists in the current uncommitted worktree and has passed the cited tests. It is not a released or default-branch capability until the worktree changes are reviewed and committed.

Inference work is stored in SQLite as durable, idempotent tasks. Claim metadata provides ownership checks and lease-based at-least-once processing for workers such as the PARA classifier.

## Table of contents

- [Task lifecycle](#task-lifecycle)
- [Claim ownership](#claim-ownership)
- [Lease recovery and retry bounds](#lease-recovery-and-retry-bounds)
- [Atomic completion](#atomic-completion)
- [Operational reconciliation](#operational-reconciliation)
- [Known legacy-data gap](#known-legacy-data-gap)
- [Verification](#verification)
- [Related pages](#related-pages)

## Task lifecycle

The inference task table records the task type, subject, input payload, output or error, requester, status, timestamps, and additive claim metadata. Task creation is idempotent for the same explicit task identity.

The normal lifecycle is:

```text
pending -> claimed -> completed
                    └-> failed
```

## Claim ownership

Schema version 5 adds:

- `claim_owner`
- `claim_token`
- `lease_expires_at`
- `attempt_count`

A worker must complete a task with the matching owner and claim token. Terminal completion clears claim metadata. A pending task or a task claimed by another worker cannot be completed by an unrelated caller.

## Lease recovery and retry bounds

Expired claims can be reclaimed. `requeue_expired_inference_tasks()` clears stale claim metadata and requeues work below the configured attempt limit; tasks at or above the limit become failed. The operator command exposes reconciliation:

```bash
uv run xibalba-cortex-operator \
  --home "$HOME/.hermes/xibalba-cortex" \
  requeue-expired --limit 50 --max-attempts 3
```

This provides at-least-once processing. It does not provide exactly-once model execution: a worker can fail after model execution and before durable completion.

## Atomic completion

PARA proposal creation occurs in the same database transaction as the ownership-checked completion update. A stale or unauthorized completion therefore cannot leave a durable proposal behind.

## Operational reconciliation

The recovery operation returns counts for expired, requeued, and failed tasks. It should be run after worker interruption or as a scheduled maintenance action. The postcondition is observable through the task list and status API rather than inferred from a process exit code alone.

## Known legacy-data gap

The live profile inspected on 2026-08-13 contained six claimed `summarize_session` rows without claim owner, claim token, lease expiry, or attempt metadata. These are legacy or malformed claimed rows and are not silently counted as healthy current claims. They require an explicit migration or dead-letter decision before the live queue can be described as fully reconciled.

## Verification

```bash
uv run pytest -q tests/test_store.py tests/test_para.py tests/test_para_worker.py
```

## Related pages

- [PARA Classification Worker](../concepts/para-classification.md)
- [Embedding Worker](../concepts/embedding-worker.md)
- [Graph Store](../concepts/graph-store.md)
- [Viewer and Local API](viewer-and-local-api.md)
