# Gate 4 connector hardening drill

Run this drill on the operator PC before inviting a second machine. Record command
output and timestamps in an append-only evidence file; do not paste OAuth tokens or
bearer credentials into the evidence.

## 0. Baseline

```bash
cd /home/xibalba/Projects/xibalba-cortex
uv run pytest -q tests/test_connector_policy.py \
  tests/test_otlp_receiver.py tests/test_local_api.py
```

Expected: all focused connector/API tests pass. This proves policy wiring, not
external provider behavior.

## 1. Local-file connectors

Run each against a fresh tenant profile and a copied fixture directory:

```bash
uv run xibalba-cortex-tenant-onboard --root ~/.hermes/cortex-drill --tenant-id drill-files
uv run xibalba-cortex-transcript-ingest --home ~/.hermes/cortex-drill/drill-files \
  --file /path/to/fixture.jsonl
uv run xibalba-cortex-codex-mcp-backfill --home ~/.hermes/cortex-drill/drill-files --dry-run
uv run xibalba-cortex-wiki-ingest --home ~/.hermes/cortex-drill/drill-files \
  --wiki-dir /path/to/wiki
```

Repeat each command. Verify no duplicate memories, the expected file offset or
prompt-id checkpoint advances, and the profile database contains no records from a
different profile. These connectors have no outbound credential to custody; their
boundary is the explicit source path and profile home.

## 2. OTLP and webhook ingress

Start the local API/OTLP receiver bound to loopback with a token issued for the
target profile. Send one valid event, replay it with the same event id, send an
invalid token, and send a burst above the documented rate. Verify:

- valid events are stored under the target profile;
- replay is idempotent;
- invalid or cross-profile credentials are rejected;
- the rate limiter prevents unbounded request throughput without dropping valid
  events silently.

Use the response status and `/metrics` counters as evidence. Never record the raw
token.

## 3. Gate decision

Gate 4 closes only when the six implemented connectors have a dated drill result:
local-file boundary/idempotency evidence for the four local connectors and real
authenticated ingress evidence for OTLP/webhook. Synthetic tests must remain labeled
`local` or `synthetic`; they cannot be promoted to external-traffic proof.
