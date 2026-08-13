---
title: Hybrid Local-First Providers
acronyms: [MCP, PARA]
created: 2026-08-13
updated: 2026-08-13
type: architecture
tags: [infrastructure, provenance, compliance]
confidence: high
source_files:
  - SPECIFICATION.md
  - spec/xibalba-cortex-v1.md
  - IMPLEMENTATION_PLAN.md
  - src/xibalba_cortex/config.py
  - src/xibalba_cortex/providers.py
  - src/xibalba_cortex/para_worker.py
  - src/xibalba_cortex/embedding_worker.py
  - tests/test_config.py
  - tests/test_providers.py
---

# Hybrid Local-First Providers

The current worktree adds an additive provider boundary to Xibalba Cortex. SQLite remains the canonical evidence store. The default deployment is local: a native agent harness performs language-model inference through the queue, while a short-lived local worker produces versioned embeddings. Hybrid mode can add rebuildable remote projections or explicitly configured fallbacks without making those systems authoritative.

## Table of contents

- [Operating modes](#operating-modes)
- [Provider boundaries](#provider-boundaries)
- [Native-harness inference](#native-harness-inference)
- [Local embeddings](#local-embeddings)
- [Current implementation state](#current-implementation-state)
- [Related pages](#related-pages)

## Operating modes

| Mode | Inference | Embeddings | Canonical store |
| --- | --- | --- | --- |
| `local` | Native agent harness, default Hermes | Local worker | Profile-local SQLite |
| `hybrid` | Native harness or configured fallback | Local worker, optional remote projection | Profile-local SQLite |
| `remote-inference` | Explicit remote provider | Local worker by default | Profile-local SQLite |

Configuration precedence is built-in defaults, profile `config.yaml`, environment overrides, command-line overrides, then task-scoped selection. `xibalba-cortex-operator config show` emits the effective configuration with secret-like fields redacted. `doctor` reports the active provider posture without loading a model.

## Provider boundaries

`config.py` owns descriptive configuration. `providers.py` exposes capability boundaries for inference, embeddings, retrieval, and future projections. These classes do not bypass `GraphStore`, authorize writes, or make external services canonical.

A provider outage must leave raw capture, lexical recall, graph traversal, and queued task evidence available. Remote projections must be rebuildable from canonical records and compared using content hashes or Merkle checkpoints before use.

## Native-harness inference

`NativeHarnessInferenceProvider` invokes the configured native harness only when a worker asks it to infer. The deterministic MCP server does not load a language model. The provider is injectable in tests, and the PARA worker's default runner uses the same boundary.

The harness receives bounded task evidence and must return structured output. Cortex validates the task claim, source-content hash, output contract, and promotion policy before any derived proposal is stored. Model output remains a reviewable derived claim rather than an automatic canonical fact.

## Local embeddings

`embedding_worker.py` remains a short-lived sidecar. It selects eligible active or confirmed memories, compares model/dimension/source-hash metadata, processes bounded batches, rejects invalid vectors, and leaves failures retryable. The local provider boundary describes the model without loading it in the always-on MCP server.

The current default model is `BAAI/bge-small-en-v1.5` with 384 dimensions. A future model registry may add revisions and migration jobs; incompatible vector spaces must never be silently mixed.

## Current implementation state

- Implemented and tested: configuration defaults, profile configuration, environment mode override, redaction, provider capability contracts, and native-harness runner injection.
- Implemented and tested: PARA worker routing through the native-harness provider boundary.
- Implemented and tested: bounded local embedding worker and vector validation.
- Planned: full task-schema registry, richer extraction task families, model registry, hybrid retrieval fusion, remote projection reconciliation, and general Merkle inclusion-proof APIs.
- Status boundary: this page documents the current uncommitted worktree, not a released or production-certified capability.

## Related pages

- [Inference Queue and Recovery](inference-queue.md)
- [Embedding Worker](../concepts/embedding-worker.md)
- [PARA Classification](../concepts/para-classification.md)
- [Viewer and Local API](viewer-and-local-api.md)
- [Integrity and Merkle Evidence](../concepts/integrity-and-merkle-evidence.md)
