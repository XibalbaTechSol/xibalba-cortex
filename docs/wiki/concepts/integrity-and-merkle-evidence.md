---
title: Integrity and Merkle Evidence
acronyms: [MCP]
created: 2026-08-13
updated: 2026-08-13
type: concept
tags: [provenance, compliance]
confidence: high
source_files:
  - spec/xibalba-cortex-v1.md
  - SPECIFICATION.md
  - src/xibalba_cortex/store.py
  - src/xibalba_cortex/exchange_builder.py
  - tests/test_store.py
---

# Integrity and Merkle Evidence

Xibalba Cortex uses hash chains and Merkle-style exchange roots as local tamper-evident evidence. These structures are deliberately narrower than truth, authorization, identity ownership, completeness, or external finality.

## Table of contents

- [Current capabilities](#current-capabilities)
- [Planned hybrid uses](#planned-hybrid-uses)
- [Verification boundary](#verification-boundary)
- [Related pages](#related-pages)

## Current capabilities

Memory event chains can be recomputed and verified for a memory. Session exchange chains commit to ordered prompt, response, tool-event, and context-contribution references. The current session root is a local head node and can be inspected through the Model Context Protocol (MCP), local API, viewer, and operator command.

## Planned hybrid uses

Future Merkle profiles may checkpoint retrieval traces, local-to-remote projection exports, backup snapshots, and derived inference proposals. A projection can compare its content hashes or declared root against the canonical local state before it is used. This provides a synchronization and drift signal without making the projection authoritative.

Each tree profile must declare its canonicalization, leaf schema, ordering, duplicate handling, odd-width rule, hash algorithm, and root type before interoperable proofs are advertised.

## Verification boundary

A valid hash or root proves that the checked bytes and declared structure recompute consistently. It does not prove that the underlying memory is true, that an agent was authorized, that a key legally belongs to a person or company, that the set is complete, or that an external Integrity Protocol anchor exists.

Retrieved memory remains untrusted data. A Merkle citation can support provenance inspection but cannot grant instructions or permissions.

## Related pages

- [Hybrid Local-First Providers](../architecture/hybrid-local-first-providers.md)
- [Inference Queue and Recovery](../architecture/inference-queue.md)
- [Viewer and Local API](../architecture/viewer-and-local-api.md)
