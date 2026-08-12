---
title: Runtime Adapters
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [identity, mcp, infrastructure]
confidence: high
source_files:
  - src/xibalba_cortex/runtime_bridge_contract.py
  - src/xibalba_cortex/runtime_controller.py
  - src/xibalba_cortex/claude_adapter.py
  - src/xibalba_cortex/agy_adapter.py
  - src/xibalba_cortex/codex_probe.py
  - src/xibalba_cortex/server.py
---

## Table of contents

- [Overview](#overview)
- [The three adapters](#the-three-adapters)
- [Enforcement boundary is looser than the type](#enforcement-boundary-is-looser-than-the-type)
- [Controller interface](#controller-interface)

## Overview

The runtime-adapter layer is a richer, opt-in identity-and-policy layer on top of the generic
store primitives — not the only way into Cortex. `RuntimeName = Literal["claude", "agy",
"codex"]` in `runtime_bridge_contract.py` documents the three officially-adapted runtimes, each
with a real per-runtime adapter and a declared set of guarantees. Any other harness talks to
the store directly through the generic MCP tools (`memory_remember`, `memory_recall`,
`memory_ingest_agent_turn`, …) without going through this layer at all — see
[Generic Ingestion](generic-ingestion.md).

## The three adapters

`runtime_bridge_contract.py` defines a `RuntimeAdapterResponsibilities` record per runtime:

| Runtime | Transport | Status | Notes |
|---|---|---|---|
| `claude` (`claude_adapter.py`) | `hooks` | `implemented` | Richest native hook surface; treated as the reference adapter. Guarantees per-tool policy enforcement, session trace propagation, normalized event ingest. |
| `agy` (`agy_adapter.py`) | `wrapper` | `partial` | Wrapper-only today: `no_native_hook_surface`, `no_pre_tool_or_post_tool_hooks`, `trace_continuity_is_best_effort_only` — explicitly must not claim Claude-equivalent tool-level parity. |
| `codex` (`codex_probe.py`) | `launcher` | `unknown` | `hook_surface_must_be_discovered`, `tool_level_parity_is_unverified` — the integration surface must be measured live before stronger claims are made. |

Each adapter's `limitations` tuple is populated honestly: missing pre-tool/post-tool/lifecycle
hooks are recorded as real capability gaps, not smoothed over to look like parity with the
Claude adapter.

## Enforcement boundary is looser than the type

`RuntimeName` is a `Literal["claude", "agy", "codex"]` at the type level, but the actual
`runtime_*` MCP tools in `server.py` (`runtime_open_session`, `runtime_close_session`,
`runtime_bind_identity`, …) only check that `runtime` is a non-empty string — the `Literal` is
not runtime-enforced. The code comment in `server.py` is explicit about why: `"claude"`/`"agy"`/
`"codex"` have real adapters with richer guarantees, but a generic or new harness name is valid
too; only an empty/missing identifier is rejected. So the three-runtime contract documents what
exists with dedicated adapter code, not a hard allowlist the server enforces.

## Controller interface

`RuntimeController` (a `Protocol` in `runtime_bridge_contract.py`) defines the shared surface
every adapter is built against: `register_runtime`, `bind_identity`, `open_session`,
`close_session`, `ingest_event`/`ingest_events`, `read_memory`/`write_memory`,
`evaluate_policy`, `record_model_exchange`, `request_memory_inference`. `RuntimeEvent` is the
normalized telemetry record adapters produce — missing fields are represented as explicit
nulls, never invented values.

See [MCP Tool Surface](mcp-tool-surface.md) for where these are exposed as tools, and
[Graph Store](graph-store.md) for the underlying store the controller writes into.
