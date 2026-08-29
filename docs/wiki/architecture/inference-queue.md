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
  - src/xibalba_cortex/providers.py
  - src/xibalba_cortex/server.py
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
- [In-session self-extraction](#in-session-self-extraction)
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

## In-session self-extraction

The lifecycle above is normally driven by `NativeHarnessInferenceProvider` (`providers.py`), which shells out to an isolated Hermes worker profile via `subprocess.run` -- a separate process that can only ever see the bounded evidence its task contract permits, and nothing else. That isolation is real, but it is a defense-in-depth measure, not the mechanism that actually makes a completed task trustworthy: `complete_inference_task` validates every output server-side (schema conformance, `input_snapshot_hash` match against the real evidence snapshot, and `evidence_quote` containment) "regardless of which caller invokes completion (in-process Python or an external MCP client holding a valid claim token)". Any caller holding a valid claim token can complete a task, isolated worker or not.

`InSessionInferenceProvider` (`providers.py`) is the second path this makes possible: the calling agent (e.g. a live MCP session) does its own extraction inline, no subprocess. `memory_start_self_extraction(task_type, subject_type, subject_id, input_payload, claimed_by)` composes `request_inference_task` + `claim_inference_task` + the same bounded-evidence fetch `memory_evidence_bundle` uses (`fetch_bounded_evidence_for_task`) into one round trip, returning `{task_id, claim_token, evidence}`. The caller then completes the task exactly as any worker would, via the existing `memory_complete_inference_task`.

Only `extract_entities`, `extract_relations`, and `detect_contradictions` are accepted -- the task types with a real server-side output validator (`validate_extraction_result`/`validate_contradiction_result`). The other task types in `_INFERENCE_TASK_TYPES` have no shared output validator and are out of scope for this path; use `request_inference_task` for those.

**The real tradeoff, stated plainly:** the calling agent's own session can see more than the evidence bundle it was handed (the rest of its conversation, other memories it recalled). Output validation still forces every claimed evidence quote to be grounded in the real bounded snapshot, but there is no mechanical proof the *selection* of what to extract wasn't influenced by context outside that scope -- unlike a subprocess-isolated worker, which structurally cannot see anything else. Use the isolated worker path when that guarantee matters; use self-extraction when speed and simplicity matter more and the calling agent is trusted.

**Known, separate inconsistency, not fixed by this feature**: the actual isolated worker (`hermes_worker.py`) does not itself call `memory_evidence_bundle` / `fetch_bounded_evidence_for_task` -- it reads via a direct, unbounded `store.get_memory(...)` call. The bounded-evidence contract mechanism exists and is enforced for `memory_evidence_bundle` and `memory_start_self_extraction`, but the isolated worker bypasses it today. Recorded here, not addressed.

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
