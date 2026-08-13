---
title: Embedding Worker
acronyms: [FTS5]
created: 2026-08-13
updated: 2026-08-13
type: concept
tags: [storage, provenance, infrastructure]
confidence: high
source_files:
  - src/xibalba_cortex/embedding_worker.py
  - src/xibalba_cortex/store.py
  - tests/test_embedding_worker.py
  - docs/architecture/embedding-model-spike.md
---

# Embedding Worker

The implementation described on this page exists in the current uncommitted worktree and has passed the cited tests. It is not a released or default-branch capability until the worktree changes are reviewed and committed.

The embedding worker is a short-lived sidecar process that projects eligible memory content into the versioned vector index. The always-on Model Context Protocol server does not load the embedding model.

## Table of contents

- [Eligibility](#eligibility)
- [Bounded processing](#bounded-processing)
- [Validation and failure isolation](#validation-and-failure-isolation)
- [Freshness protection](#freshness-protection)
- [Operations](#operations)
- [Verification](#verification)
- [Current live state](#current-live-state)
- [Related pages](#related-pages)

## Eligibility

`eligible_memories()` selects memories with `active` or `confirmed` status whose embedding metadata is missing or stale. Freshness is checked against the pinned model identifier, dimension, and source content hash.

The worker intentionally does not claim that every memory must have a vector. Lifecycle state and eligibility determine whether a memory is included.

## Bounded processing

`embed_memories()` accepts `batch_size` and `max_items` limits. Model inference occurs in batches, while each vector write is isolated so one malformed vector or database write does not abort the remaining items.

The result reports:

- `processed`
- `embedded`
- `failed`
- `remaining`

## Validation and failure isolation

Before persistence, each vector must:

- have the pinned dimension;
- contain only finite numeric values; and
- have a non-zero norm.

Wrong-dimension, zero, non-finite, and write-failure cases remain eligible for retry rather than being recorded as successful embeddings.

## Freshness protection

Embedding writes use the source content hash as an expected compare-and-set value. If a memory changes after eligibility was calculated, the write is rejected rather than associating an old vector with new content.

## Operations

Dry-run:

```bash
uv run xibalba-cortex-embedding-worker \
  --home "$HOME/.hermes/xibalba-cortex" \
  --dry-run
```

A non-dry run loads the pinned model in the worker process. Model download and runtime availability are external operational prerequisites and should be reported rather than hidden.

## Verification

Focused verification covers batching, missing/stale-vector detection, content-hash protection, wrong dimensions, zero vectors, non-finite values, per-item failure isolation, and remaining-work reporting:

```bash
uv run pytest -q tests/test_embedding_worker.py
```

## Current live state

On 2026-08-13, the live profile's dry-run reported `eligible memories: 0`. The viewer reported 83 embedded memories across the profile, while the worker found no active or confirmed memories requiring backfill or refresh. These are different measures and must not be conflated with “all memories are embedded.”

## Related pages

- [Graph Store](graph-store.md)
- [Inference Queue and Recovery](../architecture/inference-queue.md)
- [Store Schema Overview](../architecture/store-schema-overview.md)
- [Viewer and Local API](../architecture/viewer-and-local-api.md)
