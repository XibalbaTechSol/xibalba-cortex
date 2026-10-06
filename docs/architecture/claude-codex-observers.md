# Claude and Codex recorder observers

Status: initial local capture implementation, 2026-10-06. This is a B0/B6 recorder
work slice under integrity-core's existing execution plan, not a new execution ledger.
The live recorder viewer and timed playback are separate, unfinished work.

## Supported installation and capture

| Runtime | Entry point | Delivered coverage | Limits |
|---|---|---|---|
| Claude Code | Settings command hooks installed by `xibalba-cortex-observer-install` | Session start/end, submitted prompt, pre/post tool, tool failure, approval request, stop/final message, subagent lifecycle | Callback receipt timing unless source timestamp supplied; native turn IDs often absent; no complete model request, token stream, or approval verdict capture. |
| Codex local CLI | Native command hooks in explicit `hooks.json` | Session/turn callbacks, prompt, pre/post tool, approval request, stop/final message, subagents, interruption and compaction | User must review/trust definitions via `/hooks`. No hosted web-search capture or token stream; specialized tools may omit hooks. |
| Codex app-server | `normalize("codex", message)` and `enqueue(home, event)` from the client that owns the event stream; `codex-stream` consumes a copied JSONL stream | Thread/turn lifecycle, user/agent items, tool lifecycle, agent/command deltas, approval request/resolution observations | Client integration required. Does not attach to another app-server client, CLI, IDE or ChatGPT Work session. No automatic approval, transport proxy or model execution. |
| Existing interactive Codex fallback | `xibalba-cortex-codex-mcp-backfill --watch` | Completed prompt/response turns and reconstructed tools from local transcripts | Polling and transcript format dependence; incomplete turns skipped; not a live event recorder. |

