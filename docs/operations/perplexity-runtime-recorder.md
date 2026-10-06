# Perplexity API runtime recorder

The existing `PerplexityAdapter.run` records a request and final response.
`PerplexityAdapter.recorder()` adds application-owned background streams, incremental
capture, durable restart cursors, cancellation, scoped memory injection and replay.
It implements the existing runtime bridge contract; it does not observe arbitrary
Perplexity consumer-app or Computer sessions.

## Configure and launch

Install Cortex with its documented sibling integrity-core layout (`uv sync --extra
otel`). In the intended Cortex home's `config.yaml`, explicitly enable telemetry:

```yaml
telemetry:
  enabled: true
  consented_providers: [perplexity]
  retention_tier: digest
  allow_raw_payloads: false
```

Use your real session-bound `did:integrity:...` agent identity. Set
`PERPLEXITY_API_KEY` privately in the process environment. Do not place the key in a
prompt, command-line argument or committed payload file. The API key and API billing
are separate from consumer connector onboarding.

Example `request.json`:

```json
{"preset":"fast","input":"Research the tradeoffs of three database backup approaches.","tools":[{"type":"web_search"}]}
```

```bash
uv run xibalba-cortex-perplexity start \
  --home /path/to/cortex-profile --agent-id did:integrity:YOUR-ID \
  --run-id backup-research --payload request.json
```

The launcher prints the local run ID, then flushed JSONL events as provider events
arrive and are committed. It forces `stream=true` and `background=true`, using the
Agent API rather than Sonar. Optional `--memory-query "backup requirements"` injects
only this agent's active/confirmed Cortex memories as explicitly untrusted evidence.
It does not automatically save the resulting answer or commit extraction proposals.
Raw request files may configure provider built-in tools or remote MCP tools; those
are passed through, not executed locally by Cortex. Review configured tools before
launching: Perplexity's remote MCP calls may run automatically. This adapter is an
observer/launcher, not an approval or Shield enforcement layer. Custom function
calls are recorded but are not executed or automatically continued in this slice.

## Live view, restart and replay

In another terminal, follow the same durable journal while a run is active:

```bash
uv run xibalba-cortex-perplexity replay --watch \
  --home /path/to/cortex-profile --agent-id did:integrity:YOUR-ID --run-id backup-research
```

Use `status` with the same arguments to inspect provider response ID, committed
provider sequence cursor, local status, content mode and capture-gap flag. After a
disconnection or process restart, use `resume`. It performs a GET after the committed
cursor; it never automatically repeats a creation POST. If the response ID was never
received, status remains uncertain and resume refuses to create a second billed run.
If the provider rejects reconnect with HTTP 400, the recorder marks a capture gap
and fetches a snapshot. A snapshot does not reconstruct missing historical deltas.
Use `snapshot` to refresh a pending run explicitly; use `cancel` to request provider
cancellation, then `snapshot` to confirm the terminal state. `cancelling` is not
reported as `cancelled`.

`replay --after N` resumes local reading after a **local journal position**.
That cursor is distinct from Perplexity's `sequence_number`. JSONL rows carry arrival
timestamps and tool item IDs for correlation. The existing viewer can inspect the
mirrored session telemetry under `perplexity:<run-id>`; a new viewer player/launch
panel is not included. A replay consumer can render or replay the saved stream
without issuing another provider request. Replay never re-executes tools.

## Capture and durability

Default capture retains lifecycle, event identities, usage, hashes, sizes, correlation
and error classifications. It does not save response text or tool arguments/results.
Opt in to `allow_raw_payloads: true` for bounded, redacted final message and complete
string tool argument/result capture. Text deltas remain hashes/counts even then:
redacting a secret split across chunks is unsafe until the complete text is available.
Reasoning/thought bodies and summaries are excluded in every mode. The final usage
and numeric cost fields are recorded where the provider returns them; arbitrary
provider bodies, exception messages and credentials are excluded. Body/event limit
is 1 MiB; selected text capture is capped at 16,000 characters per field. Unknown
event types retain envelope identity, not their raw body. Missing provider fields
remain missing rather than being inferred.

The profile-local `perplexity-runtime.sqlite3` WAL journal commits each normalized
event and cursor atomically before the live event is returned. GraphStore receives
idempotent runtime events afterward. Resume/flush can deliver pending journal events
without duplicating existing telemetry after a lost acknowledgement. A stream
worker lease prevents concurrent resume workers; after a crash it expires in three
minutes. Provider sequence gaps and conflicting replay sequences are detected.
Events without provider sequence numbers get occurrence IDs; strong cross-reconnect
deduplication is unavailable for those events.

The journal is an additional local copy of provider telemetry. Existing provider
telemetry export/delete commands govern GraphStore only, not this journal. Back up
or remove the recorder journal separately under the deployment's retention policy;
stop its workers before removing it. Replay requires the same agent binding and, for
content-mode runs, current content-capture consent. It is a local CLI/library surface,
not a new multi-tenant remote API. Lease ownership does not provide remote auth.

## Validation boundary

Tests exercise a real incremental HTTP stream, consent and local agent binding,
SSE framing, repeated identical deltas, final tool items, restart/resume, duplicate
replay, cancellation, snapshot fallback, privacy and memory isolation. Fixture
public keys relate to the separate hosted connector, not Perplexity API auth.
No live Perplexity call was made or billed during development. A real API-key canary
is still required for provider-specific event variants, background retention,
remote MCP dispatch and account limits.

Official contracts:
- https://docs.perplexity.ai/docs/agent-api/output-control
- https://docs.perplexity.ai/docs/agent-api/background-mode
- https://docs.perplexity.ai/docs/agent-api/tools/mcp
