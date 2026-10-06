# Perplexity integration: API runtime, memory and recorder plan

Status: scoped, not implemented or live validated. Checked 2026-10-06 against
Cortex main `be224bf` and recorder foundation PR #39. This extends the existing
execution plan; it does not close a production or recorder gate.

## Product boundaries

| Surface | Connection | Scope of evidence | Availability |
|---|---|---|---|
| Perplexity conversations / Computer using Cortex | Custom remote MCP connector | Cortex memory reads/writes and calls received by Cortex; explicit turn submission if requested | Official changelog lists Pro, Max and Enterprise; organization policy may restrict custom connectors |
| Hosted Computer / Comet observer | Enterprise audit webhook | Provider-reported task/action/outcome events, not complete internal execution | Enterprise organization with 50+ seats or at least one Enterprise Max user |
| Perplexity Agent API application we operate | Instrument application's API stream and tool boundaries | Prompts, exposed stream/tool records and outcomes from runs created by Cortex | Primary delivery; requires API access and usage billing, not Enterprise audit eligibility |

An MCP connection does not automatically send each user prompt, final response or
unrelated tool call to Cortex. Agent-requested `memory_ingest_agent_turn` is an
explicit, potentially incomplete submission. Audit events are provider assertions,
not locally witnessed actions, execution authority or signed proof. Consumer MCP and audit routes do not establish complete tool input/output or
token-by-token recording. The API adapter captures exposed output chunks for runs
we initiate; it does not reveal hidden provider execution.

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

## Primary delivery: Perplexity Agent API runtime and recorder

The initial customer experience is a Perplexity-powered workflow launched inside
Cortex. The user supplies a server-side Perplexity API credential, selects a Cortex
profile/project and capture policy, submits a task, watches exposed events arrive,
and later replays the recording. This is separate from attaching Cortex to an
already-running conversation in Perplexity's consumer application.

Use the native Perplexity SDK or a small documented HTTP/SSE adapter pinned to a
verified version. Do not treat OpenAI wire compatibility as identical event semantics.
Keep transport behind an interface so fixture tests do not require credentials.

### Proposed components and contracts

| Component | Responsibility | Existing seam / implementation target |
|---|---|---|
| Runtime adapter | Submit, stream, reconnect, retrieve final snapshot, cancel | New `perplexity_runtime.py`; owns API credentials and provider transport |
| Run controller | Authenticate, bind profile/project, retrieve context, enforce budgets and drive lifecycle | New controller/service; integrates GraphStore context assembly |
| Event normalizer | Allowlisted exposed events → additive recorder envelope | Extend PR #39 capture foundation; provider-specific normalizer |
| Durable capture worker | Queue normalized events, retry storage, advance durable cursor | Existing outbox + GraphStore diagnostics; add provider resume checkpoint |
| Recorder feed | Authorized snapshot plus incremental cursor reads | Shared recorder API; scoped event projection, not raw provider response dump |
| Timeline viewer | Live events, tool details, gaps, pause, seek and timed playback | Existing viewer integration; uses durable recorder feed |
| Memory retention | Finalize exchange once; propose/save useful memories under policy | Existing turn ingestion/context tools; separate from diagnostic recording |

The controller performs context retrieval before the request, so initial recall is
application-controlled. Bound retrieved context by a configured token/size budget,
record memory references/retrieval trace IDs and do not mix tenant contexts. Retain
new memories only under an explicit policy: initial pilot records exchanges and
supports user-directed saving; automatic extraction must use existing inference/
proposal gates rather than silently launching a new uncontrolled write path.

### Tool connection strategy

For the first recorder canary, avoid mandatory remote-MCP deployment: retrieve
memory through the authenticated Cortex service locally, inject bounded context,
and use a harmless built-in search or synthetic custom function. This verifies the
API run/recorder independently of public endpoint discovery.

For agent-directed memory access, add direct `type=mcp`, Streamable HTTP, raw-token
`authorization` and an explicit tool allowlist. Credentials are profile/principal
bound and stored server-side, not in browser code or recording payloads. Do not
reuse an organization-wide memory credential across end users. Saved API Console
connectors (`type=connector`, `id`) are a separate optional configuration path;
any key in that Perplexity Project can use them. They require a tenant-isolation
review and canary before use in a multi-user Cortex deployment.

