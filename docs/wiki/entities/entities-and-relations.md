---
title: Entities and Relations
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: entity
tags: [storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - docs/operations/store-contract.md
---

## Table of contents

- [Overview](#overview)
- [Tables](#tables)
- [Traversal](#traversal)

## Overview

`entities` and `relations` (plus `entity_aliases` and `memory_entities`) hold the bounded graph
that sits alongside the memory store: nodes and edges extracted from, or explicitly asserted
against, memory content, each carrying provenance back to the memory that supports it.

## Tables

- **`entities`** — `id`, `canonical_name`, `normalized_name`, `entity_type`,
  `normalization_version`. `UNIQUE(normalized_name, entity_type)`.
- **`entity_aliases`** — alternate names for an entity, each with an `evidence_memory_id` and a
  `confidence` (0–1).
- **`memory_entities`** — many-to-many link between a memory and the entities it mentions, with
  an `evidence_quote` recording the supporting text.
- **`relations`** — subject/predicate/object edges: `subject_entity_id`, `predicate`,
  `object_entity_id` **or** `object_literal` (exactly one of the two, enforced by a `CHECK`
  constraint), `evidence_memory_id` (required — every relation must cite the memory that
  supports it), `confidence` (0–1), and its own lifecycle `status` (`candidate`, `active`,
  `confirmed`, `disputed`, `superseded`, `forgotten`).

## Traversal

Graph traversal is bounded and evidence-linked, exposed via `memory_neighbors` and
`memory_find_path` (MCP tools; see [MCP Tool Surface](../concepts/mcp-tool-surface.md)):

- `neighbors(subject, max_depth=1)` accepts depths `1..3`, enforces node and edge limits, and
  reports `truncated` truthfully when a limit was hit rather than silently dropping results.
- `find_path(from_entity, to_entity, max_depth=3)` accepts depths `1..5` and returns the
  shortest discovered relation path.

Graph payloads returned by these tools include relation, similarity, and contradiction edges;
contradiction edges are navigation evidence for a caller to resolve, not automatic resolution
(see [Lifecycle and Forgetting](../concepts/lifecycle-and-forgetting.md)). Relation rows carry
`evidence_memory_id` specifically so the viewer and MCP caller can jump back to provenance — see
[Graph Store](../concepts/graph-store.md) for the store-level object model this graph sits
inside.
