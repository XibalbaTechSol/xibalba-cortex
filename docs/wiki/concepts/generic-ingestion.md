---
title: Generic Ingestion
acronyms: [MCP]
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [mcp, infrastructure, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/server.py
  - src/xibalba_cortex/auth_middleware.py
  - src/xibalba_cortex/ingest_tokens.py
  - README.md
---

## Table of contents

- [Overview](#overview)
- [memoryingestagentturn](#memoryingestagentturn)
- [Transport: streamable-HTTP](#transport-streamable-http)
- [Auth: per-harness bearer tokens](#auth-per-harness-bearer-tokens)
- [Concrete example targets (researched this session)](#concrete-example-targets-researched-this-session)

## Overview

Every other ingestion path in Cortex (transcript files, Hermes hook subprocess dispatch,
localhost-only OTLP/API servers) assumes a caller on the same machine. Generic ingestion is the
network-reachable path added for any agent harness — local or cloud-hosted — that can't spawn a
local subprocess or read local files, built this session.

## `memory_ingest_agent_turn`

One MCP call captures a complete turn: prompt, response, every tool call, and metadata, instead
of orchestrating `memory_session_start` + `memory_record_model_exchange` +
`memory_record_otel_batch` yourself. Signature (from `server.py`):

```python
memory_ingest_agent_turn(
    external_session_id: str,
    runtime: str,
    prompt: str,
    response: str,
    tool_calls: list[dict] | None = None,
    agent_id: str | None = None,
    prompt_id: str | None = None,
    prompt_time: str | None = None,
    response_time: str | None = None,
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> dict
```

`runtime` is a free string — there is no fixed harness allowlist, so a brand-new harness name
works with zero code changes (contrast with the three officially-adapted runtimes in
[Runtime Adapters](runtime-adapters.md), which get richer identity/policy handling but are not
the only path in). Each `tool_calls` entry is recorded as a real `otel_event` **and** committed
into the resulting exchange's Merkle node, so tool-call identity is tamper-evident too, not just
prompt/response content — see [Hash Chain and Merkle Roots](hash-chain-and-merkle-roots.md).
All string content is passed through [`redact()`](redaction.md) before storage.

## Transport: streamable-HTTP

The server supports `--transport streamable-http` in addition to the stdio default. It binds to
`127.0.0.1` by default even in HTTP mode, and it has no TLS of its own: real remote reachability
requires a TLS-terminating reverse proxy or tunnel (Caddy, nginx, Cloudflare Tunnel, ngrok, …)
in front of it. Binding a non-loopback `--host` prints a loud warning at startup rather than
silently accepting it (`server.py`'s `main()`).

## Auth: per-harness bearer tokens

Every HTTP request needs `Authorization: Bearer <token>`. `auth_middleware.BearerTokenAuth` is a
raw ASGI middleware (not the `mcp` SDK's OAuth-shaped `TokenVerifier`, and not Starlette's
`BaseHTTPMiddleware`, which would buffer the whole response and break the transport's real SSE
streaming) that rejects any `http` scope with a missing, malformed, or revoked/unknown token
before it reaches the wrapped app. Tokens are issued and stored per harness via
`ingest_tokens.py` — see [Ingest Tokens](../entities/ingest-tokens.md) for the full token
lifecycle.

## Concrete example targets (researched this session)

- **Google Antigravity CLI** supports a `serverUrl` field for remote MCP servers in
  `~/.gemini/config/mcp_config.json`, plus a `headers` map for the bearer token.
- **Perplexity** (Pro/Max/Enterprise) supports adding a custom remote MCP connector for
  Computer/Comet workflows via a server URL plus an API key, configured in Perplexity's own
  connector settings.

Both are cited as concretely researched integration targets, not as tested-in-this-repo
integrations — no automated test in this repo exercises either product directly.

See [MCP Tool Surface](mcp-tool-surface.md) for the rest of the tool surface, and
[Compliance Evidence Trail](../queries/compliance-evidence-trail.md) for how a cloud-sourced
turn gets the same auditability guarantees as a local one.