Perplexity currently documents automatic MCP tool execution and ignored
`require_approval`. Restrict the pilot to scoped memory reads and deliberate writes;
do not expose delete/admin/anchoring actions. If a future external action needs
human approval, implement a client-executed custom function and persist an explicit
approval state before execution. Computer MCP's interactive approvals are a different
contract and must not be assumed for Agent API MCP tools.

### Run identity, streaming and recovery

- Cortex creates a profile-bound session/run ID before the provider request. Track
  provider response ID, output-item ID, function call ID, attempt and source sequence
  independently. Do not use the provider response ID as an authorization boundary.
- Persist the submitted prompt/context policy before calling the provider. Record
  `submitting`, then map observed provider states into `running`, `waiting_for_tool`,
  `cancelling`, `completed`, `cancelled`, `failed` or `incomplete`. This is an additive
  run registry design, not a mutation of frozen memory/exchange schemas.
- Store credential references, model/preset/profile version, capture policy and
  provider IDs in the registry; no raw secrets. Pin immutable profile versions where
  profiles are used. A create timeout may leave the provider run outcome unknown:
  mark that ambiguity and do not blindly create another charged run. Provider request
  idempotency must be verified before using automatic submission retries.
- Normalize exposed lifecycle/text/output/tool events only; exclude raw reasoning.
  Use documented Perplexity events plus sanitized canary fixtures, never infer the
  full OpenAI event catalog. Tool arguments may arrive complete inside an item or
  incrementally; test both. Final MCP output items include name/arguments/output/error,
  but the timing of live tool detail visibility needs a real streaming canary.
- For background streams, checkpoint provider response ID and `sequence_number`.
  Durable occurrence identity is integration + response + sequence when supplied;
  final snapshot reconciliation uses provider item identity and an explicit snapshot
  classification. Do not globally deduplicate identical text chunks.
- Advance the reconnect cursor only after durable queue acceptance. Restart recovers
  that cursor and retries queued persistence; a lost ACK must not double-insert.
  When no source sequence exists, label receipt ordering and weaker replay coverage.
- Resume with `GET /v1/agent/{id}?stream=true&starting_after=N`. When the reconnect
  window expires (`400`), retrieve a final snapshot and persist a visible gap.
  A snapshot repairs final state, not missing source timing or deltas.
- Cancel via the provider endpoint. `cancelling` is not terminal: poll/stream until
  `cancelled` or another terminal outcome. Tool/model costs already incurred remain.
- Additive registry/checkpoint fields and recorder-envelope changes must be specified
  with migration/compatibility notes in the same implementation PR. Reuse existing
  deduplication boundaries; preserve frozen memory/exchange/receipt/hash contracts.

### Recorder contract and UI

Proposed session-scoped `GET /api/session/{id}/observer-events` returns a bounded
page with an opaque server cursor, event IDs, source/receipt times and capture state.
Define cursors against a stable persisted ordering and bind them to session/profile;
reject cross-session cursors. Initial delivery can use short polling. SSE/live push
is an optimization after reconnect, authorization and load tests pass.

The viewer must support initial snapshot + incremental catch-up, pause display
while ingestion continues, seek, playback speed and live-edge resume. Group tools
by actual call/item correlation; show source/receipt ordering and gaps. Use content
states from PR #39, including policy/size omission. Metadata-only recordings cannot
replay omitted message text. Existing 6,000-byte content bounds require chunk-size
validation; do not silently truncate or split source events while preserving a false
single-event identity. Do not label gaps as measured producer loss when the provider
does not expose a sequence or completeness guarantee.

Recorder errors must be visible. At minimum expose queued/persisted/dead-letter
counts, unsupported event counts, ingestion lag, reconnect state and known gaps.
Use tenant-scoped metrics and fixed/redacted failure codes. Viewer reconnection must
recover persisted events without replaying model/tool execution. Replay is a viewing
operation, not a re-run.

### Implementation milestones

