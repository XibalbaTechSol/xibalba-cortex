---
title: Redaction
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [provenance, compliance]
confidence: high
source_files:
  - src/xibalba_cortex/redaction.py
---

## Table of contents

- [Overview](#overview)
- [What it matches](#what-it-matches)
- [Recursion](#recursion)

## Overview

`src/xibalba_cortex/redaction.py` provides `redact()`, the shared secret-scrubbing logic used by
every ingestion path that captures externally-sourced content: `transcript_ingest.py`,
`session_sync.py`, and [`memory_ingest_agent_turn`](generic-ingestion.md). It was extracted this
session from what used to be near-identical duplicated logic in the first two — a fix to the
pattern set now only needs to happen in one place, and any new ingestion path (which by
definition sees less-trusted content than a local transcript file) gets the same scrubbing by
default rather than by copy-paste.

## What it matches

Five regex patterns, applied independently over the same string (order doesn't matter since
none depend on another's output):

```python
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret|password|token|private[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b"), "[REDACTED]"),
)
```

That covers: bearer tokens, `api_key=`/`api-key:` values, `secret`/`password`/`token`/
`private_key` key=value pairs, `sk-...`-style API keys (OpenAI/Anthropic-style), and bare
64-hex-character strings (a common shape for raw secrets and private keys).

## Recursion

`redact()` recurses over `str`/`list`/`dict` values — a string has the patterns applied
directly; a list has `redact()` mapped over its items; a dict has `redact()` applied to every
value (keys are coerced to `str` but not redacted). Any other type passes through unchanged.
This is a best-effort regex scrub, not a guarantee of complete secret removal — it does not
replace not putting secrets in agent transcripts in the first place.

See [Generic Ingestion](generic-ingestion.md) for the ingestion path that made this extraction
necessary, and [Graph Store](graph-store.md) for where redacted content ultimately lands.
