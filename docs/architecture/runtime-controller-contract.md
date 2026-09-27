# Xibalba Runtime Controller Contract

Status: implemented prototype contract, not production-certified.

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

`src/xibalba_cortex/runtime_bridge_contract.py`

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

`src/xibalba_cortex/runtime_bridge_contract.py`

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
- `record_model_exchange(...)`
- `request_memory_inference(...)`

The controller is the only component allowed to decide how runtime events become memory, telemetry, or policy records.

`open_session(..., agent_id=...)` persists the resolved agent partition on the session when it
creates the session, as well as recording the runtime binding. If `ingest_event()` implicitly
opens a session after a prior identity bind, it carries that bound `agent_id` into session
creation. This keeps the session row and subsequent event attribution in the same agent
namespace. An event without a binding remains unattributed; adapters must not infer an agent
from a profile label or session identifier.

## Adapter responsibilities

### Claude Code

Transport: hooks

Responsibilities:
- session start and end hooks
- pre-tool gating
- post-tool reporting
- trace continuity
- memory bus access

Prototype guarantees:
- pre-tool policy evaluation routes through `XibalbaRuntimeController.evaluate_policy`
- post-LLM and post-tool events route through `XibalbaRuntimeController`
- normalized event ingest preserves trace, tool, intent, outcome, and missing telemetry as explicit nulls
- stable session correlation through the controller/store session APIs

Current limitation:
- live user-local hook installation still needs environment-level verification before claiming automatic enforcement by a running Claude Code process.

### agy

Transport: forwarded hook callbacks, with wrapper fallback

`runtime_agy_hook(hook_name, event)` accepts a normalized event mapping through
the existing `memory:write` MCP authorization boundary. A native plugin or SDK
callback must supply `session_id`; optional fields include `turn_id`,
`invocation_id`, `event_id`, `tool_name`, `status`, and `traceparent`.
Tool inputs/results are hashed and error bodies are omitted. Repeated deliveries
with the same upstream event ID and hook phase are deduplicated. Callbacks without
an upstream event ID are distinct observations. This is an ingestion boundary;
Native Agy observation hooks are installed and live-tested on this workstation;
blocking policy decisions remain unverified. See
[installation evidence](harness-hook-installation.md) for commands, canary IDs,
Hermes delivery corrections, and remaining production limits.

Responsibilities:
- wrapper session start and end
- identity binding
- memory bus access
- best-effort telemetry

Guarantees:
- shared identity binding
- lifecycle telemetry

Limitations:
- native hook callbacks can be forwarded from a configured CLI plugin or Python SDK agent
- callback payloads and actual coverage are integration-defined and require live verification
- no Claude-equivalent pre-tool or post-tool coverage is claimed without that evidence
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
- measured lifecycle hook discovery (`SessionStart`, `Stop` in the active coordinator plugin)

Limitations:
- lifecycle hook effects are plugin-defined and must not be inferred from event names alone
- tool-level parity is unverified until measured

## Interpretation rules

1. Shared identity does not imply shared enforcement.
2. Shared memory does not imply shared telemetry fidelity.
3. Missing hook support must be reported, not hidden.
4. A runtime that cannot emit pre-tool or post-tool hooks must not claim Claude-equivalent behavior.
5. Canonical memory remains separate from orchestration and runtime automation.

## Implemented prototype surface

This repository now contains:

1. `src/xibalba_cortex/runtime_bridge_contract.py` for schema, controller interface, and runtime capability records.
2. `src/xibalba_cortex/runtime_controller.py` as the only adapter-facing façade over `GraphStore`.
3. `src/xibalba_cortex/claude_adapter.py` for session, pre-tool, post-LLM, post-tool, and API-error hook translation.
4. `src/xibalba_cortex/agy_adapter.py` for wrapper fallback and generic native-hook callback telemetry.
5. `src/xibalba_cortex/codex_probe.py` for live launcher discovery without hook-parity claims.
6. MCP tools in `src/xibalba_cortex/server.py` for controller status, session open/close, identity binding, event ingest, policy evaluation, Claude adapter hooks, agy wrapper events, and Codex probe.

Runtime contract tests:

- `tests/test_runtime_bridge_contract.py`
- `tests/test_runtime_adapters.py`
- `tests/test_server.py::test_runtime_controller_tools_through_mcp`
- `tests/test_server.py::test_runtime_adapter_tools_through_mcp`

The negative tests assert that missing telemetry remains null, Agy does not claim unverified hook coverage, wrapper observations remain distinct from native callbacks, and Codex reports only lifecycle hooks found in the active plugin registry; tool-hook parity remains unclaimed.
