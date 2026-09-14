---
title: Runtime Adapter Research and Telemetry Contract
type: concept
tags: [telemetry, adapters, claude, codex, antigravity]
confidence: high
source_files:
  - src/xibalba_cortex/claude_adapter.py
  - src/xibalba_cortex/codex_probe.py
  - src/xibalba_cortex/codex_mcp_backfill.py
  - src/xibalba_cortex/agy_adapter.py
---

# Runtime adapter research

This page records the evidence boundary for the three adapters. A shared event schema does not
turn a wrapper into a native hook integration: every adapter reports the strongest surface that
has actually been observed.

## Claude Code

Claude Code's official hook reference documents JSON hook input over stdin and a broad lifecycle:
session start/end, per-turn prompt/stop events, per-tool `PreToolUse` and `PostToolUse`, failures,
permissions, subagents, compaction, model switching, and filesystem/configuration notifications.
The adapter should therefore use command or HTTP hooks for live capture, with `PreToolUse` as the
policy boundary and post/failure events as outcome telemetry. It should not infer model-request
timing from tool hooks.

Source: https://code.claude.com/docs/en/hooks

## Codex

The strongest documented live surface is Codex app-server's bidirectional JSON-RPC protocol over
stdio, WebSocket, or Unix socket. It emits `turn/started`, `turn/completed`, per-item lifecycle
events and deltas, and `thread/tokenUsage/updated`. A launcher-only adapter cannot see these
events, so it remains process-level unless it owns an app-server connection.

Codex also persists rollout JSONL under `CODEX_HOME/sessions/YYYY/MM/DD`. The existing
`codex_mcp_backfill` parser is the durable fallback: it extracts session metadata, prompts,
assistant messages, tool calls/results, and token events. Rollout tracing is explicitly local and
may contain sensitive prompts, tool inputs/results, terminal output, and paths; it must never be
treated as automatically shareable telemetry.

Sources:

- https://github.com/openai/codex/tree/main/codex-rs/app-server
- https://github.com/openai/codex/tree/main/codex-rs/rollout-trace
- https://learn.chatgpt.com/docs/config-file/config-advanced

## Antigravity / agy

The official Antigravity SDK describes a Python `Agent` runtime with session management, tool
execution, safety policies, subagent delegation, streaming, persistence, and lifecycle/hooks.
The current Cortex `AgyWrapperShim` is not an in-process SDK adapter, however; it only observes
wrapper entry/exit and explicitly forwarded facts. Until the SDK package and callback signatures
are pinned and exercised locally, the adapter must not claim native per-tool or model telemetry.

Source: https://www.agy.dev/docs/sdk/overview/

## Normalized implementation boundary

All three adapters use `RuntimeEvent` fields for `runtime`, session/turn/invocation correlation,
tool outcome, token usage, assistant response, provenance, and metadata. Payload-heavy metadata is
bounded or hashed when sent to external Integrity reporting. Local Cortex capture may retain the
configured verbatim tier, subject to its retention policy. Policy enforcement is only claimed for
Claude's verified pre-tool path; Codex app-server and Antigravity SDK policy hooks require separate
live validation before being enabled.

| Runtime | Live adapter now | Durable fallback | Honest gap |
|---|---|---|---|
| Claude | Native hook-shaped adapter, including pre/post tool and lifecycle events | Hook watermark | Hook configuration/deployment must be validated in each Claude surface |
| Codex | Launcher/process telemetry | Rollout JSONL parser and MCP backfill | App-server event subscription is not yet owned by this adapter |
| agy | Wrapper start/end and explicit observations | SDK persistence when exposed by caller | No in-process SDK callback registration yet |
