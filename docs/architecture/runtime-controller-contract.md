# Xibalba Runtime Controller Contract

Status: first implementation pass.

This document defines the shared interface that lets Claude Code, agy, and Codex operate under the Xibalba identity while sharing the same canonical memory and Hermes tool bus.

The key design rule is simple:
- Hermes Model Context Protocol is the shared transport and discovery layer.
- The controller owns identity binding, session state, memory access, and normalized telemetry.
- Runtime adapters are thin translators, not authorities.

## Contract objectives

- One Xibalba identity across supported runtimes.
- One canonical memory service.
- One normalized event schema.
- Honest capability reporting when a runtime cannot provide a hook or trace surface.
- No adapter writes directly to canonical storage.

## Canonical event schema

The normalized controller event record is defined in:

`src/xibalba_graph/runtime_bridge_contract.py`

Required record fields:

- `schema_version`
- `runtime`
- `session_id`
- `turn_id`
- `traceparent`
- `agent_id`
- `intent_rationale`
- `tool_name`
- `tool_input_hash`
- `tool_outcome`
- `token_usage`
- `assistant_response`
- `observed_at_utc`
- `provenance`
- `metadata`

The event record must preserve missing values as explicit nulls. Missing context is a capability gap, not a reason to invent data.

## Controller interface

The controller boundary is also defined in:

`src/xibalba_graph/runtime_bridge_contract.py`

Core methods:

- `register_runtime(...)`
- `bind_identity(...)`
- `open_session(...)`
- `close_session(...)`
- `ingest_event(...)`
- `ingest_events(...)`
- `read_memory(...)`
- `write_memory(...)`
- `evaluate_policy(...)`

The controller is the only component allowed to decide how runtime events become memory, telemetry, or policy records.

## Adapter responsibilities

### Claude Code

Transport: hooks

Responsibilities:
- session start and end hooks
- pre-tool gating
- post-tool reporting
- trace continuity
- memory bus access

Guarantees:
- per-tool policy enforcement
- normalized event ingest
- stable session correlation

### agy

Transport: wrapper

Responsibilities:
- wrapper session start and end
- identity binding
- memory bus access
- best-effort telemetry

Guarantees:
- shared identity binding
- lifecycle telemetry

Limitations:
- no native hook surface
- no pre-tool or post-tool hooks
- trace continuity is best effort only

### Codex

Transport: launcher

Responsibilities:
- identity binding
- launcher session context
- memory bus access
- telemetry normalization

Guarantees:
- shared identity binding
- shared memory access

Limitations:
- hook surface must be discovered in the live environment
- tool-level parity is unverified until measured

## Interpretation rules

1. Shared identity does not imply shared enforcement.
2. Shared memory does not imply shared telemetry fidelity.
3. Missing hook support must be reported, not hidden.
4. A runtime that cannot emit pre-tool or post-tool hooks must not claim Claude-equivalent behavior.
5. Canonical memory remains separate from orchestration and runtime automation.

## First implementation pass

This repository now contains the contract module and adapter responsibility records. The next pass should:

1. Wire the controller methods into an actual service boundary.
2. Add a thin Claude adapter that emits `RuntimeEvent` records.
3. Add an agy wrapper that emits lifecycle-only records when tool hooks are absent.
4. Discover and classify the live Codex integration surface.
5. Add tests that prove missing capabilities are surfaced honestly.
