---
title: Ingest Tokens
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: entity
tags: [identity, mcp, infrastructure]
confidence: high
source_files:
  - src/xibalba_cortex/ingest_tokens.py
  - src/xibalba_cortex/auth_middleware.py
---

## Table of contents

- [Overview](#overview)
- [Schema](#schema)
- [Hash-only storage, no recovery path](#hash-only-storage-no-recovery-path)
- [CLI](#cli)

## Overview

`src/xibalba_cortex/ingest_tokens.py` implements per-harness named bearer tokens for the
streamable-HTTP MCP transport (see [Generic Ingestion](../concepts/generic-ingestion.md)).
Tokens are stored in a **separate** SQLite file, `<home>/ingest_tokens.sqlite3` — deliberately
not a table inside the main `graph-memory.sqlite3` store. This is security-sensitive credential
state with a different lifecycle (issued/revoked by an operator, never touched by normal
memory-write traffic) than memory content: keeping it in its own file means a memory-store
backup/restore never accidentally carries live credentials along with it, and a credential
rotation never touches the memory schema or its migrations.

## Schema

```sql
CREATE TABLE IF NOT EXISTS ingest_tokens (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    revoked_at TEXT
);
```

A single shared-token deployment is just one row (e.g. `label="default"`) — there is no separate
"shared mode"; every deployment uses the same per-harness-named-token mechanism.

## Hash-only storage, no recovery path

Only a token's SHA-256 hash is ever stored. The raw token is generated with
`secrets.token_urlsafe(32)` (cryptographically random) and shown to the caller exactly once, at
issuance (`issue_token()`). There is no way to recover a lost raw token from this store —
issuing a new one and revoking the old is the only path, matching how real API-key systems
(GitHub, Stripe, etc.) work. This is a deliberate design choice, not a missing feature.

`verify_token()` compares hashes with `hmac.compare_digest` (constant-time), so response timing
can't be used to guess a valid hash byte-by-byte. `revoke_token()` revokes by `id`, not `label`
(labels aren't unique, ids are).

## CLI

```bash
uv run xibalba-cortex-ingest-tokens --home ~/.hermes/xibalba-cortex issue --label "perplexity-personal"
uv run xibalba-cortex-ingest-tokens --home ~/.hermes/xibalba-cortex list
uv run xibalba-cortex-ingest-tokens --home ~/.hermes/xibalba-cortex revoke --id <token-id>
```

`list` prints labels and timestamps only, never hashes — safe to print or log.

See [`BearerTokenAuth`](../concepts/generic-ingestion.md) for how a verified token gates a
streamable-HTTP request, and [Generic Ingestion](../concepts/generic-ingestion.md) for the
transport this credential system protects.