Effort is a preliminary engineering estimate for one contributor, not a delivery
commitment. Account access, review, deployment and representative burn-in are separate.

| Milestone | Deliverable | Exit criterion | Estimate |
|---|---|---|---|
| P0: contract canary | Pinned SDK/model fixtures; synthetic Agent API run and local memory seam | Exposed event shapes, sequence/reconnect, auth and billing errors observed; unsupported fields documented | 1–2 days |
| P1: runtime and durable capture | Controller, registry/checkpoint, normalizer, worker and CLI/developer entry point | Stream, restart, duplicate/conflict, timeout ambiguity, cancellation and expired-window tests pass | 3–5 days |
| P2: feed and replay | Session cursor endpoint and live/timed timeline UI | Cross-tenant denial, catch-up, pause/seek/speed, gaps and omissions tested in real UI | 3–5 days |
| P3: memory and consumer onboarding | Bounded pre-run recall, explicit saving, remote MCP instructions and connection doctor | Cross-session synthetic memory canary passes; actual received tool calls prove consumer connector works | 2–3 days |
| P4: deployment pilot | Credential provisioning, retention, budgets, worker supervision and operations runbook | Sustained-load/restart drill, measured latency and one repeatable customer pilot | 2–4 days |
| P5: Enterprise observer | Existing audit-webhook work package and eligible account canary | Real Computer/Comet payload coverage and organization access isolation verified | 2–4 days plus access |

Core API experience P0–P4 totals approximately **11–19 engineering days**, subject to
P0 discoveries and reuse of shared recorder work. P5 is independently gated. Local
Claude/Codex canaries remain gates for their own supported surfaces; Perplexity API
canary does not certify those harnesses. PR #39 foundations need review/integration,
not an implicit merge or production-readiness claim.

### Acceptance tests and measured targets

| Scenario | Required evidence |
|---|---|
| Memory continuity | Synthetic fact saved under one session is retrieved in a new run under the same permitted identity; another identity cannot read it |
| Live capture | Submitted prompt, text chunks, available tool records, terminal state and usage visible without raw reasoning or credentials |
| Recovery | Disconnect/restart + cursor resume; duplicate delivery; conflicting IDs; queue full; unavailable store; expired window with final snapshot and explicit gap |
| Provider failures | 401/429/5xx; discovery failure; tool-error item while run succeeds; incomplete output; create timeout with unknown outcome |
| Cancellation/tools | Asynchronous cancellation outcome; complete-vs-delta arguments; custom function call/result pairing; no execution on playback |
| Authorization | Wrong profile/session/cursor, revoked credentials, consumer/API connector scopes and saved-connector project isolation |
| Content/retention | Metadata mode omission; redacted content; oversized chunks; secrets absent from queue/store/logs; retention for run registry, queue and recordings |
| UI | Live edge, initial history/catch-up, pause/seek/speed, reconnect, missing content and gaps tested in browser |
| Cost and limits | Configured max steps, output limit, concurrency and spend budget; record available provider usage without claiming complete invoice cost |

Proposed pilot performance targets: receiver acceptance within 1 second where used,
and Cortex event receipt to visible UI p95 within 2 seconds under declared test load.
These are targets to measure, not provider event-latency guarantees or current SLAs.
P0/P4 must define concurrency, duration, event size and hardware before accepting them.

## Documentation and forum findings affecting scope

Primary API docs establish Streamable HTTP MCP, exposed text streams, background
sequence cursors and custom-function call/result correlation. Direct MCP discovery
failure can abort a request with HTTP 424; tool failures can coexist with a successful
final response, so classify memory availability independently of model completion.

The dedicated connector docs describe `type=connector` with an `id`, while the MCP
limitations table still describes unsupported OpenAI-style `connector_id`/catalog
behavior. Treat these as separate request forms; validate the dedicated connector
contract explicitly rather than extrapolating compatibility.

Forum reports are historical user observations, not current supported API contracts:

- July–September consumer connector selection/dispatch regressions: connection doctor
  must verify a real Cortex tool call, not a UI checkmark.
