# Gemini Spark integration: memory connection and Gemini API recorder

Status: plan and scope only, 2026-10-06. Based on Cortex main `be224bf`, observer
foundation PR #39 and shared recorder planning in PR #40. No runtime, OAuth gateway,
live account connection, deployment or paid API call is delivered by this document.
This extends the existing execution plan; it does not establish a separate ledger.

## Product boundary and recommended delivery

| Surface | Supported integration direction | Cortex evidence | Scope |
|---|---|---|---|
| Hosted Gemini Spark / Gemini Apps | Custom Connected App pointing to Cortex MCP | Calls received by Cortex and explicitly submitted context | Primary Spark memory integration; actual OAuth/account canary required |
| Gemini workflows launched inside Cortex | Gemini Interactions API + application-controlled memory/tool boundaries | Submitted prompts, exposed steps/text/tool results, outcomes and usage | Primary Gemini recorder pilot; this is not the hosted Spark service |
| Existing arbitrary Spark tasks | No complete event feed identified in official pages reviewed | At most Cortex-facing calls | Discovery gate; do not promise passive or complete recording |
| Gemini CLI / Antigravity / Gemini Enterprise | Different products and client contracts | Depends on their own adapter | Out of this Spark plan; do not equate CLI hooks or cloud audit logs with Spark events |

Google's current help documents custom apps through Settings → Connected Apps →
Custom apps → MCP URL. It lists personal Google accounts, age 18+, US, English and
Keep Activity on for this custom-app feature; Spark help separately lists Google AI
Pro/Ultra. Eligibility differs by feature and changes with rollout. Verify the actual
pilot account before promising support, including web/mobile availability. Installing
custom apps is documented in the web app; use `@` to explicitly select the app.

Consumer MCP usage is model-directed memory use, not deterministic capture of each
prompt/action. The API controller can guarantee its own pre-run recall and instrument
client-executed tools, but does not reveal hidden Google internals. Do not advertise
API recordings as recordings of consumer Spark sessions.

## Research findings and unresolved gates

- Google help exposes a custom-app flow with Dynamic Client Registration (DCR), or
  advanced credentials if DCR is unavailable. It does not establish that Cortex's
  static bearer-only auth can be pasted directly into this consumer flow. Build and
  test standards-based OAuth authorization for hosted Spark; verify advanced-field
  semantics rather than assuming they accept a raw Cortex API token.
- Cortex's `auth_middleware.py` explicitly implements static bearer auth, not OAuth
  discovery/authorization/token issuance. Existing profile/scoped tools can be reused,
  but hosted consumer authorization is real new work.
- Gemini Interactions API is documented as the recommended interface with stored
  interaction history, observable steps and background execution. The SDK's
  `interactions.create/get/cancel` provide an application-owned runtime path.
- Remote MCP in Interactions supports `type=mcp_server`, Streamable HTTP, `headers`
  and `allowed_tools`. Server names must avoid hyphens; use `cortex_memory`.
  API MCP auth headers and consumer Connected-App OAuth are separate contracts.
- Background stream reconnection uses interaction ID and `last_event_id`; retain
  observed event IDs as opaque values, not Perplexity's numeric sequence cursors.
- `store=false` prevents background execution and `previous_interaction_id` continuity.
  The API's documented retention is 1 day free / 55 days paid, with configurable paid
  windows. Provider retention and Cortex recording retention need separate policies.
- No public full Spark task subscription/audit webhook was identified in the reviewed
  Spark help and API pages. This is a research boundary, not proof no private/partner
  interface exists. Confirm with Google before planning that dependency.

Forum findings are reported observations, not API guarantees:

- August 6 and October 2 reports describe consumer MCP OAuth reaching Google's redirect
  relay without a subsequent token exchange. October 2 included a qualifying Pro account
  and logs from multiple browsers. Reproduce/measure discovery, authorization, token
  exchange and the first actual tool call separately; never mark success after redirect.
- An October 5 reply in the vendor-onboarding thread reports another server working
  as a Spark custom app with OAuth/DCR. Results appear integration-dependent; do not
  claim a universal OAuth outage or universally working connection.
