# Xibalba Runtime Adapter Checklist

> Goal: operate as the Xibalba agent identity with shared memory and Hermes tools across Claude Code, agy, and Codex.
>
> Conclusion: Hermes Model Context Protocol is the shared backbone, not the full solution. Use it as the tool and memory bus, then add runtime adapters for lifecycle, telemetry, and policy parity.

## 0. Design boundary

- Canonical storage lives in the Xibalba graph memory / Integrity layer.
- Hermes is the controller and retrieval surface.
- Claude Code, agy, and Codex are clients with different hook capabilities.
- No runtime is allowed to become its own memory authority.
- No adapter may write directly to canonical storage without going through the controller API.

## 1. Required architecture layers

### 1.1 Canonical identity layer
- [ ] Create or confirm one Xibalba identity bridge for all runtimes.
- [ ] Resolve the active agent identity from profile, environment, or explicit override.
- [ ] Ensure the same DID / keypair is reused across runtimes where intended.
- [ ] Record identity provenance separately from semantic memory.

### 1.2 Canonical memory layer
- [ ] Expose read APIs for recall, profile, graph traversal, and evidence lookup.
- [ ] Expose write APIs for memory ingest, correction, contradiction, and forgetting.
- [ ] Preserve append-only provenance and immutable revisions.
- [ ] Keep deterministic storage separate from orchestration and inference.

### 1.3 Runtime adapter layer
- [ ] Claude adapter: use hooks for session start, session end, pre-tool, and post-tool events.
- [ ] agy adapter: use the shell wrapper as the lifecycle shim because agy has no hook system.
- [ ] Codex adapter: identify the minimal launcher or wrapper surface and normalize its events.
- [ ] Normalize all runtime events to one schema before sending to the controller.

### 1.4 Policy and telemetry layer
- [ ] Carry `session_id` through every runtime if the runtime supports it.
- [ ] Carry `traceparent` or equivalent per-session trace context.
- [ ] Carry `intent_rationale` or a runtime-specific equivalent.
- [ ] Carry tool input hash, tool outcome, token usage, and timestamps.
- [ ] Emit honest failures when a runtime cannot supply a field.

## 2. Shared event schema

Every runtime should emit the same normalized event envelope:

- `runtime`: `claude` | `agy` | `codex`
- `session_id`: stable session identifier
- `turn_id`: per-turn identifier if available
- `traceparent`: OpenTelemetry parent context if available
- `agent_id`: Xibalba DID or equivalent bridged identity
- `intent_rationale`: the reason for the action
- `tool_name`: tool or command name
- `tool_input_hash`: stable digest of the tool input
- `tool_outcome`: `success` | `error` | `blocked` | `unknown`
- `token_usage`: numeric usage if available
- `assistant_response`: final text if available
- `timestamp`: event time in UTC
- `provenance`: source files, hook source, or wrapper source

## 3. Runtime-specific requirements

### 3.1 Claude Code
- [ ] Preserve existing hook-based session start and session end behavior.
- [ ] Preserve pre-tool gating for risky tools.
- [ ] Preserve post-tool outcome reporting.
- [ ] Persist and reload trace context within the same session.
- [ ] Ensure Claude events flow into the controller in the shared schema.

Pass criteria:
- pre-tool gating works
- post-tool telemetry is present
- session trace continues across tool calls
- memory reads and writes use the canonical controller

### 3.2 agy
- [ ] Keep the wrapper-based start/end lifecycle shim.
- [ ] Add session_id capture if the wrapper can access a stable session identifier.
- [ ] Add trace context persistence if a stable trace can be established.
- [ ] Add best-effort per-tool reporting only if the wrapper can intercept tool execution boundaries.
- [ ] If tool interception is impossible, explicitly mark agy as lifecycle-only and do not pretend tool parity.

Pass criteria:
- Xibalba identity is bound at start
- session end is reported
- telemetry is honest about missing tool hooks
- no fabricated parity claims

### 3.3 Codex
- [ ] Determine the actual Codex launch surface available in this environment.
- [ ] Add the lightest wrapper or shell adapter that can inject identity and session context.
- [ ] Normalize Codex tool results into the shared event schema.
- [ ] Verify whether Codex can support pre-tool or post-tool hooks; if not, treat it as adapter-limited.

Pass criteria:
- Codex can read shared memory
- Codex can emit normalized telemetry
- Codex uses the same Xibalba identity where intended
- missing hooks are documented as capability gaps

## 4. Hermes controller responsibilities

- [ ] Own the canonical memory API.
- [ ] Own the identity bridge and profile resolver.
- [ ] Own trace/session registration.
- [ ] Own the telemetry normalization endpoint.
- [ ] Own the policy evaluation interface.
- [ ] Own the retrieval and graph query surface.
- [ ] Expose these capabilities to all runtimes through Hermes Model Context Protocol and, where useful, local HTTP or GraphQL / REST interfaces.

## 5. Non-negotiable invariants

1. Storage and automation stay separated.
2. A runtime may never silently fabricate missing telemetry.
3. Missing hook support must be reported as a capability gap.
4. Memory writes must preserve provenance and revision history.
5. A shared identity does not imply shared enforcement capabilities.
6. A runtime with no hook system cannot be treated as Claude-equivalent.
7. Hermes Model Context Protocol is a transport and discovery layer, not the entire control plane.

## 6. Implementation sequence

### Phase 1: Canonical controller
- [ ] Define the shared event schema.
- [ ] Confirm identity resolution path.
- [ ] Expose memory read / write / search APIs.
- [ ] Add telemetry ingest endpoints.

### Phase 2: Claude parity
- [ ] Confirm Claude hook wiring.
- [ ] Confirm session trace continuity.
- [ ] Confirm pre-tool and post-tool reporting.
- [ ] Confirm controller ingest of Claude events.

### Phase 3: agy adapter
- [ ] Confirm wrapper entry and exit points.
- [ ] Capture the best available session metadata.
- [ ] Emit honest lifecycle telemetry.
- [ ] Document unsupported capabilities explicitly.

### Phase 4: Codex adapter
- [ ] Inspect actual Codex CLI integration surface.
- [ ] Implement wrapper or launcher adapter.
- [ ] Normalize telemetry and memory access.
- [ ] Document unsupported capabilities explicitly.

### Phase 5: Hardening
- [ ] Add failure-mode tests for missing hooks.
- [ ] Add tests for shared identity consistency.
- [ ] Add tests for trace propagation.
- [ ] Add tests for memory provenance and contradiction handling.
- [ ] Add tests that prove a runtime cannot silently claim parity.

## 7. Acceptance checklist

The architecture is acceptable only when all of the following are true:

- [ ] Claude, agy, and Codex all use the Xibalba identity where intended.
- [ ] All three runtimes can read and write through the canonical memory service.
- [ ] Claude has full lifecycle and tool-event parity.
- [ ] agy and Codex have honest, documented capability boundaries.
- [ ] The controller can reconstruct a single audit trail from all runtimes.
- [ ] Missing runtime capabilities are explicit, not hidden.
- [ ] Hermes Model Context Protocol is confirmed as the shared tool bus, not the sole solution.

## 8. Immediate next action

Implement the canonical controller first, then bring each runtime online one at a time. Do not attempt to declare full parity until the adapter-specific pass criteria are met for each runtime.