- May–June OAuth dynamic-client-registration secret failures: test OAuth against the
  actual Perplexity client; preserve API-key pilot path. Do not invent nonstandard
  secrets to bypass public-client behavior.
- April Agent API argument-stream parser incompatibility, followed by a reported
  upstream fix: support complete item arguments and pin parser fixtures/version.
- April requests for a Computer API are older than the current official Computer MCP
  docs; use current documented capabilities, not absence inferred from old requests.

## Optional Computer MCP adapter

Defer until the primary recorder pilot passes. A Cortex-owned MCP client can connect
through Perplexity OAuth, launch/continue tasks and capture returned outcomes plus
interactive question/approval/auth events. Keep approval decisions user-controlled.
No documented full internal live-event subscription is established here. This adapter
uses Perplexity account credits and its own auth lifecycle; do not conflate it with
Agent API credentials or Enterprise audit credentials.

## Consumer delivery: remote MCP canary

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

## Enterprise delivery: audit webhook adapter

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

## Delivery order and release gates

Use P0–P4 above for the API runtime and recorder pilot; ship the consumer memory
connector independently when its live canary passes. P5 audit ingestion follows when
eligible organization access is available. Optional Computer MCP remains separate.

A local fixture test earns adapter validation only. A paid API synthetic run earns
API compatibility evidence, not arbitrary consumer-session coverage. Pro/Max memory
users without audit access must not be sold full hosted-session recording.
No Perplexity account connection, API spend, deployment or merge is performed by this plan.

## Primary references and verification

Official pages checked 2026-10-06:

- [Adding Custom Remote Connectors](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors)
- [March 13 release: Bring Your Own Connector](https://www.perplexity.ai/changelog/what-we-shipped---march-13-2026)
- [Audit Logs: eligibility, schema, events and webhook delivery](https://www.perplexity.ai/help-center/en/articles/11652747-audit-logs)
- [Perplexity Computer MCP](https://docs.perplexity.ai/docs/getting-started/integrations/computer-mcp-server)
- [Agent API](https://docs.perplexity.ai/docs/agent-api/quickstart)
- [Remote MCP API contract](https://docs.perplexity.ai/docs/agent-api/tools/mcp)
- [Saved API Project connectors](https://docs.perplexity.ai/docs/agent-api/tools/connectors)
- [Output streaming](https://docs.perplexity.ai/docs/agent-api/output-control)
- [Background/reconnect/cancellation](https://docs.perplexity.ai/docs/agent-api/background-mode)
- [Conversation continuation](https://docs.perplexity.ai/docs/agent-api/conversation-state)
- [Custom function loop](https://docs.perplexity.ai/docs/agent-api/tools/custom-functions)
- [Immutable profile versions](https://docs.perplexity.ai/docs/agent-api/profiles)

Forum observations reviewed separately from primary API contracts:

- [Consumer connector dispatch reports](https://community.perplexity.ai/t/connector-stays-checked-in-the-dropdown-but-is-never-attached-to-the-composer-tool-never-dispatches-fresh-sessions-any-machine/5525)
- [OAuth public-client registration reports](https://community.perplexity.ai/t/custom-mcp-connector-fails-with-did-not-return-a-client-secret-for-rfc-7591-compliant-public-client-registrations/5172)
- [Argument-stream parser report and reported fix](https://community.perplexity.ai/t/does-anyone-try-to-use-perplexity-api-on-openclaw-couldnt-do-it/4760)
- [Historical Computer API request](https://community.perplexity.ai/t/feature-request-computer-api-availability-on-the-perplexity-api-platform/4746)

The Computer MCP server exposes task calls and interactive/outcome responses; it
is not documented here as a passive subscription to all existing hosted sessions.
API-driven capture remains separate from consumer-session audit capture.

Scope validation: cross-checked the named Cortex code/test seams and official
connector/audit contracts; Markdown/diff checks pass. Existing HTTP authentication and generic-ingestion regression suites: **22 passed**
(`uv run pytest -o addopts='' -q tests/test_streamable_http_auth_integration.py
tests/test_auth_middleware.py tests/test_ingest_agent_turn.py`, 1.77 seconds).
No live account canary, webhook implementation, deployment or production SLA is claimed.