- Vendor requests for curated Connected-App listing do not establish a public partner
  acceptance program. Custom apps are the pilot route; official catalog listing is
  optional business-development work.
- A memory vendor's Spark guide mixes Antigravity configuration files/manifests with
  consumer Spark. Use Google's Connected-App UI as authority for consumer setup;
  do not ship `antigravity.yaml` or CLI config changes as a Spark installation method.

## Workstream A: Spark consumer memory

### Customer experience

1. Cortex provisions a profile/project and displays its hosted HTTPS MCP URL.
2. User adds that URL in Gemini web Connected Apps and signs into Cortex through
   OAuth consent; read-only first, scoped write consent when deliberately enabled.
3. User selects `@Cortex` and asks it to remember a synthetic project fact.
4. In a new Spark task, user selects Cortex and asks for that fact. Connection doctor
   verifies the actual scoped tool calls and persisted/retrieved marker.
5. User can disconnect in Gemini and revoke Cortex's grant. Recording/history deletion
   follows separate retention policy; disconnect is not data erasure.

Provide concise instructions for recall before task execution and saving useful facts
or decisions afterward. Label these as requested tool behavior, not guaranteed hooks.
MCP call telemetry records only Cortex-bound operations and their actual results.

### Authorization design

Use a maintained OAuth authorization implementation/provider and an MCP-aware resource
server. Specify the supported MCP authorization revision explicitly and canary Google's
client against it. Do not invent a partial OAuth server inside existing bearer middleware.
Implement protected-resource metadata, authorization-server discovery, authorization
code + PKCE, client registration or documented pre-registered-client setup, consent,
refresh/revocation, resource/audience binding and exact redirect URI validation.
Do not wildcard every `googleusercontent.com` redirect or copy one forum user's callback.

Bind access-token subject/grant to Cortex identity, permitted profile/project and scopes.
Enforce authorization on every memory/tool call and cursor read; a Google account email
or user-provided agent ID must not select a tenant. Existing memory scopes remain the
resource permission vocabulary. Keep authorization codes, refresh tokens and callback
query strings out of diagnostics/recordings. Hosted OAuth must coexist with local
stdio and existing API-key clients without silently broadening access.

Scope changes:

| Component | Deliverable |
|---|---|
| OAuth service / resource integration | Auth discovery, consent, tokens, revocation, subject/profile binding |
| Hosted MCP resource | Existing Cortex tools over HTTPS with OAuth verification and explicit scope checks |
| Provisioning/onboarding | User-owned endpoint/grant setup; connection doctor; removal/revocation guidance |
| Memory tool policy | Small scoped recall/save surface; no admin/delete/anchor tools exposed in pilot |
| Operations | Expired token/refresh diagnostics, fixed failure codes, rate limits and health checks |

Live Spark canary exit: discovery → authorize → token exchange → real tool call →
new-task recall → revocation denial. Verify write scope and cross-profile denial. If
Google's client stops at redirect, preserve redacted evidence and mark the pilot blocked;
do not disable auth or claim connection solely from another MCP client's success.

## Workstream B: Gemini API runtime and recorder

### Controller and memory

Build a provider adapter behind the shared run-controller interface scoped in PR #40,
proposed `gemini_runtime.py`. Pin `google-genai`, a supported model and the verified
Interactions API revision (official REST examples currently use `Api-Revision:
2026-05-20`). Validate current availability at implementation time; do not hardcode
an untested latest model or equate Gemini model access with Spark account access.

Bind every request to a Cortex principal/profile before context retrieval. Assemble
bounded memory with references/retrieval trace IDs, supply it to the model, and record
the policy and submitted prompt. Initial retention uses completed exchange records
and user-directed save; automatic memory extraction follows existing inference/proposal
gates. API keys stay server-side and never enter provider headers stored in recordings.

For the first canary use local Cortex context plus a harmless custom function. This
avoids making a public MCP deployment a prerequisite to validating API capture.
Then connect scoped remote tools with explicit `Authorization: Bearer` headers and
an allowlist. Do not assume provider-hosted MCP pauses for human approval: any action
requiring consent is a client-executed function controlled by our run controller.

