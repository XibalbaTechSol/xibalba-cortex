# Perplexity integration: memory connection and hosted observer

Status: scoped, not implemented or live validated. Checked 2026-10-06 against
Cortex main `be224bf` and recorder foundation PR #39. This extends the existing
execution plan; it does not close a production or recorder gate.

## Product boundaries

| Surface | Connection | Scope of evidence | Availability |
|---|---|---|---|
| Perplexity conversations / Computer using Cortex | Custom remote MCP connector | Cortex memory reads/writes and calls received by Cortex; explicit turn submission if requested | Official changelog lists Pro, Max and Enterprise; organization policy may restrict custom connectors |
| Hosted Computer / Comet observer | Enterprise audit webhook | Provider-reported task/action/outcome events, not complete internal execution | Enterprise organization with 50+ seats or at least one Enterprise Max user |
| Perplexity Agent API application we operate | Instrument application's API stream and tool boundaries | Only runs created by that application | Separate future adapter; does not observe arbitrary consumer sessions |

An MCP connection does not automatically send each user prompt, final response or
unrelated tool call to Cortex. Agent-requested `memory_ingest_agent_turn` is an
explicit, potentially incomplete submission. Audit events are provider assertions,
not locally witnessed actions, execution authority or signed proof. Neither route
establishes complete tool input/output or token-by-token recording.

## Existing Cortex seams

- `src/xibalba_cortex/server.py`: Streamable HTTP MCP, profile-bound authentication,
  scoped memory tools and `memory_ingest_agent_turn(runtime=...)`. Perplexity can
  use a runtime label such as `perplexity-computer`; no new runtime allowlist is needed.
- `src/xibalba_cortex/auth_middleware.py` and `ingest_tokens.py`: static bearer
  credentials, scope checks, profile binding and rate limiting. Cortex does not
  implement an OAuth authorization server; use Perplexity's API-key option for the pilot.
- PR #39 `observer_capture.py`: bounded redaction, additive occurrence envelope,
  per-profile queue, worker and idempotent GraphStore OTel diagnostic persistence.
  It currently accepts Claude/Codex shapes, not Perplexity audit payloads. Its local
  worker is not a finished multi-tenant hosted receiver.
- Existing authenticated session OTel reads provide diagnostic access. Cursor API,
  live feed and timed playback UI remain separate shared recorder work.

## Work package 1: remote MCP canary

No new memory backend is required. Prepare a disposable profile, scoped credentials
and operator-controlled HTTPS endpoint terminating into Cortex's existing `/mcp`.
Do not expose a bare local development process to the internet. Verify what header
Perplexity's API-key setting actually sends; documentation does not pin that header
shape, so compatibility with Cortex's `Authorization: Bearer` remains a canary gate.
If incompatible, design an explicit auth adapter rather than disabling authentication.

In Perplexity Account settings → Connectors → Custom connector → Remote, use the
HTTPS MCP URL, Streamable HTTP and API Key authentication. Use a dedicated pilot
credential; read-only first, then a separate read/write canary credential.

Acceptance evidence:

1. Initialization and tool discovery succeed from the actual Perplexity account.
2. Write a synthetic unique memory marker and retrieve it in a fresh conversation.
   Verify the stored record and principal attribution in Cortex independently.
3. Read-only credentials cannot write; missing/revoked credentials fail; another
   profile cannot retrieve the marker, including guessed memory/session IDs.
4. If testing explicit turn ingestion, submit one synthetic turn and repeat its
   idempotency key; inspect deduplication. Do not equate submission with full capture.
5. Restart/reconnect and remove the connector; revoke credentials and confirm denial.

Record account tier, client surface/version, transport, header compatibility,
tool schemas, sanitized request IDs/results, and pass/fail. Never commit credentials
or actual account/user data. This canary requires an accessible pilot endpoint and
account; neither is established by this scope.

## Work package 2: audit webhook adapter

Implement a separate ASGI receiver, proposed `POST /integrations/perplexity/audit`,
plus an explicit Perplexity normalizer and integration tests. Route/profile binding
must come from a provisioned credential, never email, session ID or body metadata.
An organization-level credential must not expose every member's events to every
member: initially expose recordings only to the integration owner/admin. Design
member-level authorization before offering individual-user playback.

### Ingress and delivery

- Require HTTPS at the edge and a dedicated bearer credential with a narrowly scoped
  observer-ingest permission. Validate provisioning/revocation and deny memory access
  using that credential. Extend `ROLE_SCOPES` and its effective-scope tests explicitly; current roles
  grant memory/tool scopes, not an observer-only permission.
- Enforce streaming body bounds (initially 1 MiB), JSON object shape, UUID event ID,
  timezone-aware RFC3339 timestamp and bounded scalar identities. Rate-limit by
  authenticated integration. No credentials, email, IP, paths or raw body in logs.
- Validate and redact before durable enqueue. Return 202 only after local durable
  acceptance; duplicates with the same identity/content receive success. Reject
  conflicting contents under the same source event UUID visibly.
- Keep request handling short; Perplexity recommends response within one second.
  Measure enqueue response latency separately from persistence/live-feed latency.