These interfaces were checked against the official [Claude hook
reference](https://code.claude.com/docs/en/hooks) and [Codex app-server
reference](https://developers.openai.com/codex/app-server) and [Codex native hooks](https://developers.openai.com/codex/hooks) on 2026-10-06.
Claude provides JSON on stdin and command-hook settings; the selected hook payloads
carry prompts, tool IDs/input/result and final assistant messages where available.
Codex emits JSON-RPC notifications and approval requests on its active client stream.
Its item IDs correlate start/completion and deltas. Capture does not claim the
notification stream is a passive subscription to arbitrary existing sessions.

## Install Claude (Linux/POSIX pilot)

Install Cortex using the currently supported sibling integrity-core layout (`uv sync
--extra otel`); standalone SDK packaging remains an external product gate. No
published `pip install` experience is implied by these commands.

Choose an explicit Cortex profile and settings file. For example:

```sh
uv run xibalba-cortex-observer-install install \
  --settings "$HOME/.claude/settings.json" \
  --home "$HOME/.local/share/cortex/pilot" --mode metadata

uv run xibalba-cortex-observer drain \
  --home "$HOME/.local/share/cortex/pilot" --watch
```

Run the drain worker in a second terminal, or under an operator-managed process
supervisor. Service registration is not installed automatically. Restart Claude,
submit a prompt, and execute a benign tool to validate callback delivery. Inspect:

```sh
uv run xibalba-cortex-observer status --home "$HOME/.local/share/cortex/pilot"
```

Settings installation preserves existing hooks/permissions, is idempotent, writes
atomically, and keeps a first backup. The command pins this environment's Python
executable; reinstall after moving/replacing the environment. Hooks enqueue only,
print nothing to stdout, return success on capture errors and emit a fixed stderr
message. They never approve, deny, modify a tool call or inject agent context.
Restart/reload behavior and minimum installed Claude version require a live canary.

To remove only these hooks:

```sh
uv run xibalba-cortex-observer-install uninstall \
  --settings "$HOME/.claude/settings.json" --home "$HOME/.local/share/cortex/pilot"
```

The backup is retained. Stop the drain process separately; uninstall does not delete
recordings. Windows shell quoting/service installation is outside this pilot slice.

## Install Codex native hooks (local Linux/POSIX pilot)

Use the same Cortex environment and drain worker above:

```sh
uv run xibalba-cortex-observer-install install --runtime codex \
  --settings "$HOME/.codex/hooks.json" \
  --home "$HOME/.local/share/cortex/pilot" --mode metadata
```

Review the exact definitions with Codex `/hooks` and trust them explicitly before
running the canary. New or changed definitions require renewed trust; the installer
does not bypass that requirement. Administrator policy can disable local hooks.
This installs local CLI hooks, not hooks in hosted ChatGPT Work sessions.
SessionEnd and Interrupt use the documented three-second maximum. Codex callbacks
return `{}` on stdout, including failure, to satisfy Stop/SubagentStop JSON parsing
without supplying decisions or model context. PostToolUse captures available output;
Codex has no separate PostToolUseFailure hook in the documented contract. Turn IDs
are retained where supplied. Hooks do not capture every tool path or token delta.

```sh
uv run xibalba-cortex-observer-install uninstall --runtime codex \
  --settings "$HOME/.codex/hooks.json" --home "$HOME/.local/share/cortex/pilot"
```

As with Claude, settings are preserved and installation is idempotent. Live release,
trust/reload, callback ordering and deadline validation remain canary gates.

## Connect a Codex client

Copy messages from a client you control before discarding them. Observation must
remain separate from request handling and approvals. Example callback:

```python
from pathlib import Path
from xibalba_cortex.observer_capture import enqueue, normalize

event = normalize("codex", message, mode="metadata",
                  occurrence_id=durable_capture_occurrence_id)
if event is not None:
    enqueue(Path(cortex_profile), event)
```

Assign a durable capture occurrence ID before retrying. For streamed deltas this
must distinguish each chunk, including identical consecutive chunks. Enqueue off
the event-loop thread if a blocking local write would interrupt your client.
Unsupported and reasoning events are excluded; no raw reasoning is recorded.

For a copied JSON-RPC stream (not `codex exec --json`, which is a different schema):

```sh
uv run xibalba-cortex-observer codex-stream \
  --home "$HOME/.local/share/cortex/pilot" < copied-app-server-messages.jsonl
```

This command enqueues events as lines arrive, does not echo the transport or
answer server requests, and exits nonzero if supported input could not be captured.
Its automatically generated IDs distinguish deltas on one pass; replaying an entire
file is not exactly-once chunk ingestion. Use the Python interface with retained
occurrence IDs for reconnect/replay. Stable item lifecycle IDs deduplicate repeats
and reject conflicting payloads while queued. The same drain worker persists them.

## Storage, access and recording policy

Events use additive `xibalba.observer.capture.v1`, the existing bounded outbox and
GraphStore telemetry deduplication. No canonical memory/receipt/hash-chain schema
is replaced. The observer queue is per profile, has only the observer persistence
destination, and supports lease recovery, retries and dead-letter states. Enqueue
success proves queuing, ACK proves persistence; neither proves complete capture.
The worker recovers a lost ACK without inserting the event twice. Ordering is
ingestion order plus available source correlation, not claimed total source order.

`metadata` mode stores a redacted-content hash/length and correlation metadata.
`redacted` mode includes allowlisted content after string and key-aware redaction;
it is enabled explicitly during installation/client configuration. Content above
6,000 encoded bytes is omitted with a visible reason. Callback IDs, tool names and
other metadata remain sensitive operational data; metadata mode is not a general
regulated-data compliance guarantee. Input frames are capped at 1 MiB. Redaction
is applied before both queuing and persistence.

Observations are visible through the existing authenticated, session-scoped
`GET /api/session/{id}/otel` as `xibalba.observer.event`. Existing telemetry retention
sweeps apply to GraphStore; terminal queue copies prune after one day. Operators
must run retention sweeps and configure retention/backup for the profile. This
slice does not create exchange transcripts, add memory-retrieval records, feed
Integrity SDK/Oracle, or establish signed/anchored recorder evidence.

## Validation and remaining work

Validated against Cortex base `be224bf` and CI-pinned integrity-core
`4ddaae1965635224958e147f6eaaead06e3cdc41` with `uv sync --extra otel`:

- `uv run pytest -o addopts='' -q -ra`: **574 passed, 2 skipped**, 33.92 seconds.
- Focused observer/backfill suite: **27 passed**.
- The skips are the opt-in live Hermes smoke and sustained inference-load drill.
  Two deprecation warnings remain (websockets legacy and threaded-process fork).
- `git diff --check`: passed. Viewer code is unchanged; no viewer validation claimed.

`tests/test_observer_capture.py` exercises actual installer commands and real local
queue/GraphStore persistence, metadata-only and redacted modes, bounded content,
tool correlation, repeated messages, conflicting IDs, lost-ACK lease recovery,
store unavailability, profile separation, reasoning exclusion and silent fail-open
Claude subprocess behavior and Codex native-hook installation, empty-JSON fail-open
behavior, timeout limits and turn/tool correlation. Existing Codex backfill tests remain unchanged.

Still required before shipping the recorder experience:

- Live canaries on pinned Claude and Codex versions; confirm installed hook schemas
  and client wire messages, callback order, approval/cancellation and subagent behavior.
- Durable client-side chunk sequence/source ordering and additional content coverage.
- Incremental transcript fallback for local Codex sessions where native hooks are
  unavailable; current backfill alone is not the event-stream observer.
- A scoped cursor API/live feed and viewer timeline/playback controls over these
  occurrences; current exchange replay does not automatically include this new stream.
- Managed worker installation, upgrade/doctor/uninstall, producer-loss metrics and
  viewer health/gap reporting, concurrent sustained load and representative burn-in.
- Cross-product Shield decision correlation, proof coverage and customer export.

Neither harness binary is available in this execution environment. Passing fixture
and subprocess storage tests is not a claim of live harness verification, latency
SLA, production rollout or recorder completeness.