### Event normalization and identity

| Source | Recorder mapping | Boundary |
|---|---|---|
| Submitted input | User prompt + context-reference metadata | Captured by our controller, not inferred from consumer chat |
| `interaction.created` and documented lifecycle outcomes | Provider interaction identity and state | SDK/API canary pins actual terminal/failure shapes |
| `step.start`, `step.delta`, `step.stop` | Step-correlated exposed output/tool observations | Type-aware filter; only text deltas on approved output steps |
| `function_call` / `function_result` | Tool request/result paired with call identity | Instrument actual local execution separately from provider-reported steps |
| `model_output` and final usage | Final visible output and available usage | Snapshot reconciliation is labelled; no fabricated timing |
| `thought` / thought signatures | Excluded from public recorder | Protocol state handled privately where required for continuation |

Maintain integration/profile, Cortex run/session, provider interaction ID, step index,
call ID and optional opaque event ID independently. Step index is local to interaction,
not a global ordering or tool ID. Distinguish continuation interactions from one user
run; a function result references `call_id` and may create another interaction with
`previous_interaction_id`.

PR #39 supplies bounded redaction, per-profile outbox and GraphStore diagnostic dedupe.
Extend it with an additive Gemini normalizer and spec changes for provider correlation,
run registry and checkpoints. Preserve frozen memory/exchange/receipt/hash contracts.
Thought/signature steps required by stateless provider continuation must never be
redacted then replayed as though intact: prefer server-side continuation for the pilot;
if stateless mode is offered, keep exact necessary protocol state in separate protected
short-lived runtime storage, excluded from memory/export/viewer/logs.

### Recovery, lifecycle and retention

Queue sanitized events before updating the durable `last_event_id`. Deduplicate using
profile/integration + interaction + provider event ID when available. For events lacking
IDs retain occurrence identities and explicitly weaker retry coverage; identical text
chunks remain separate. Restart recovers the checkpoint/outbox, resumes the provider
stream and avoids duplicate persisted events after a lost ACK.

Background execution requires provider storage consent/configuration. If retrieval or
resume becomes unavailable through expiry/deletion/error, retrieve a final snapshot
when possible and mark the gap; never invent missing timed events. Handle 401/429/5xx,
unknown outcome after submission timeout, cancellation, failed/incomplete runs and
queue backpressure. Do not blindly resubmit charged work after ambiguous creation.
Observe provider terminal cancellation rather than assuming the cancel request ends
all execution immediately; canary the actual state transitions.

Provider tools/model/config are not automatically inherited across all continuation
calls: resend required settings per the documented contract. Verify missing/wrong
interaction ID, cross-account continuation and store=false behavior. Apply Cortex
retention separately to queue, run registry, checkpoints, protocol state and recordings.

### Shared recorder feed and UI

Reuse the authorized session-cursor feed and viewer scoped in PR #40, not a second
Gemini-only timeline. Show live edge, pause display while capture continues, seek,
speed, source-vs-receipt time, content omission and known gaps. Separate Spark MCP
calls (`capture_surface=spark_custom_app`) from API recordings (`gemini_interactions`).
Playback reads recorded events; it never re-executes tools/model requests.
Metadata-only mode cannot replay omitted text. Respect existing content/frame bounds;
exclude unbounded multimodal bytes, browser sessions and raw thought content from the
initial pilot. Multimodal recordings need a later explicit artifact/retention contract.

## Milestones and validation gates

Estimates are preliminary engineering effort for one contributor, not elapsed delivery
promises; access, review and representative burn-in can extend them. Shared recorder
work is counted once across providers, not separately per adapter.

| Milestone | Scope | Exit gate | Estimate |
|---|---|---|---|
| G0 | Official contracts, pinned SDK/model fixtures, account eligibility and synthetic API run | API event/step/ID/retention shapes verified; hosted Spark OAuth assumptions separated | 1–2 days |
| G1 | OAuth MCP resource and Spark onboarding | Full real Spark connect/recall/revoke chain, scope/isolation tests; documented blocker if client fails | 3–5 days |
| G2 | Gemini runtime, normalizer, checkpoint and worker | Stream, tool pairing, restart/resume, lost ACK, cancellation and policy tests | 3–5 days |
| G3 | Shared feed/timeline integration | Cross-provider playback, authorized cursors, gaps, pause/seek/speed and live catch-up in UI | 3–5 days if shared UI not yet built |
| G4 | Operator pilot and support | Budgets, retention, health/connection doctor, restart/load drill and repeatable synthetic canaries | 2–4 days |