- Return non-2xx for authentication/validation errors and unavailable/full queue;
  never ACK discarded supported events. Upstream retry guarantees, retention and
  replay are not documented sufficiently to promise recovery. Record these gaps,
  test observed retry behavior and provide an operator replay path with stable IDs.
- Persist asynchronously using a profile-aware worker and existing GraphStore
  diagnostic deduplication. Queue identity includes integration/profile + source UUID.
  Recovery after restart/lost ACK must preserve once-only persisted occurrences.

### First event allowlist and mapping

| Perplexity event | Recorder classification | Capture boundary |
|---|---|---|
| `query` | Submitted query | Optional allowlisted query text in redacted mode |
| `answer_generated` | Returned answer | Optional allowlisted answer/model fields; no token stream |
| `computer_task_started` | Task lifecycle start | Retain documented correlation when present |
| `computer_agent_action` | Provider-reported agent action | Action detail schema is not pinned; fixture discovery gate |
| `computer_task_completed` | Task lifecycle completion | No invented tool result or duration |
| `computer_task_error` | Task lifecycle error | Allowlisted bounded error only after payload validation |
| `comet_agent_action` | Provider-reported browser action | Separate surface label; not full browser recording |

Ignore unrelated membership/login/administrative events with a counted, successful
response after authentication and validation. Unknown types receive an unsupported
counter, not raw-body storage. Version the allowlist as provider schemas evolve.

Preserve original event type, UUID, source timestamp and receipt timestamp. Distinguish
`capture_surface=enterprise_audit_webhook` from local hooks. Provider `session_id` is
optional: when absent, store as an explicitly uncorrelated occurrence with a synthetic
integration-local bucket; never infer a real agent session, turn or tool identity.
Namespace source session IDs by provisioned integration to avoid collisions.

Default metadata-only policy drops email/IP/user-agent and arbitrary metadata.
Only approved bounded fields may enter redacted content capture. Redaction is
best-effort, not a compliance guarantee. Hashes do not restore omitted content.
Task/tool IDs and action metadata need sanitized real samples before claiming coverage.
New provider/source-correlation fields require an additive envelope spec update in
the same change; frozen receipt/exchange/hash contracts must remain unchanged.

### Validation matrix

| Area | Required checks |
|---|---|
| Authentication | Missing, invalid, revoked, wrong profile/scope; ingest credential cannot read memory |
| Input | Valid source UUID/time; malformed JSON, oversized streamed body, unsupported type, null session |
| Privacy | Secrets and PII omitted/redacted before queue/store; no raw payload in errors/logs |
| Delivery | Duplicate, conflicting UUID, restart, lost ACK, queue full, unavailable persistence, dead letter |
| Isolation | Same source UUID/session in two integrations; admin vs member access denial |
| Ordering | Out-of-order events remain visible with source/receipt times; no claimed total order |
| Latency | Receiver p50/p95 and enqueue-to-store lag under representative sustained load |
| Provider canary | Real task start/action/completion/error; observed headers, fields, retries and correlation |

Backend regression tests reuse real-server conventions in
`tests/test_streamable_http_auth_integration.py`, `test_auth_middleware.py`,
`test_ingest_agent_turn.py`, plus PR #39 observer recovery tests. Fixture tests prove
our adapter behavior; only real provider delivery proves account compatibility.

## Delivery order and gates

1. Remote MCP canary: validate memory utility and auth compatibility.
2. Receiver + normalizer + durable delivery: implement and regression-test locally.
3. Eligible Enterprise webhook canary: capture sanitized samples, validate action
   metadata, organization isolation, retry behavior and actual event latency.
4. Shared recorder cursor/live feed and UI: expose recorded occurrences with source
   labels, content-omission states and gaps, then add timed playback.

Memory support can ship independently of Enterprise observability. Pro/Max users
without audit access must not be sold full hosted-session recording. The webhook
receiver can be implemented before account access; hosted validation stays open.
No Perplexity connection or account change is performed by this document.

## Primary references and verification

Official pages checked 2026-10-06:

- [Adding Custom Remote Connectors](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors)
- [March 13 release: Bring Your Own Connector](https://www.perplexity.ai/changelog/what-we-shipped---march-13-2026)
- [Audit Logs: eligibility, schema, events and webhook delivery](https://www.perplexity.ai/help-center/en/articles/11652747-audit-logs)
- [Perplexity Computer MCP](https://docs.perplexity.ai/docs/getting-started/integrations/computer-mcp-server)
- [Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart)

The Computer MCP server exposes task calls and interactive/outcome responses; it
is not documented here as a passive subscription to all existing hosted sessions.
API-driven capture remains separate from consumer-session audit capture.

Scope validation: cross-checked the named Cortex code/test seams and official
connector/audit contracts; Markdown/diff checks pass. Existing HTTP authentication and generic-ingestion regression suites: **22 passed**
(`uv run pytest -o addopts='' -q tests/test_streamable_http_auth_integration.py
tests/test_auth_middleware.py tests/test_ingest_agent_turn.py`, 1.77 seconds).
No live account canary, webhook implementation, deployment or production SLA is claimed.
