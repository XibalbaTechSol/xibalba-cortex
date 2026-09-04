# Connector hardening policy

This is the Gate 4 control document. It defines the minimum policy for each
connector reported as `implemented`; it does not claim external deployment proof.

## Shared controls

`src/xibalba_cortex/connector_policy.py` provides:

- bounded exponential retry (three attempts by default) for transport failures and
  HTTP 429/5xx responses; authentication and validation failures are not retried;
- a thread-safe token bucket per connector process/profile;
- profile-path confinement for credentials.

The default limits are intentionally conservative and local: Drive outbound calls
use 2 requests/second with a burst of 2; authenticated local API/webhook ingress
and OTLP ingress use 20 requests/second with a burst of 40. Deployments may wrap
these primitives with a stricter reverse-proxy limit, but must not remove them.

## Connector matrix

| Connector | Transport | Credential boundary | Retry/throttle status |
|---|---|---|---|
| `claude_transcripts` | local append-only JSONL | no connector credential; reads only configured transcript path | SQLite writes use the store's busy timeout; incremental offsets and idempotency make re-runs safe |
| `codex_mcp` | local Codex session JSONL/MCP | no connector credential; uses the configured Cortex profile | idempotent prompt IDs; store busy timeout protects concurrent writes |
| `hermes_sessions` | local Hermes state DB | no connector credential; configured profile only | deterministic message IDs; repeated finalization is safe |
| `integrity_wiki` | local wiki files | no connector credential; explicit wiki directory | deterministic locator/idempotency; changed pages supersede rather than duplicate |
| `otel` | authenticated/local HTTP ingress | bearer token is verified against the target profile; no shared tenant secret | 20 requests/second, burst 40; malformed/auth failures are rejected without retry |
| `webhook` | authenticated MCP/local API ingress | bearer token is profile-bound and scope-checked | 20 requests/second, burst 40; event IDs make retries idempotent |
| `google_drive` | outbound Google APIs | default OAuth file is `<profile-home>/credentials/google_token.json`; cross-profile paths are rejected for the default path | 2 requests/second, burst 2; bounded retry on transport and 429/5xx |

## Evidence and remaining work

The shared policy and Drive/OTLP/local-API wiring are covered by
`tests/test_connector_policy.py`, `tests/test_drive_ingest.py`,
`tests/test_otlp_receiver.py`, and `tests/test_local_api.py`. Gate 4 remains open
until each connector has an end-to-end credential-custody and retry/throttle drill
against its real transport. Local-file connectors cannot substitute for real
external connector traffic; their evidence proves only profile/path boundaries and
idempotent recovery.