Full initial scope G0–G4: **12–21 engineering days** if shared UI/OAuth are new.
If Perplexity delivers the shared recorder UI first, Gemini scope reduces by that
already-completed work. A failed Spark OAuth canary does not block Gemini API adapter
implementation; release memory connector and API recorder as independently verified
capabilities. No milestone for full hosted Spark capture is committed without a
supported provider interface.

| Test area | Acceptance evidence |
|---|---|
| Spark OAuth | Discovery, code/PKCE, token exchange, refresh, revoke; wrong resource/audience/profile denied |
| Memory | Scoped synthetic fact remembered and retrieved in a fresh Spark task/API run; other identity denied |
| API contracts | Actual step types, text deltas, function/result IDs, final usage and model/revision recorded |
| Recovery | Reconnect using opaque event ID, duplicate/conflict, missing ID, restart, lost ACK, expiry/deletion gap |
| Content | Secret redaction before queue/store; thought/signature exclusion; bounded text; multimodal omission |
| Runtime state | store=false/background incompatibility, continuation configuration, unknown submission outcome, terminal cancellation |
| Tool control | Client execution actually observed; scoped remote MCP; consent-controlled external actions; no tool reruns on playback |
| Feed/UI | Tenant/cursor isolation, catch-up, live edge, pause/seek/speed, omitted text and known gaps |
| Operations | Rate limits, budgets/concurrency, dead letters, lag, credential rotation and retention sweeps |

Proposed pilot target: Cortex receipt-to-visible-event p95 within 2 seconds under a
declared workload. This is not a guarantee of provider emission latency. Publish
concurrency/duration/payload/hardware and actual p50/p95 before claiming a service SLA.
Use fixture tests for local adapter behavior and sanitized paid API canaries for
provider compatibility. Spark connection tests require an eligible actual account.

## Primary references and research evidence

Official Google/MCP pages reviewed 2026-10-06:

- [Custom apps in Gemini Apps](https://support.google.com/gemini/answer/17209137)
- [Spark requirements and behavior](https://support.google.com/gemini/answer/17094507)
- [Interactions overview and retention](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Interactions getting started and stream examples](https://ai.google.dev/gemini-api/docs/get-started)
- [Background execution and last_event_id](https://ai.google.dev/gemini-api/docs/background-execution)
- [Function calling, stateful/stateless loops and remote MCP](https://ai.google.dev/gemini-api/docs/function-calling)
- [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

Forum observations, not current compatibility guarantees:

- [August Spark OAuth callback report](https://discuss.ai.google.dev/t/gemini-spark-custom-mcp-oauth-stops-after-302-callback-and-never-calls-token/177327)
- [October 2 OAuth exchange report](https://discuss.ai.google.dev/t/gemini-app-spark-custom-apps-mcp-oauth-never-exchanges-the-code-cannot-complete-request-on-oauth-redirect-googleusercontent-com/186405)
- [Vendor onboarding discussion and October 5 reported working custom app](https://discuss.ai.google.dev/t/how-can-third-party-software-vendors-integrate-with-gemini-spark-other-apps-and-gemini-connected-apps/177442)

[Hindsight's Spark memory guide](https://hindsight.vectorize.io/guides/2026/07/17/guide-gemini-spark-memory-with-hindsight)
is competitor research only. Its Antigravity config/manifests do not override Google's
consumer Connected-App installation flow.

Scope validation: named Cortex transport/auth/context seams inspected, official docs
and forum dates checked, Markdown structure and diff checks passed. This revision
changes documentation only. Existing backend tests are not Gemini compatibility tests;
no live Spark/Gemini canary, provider account entitlement or production readiness is claimed.
