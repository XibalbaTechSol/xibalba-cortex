# Session Log: Graph Memory Build + Integrity Protocol Coupling — 2026-08-05

Status: session record, not a spec. Referenced from
`spec/xibalba-graph-memory-v1.md`, `docs/operations/resource-readiness.md`, and
`INTEGRITY-LATEST/docs/design/memory-dag.md`. Written to capture what was built, where
confusion happened and why, and what was decided — so a future session (or a future
architecture decision) doesn't have to re-derive any of this from git log archaeology.

## 1. What this session built (chronological)

Started by picking up a partially-implemented project (`xibalba-graph-memory`: two plan docs, a
research register, ~40% of a SQLite store, 3/5 tests passing) and continuing it. In order:

1. **Reclaimed disk/resources.** Machine was at 2.1GB free / 99% full, 248MiB free RAM. Freed
   ~80GB (Rust `target/` dirs, Docker unused images/cache, package manager caches) — none of it
   touched source or user files.
2. **Ran a benchmark-gated database spike** rather than defaulting to the advanced plan's stated
   PostgreSQL-canonical choice: SQLite beat DuckDB 1.5x on throughput and ~4x on resident memory
   for this system's actual single-row transactional write pattern. PostgreSQL was never
   installed — its stated advantages (multi-tenant concurrency, Row-Level Security) don't apply
   to a single-user local agent. Documented in `docs/architecture/advanced-memory.md`.
3. **Ran a Devil's Advocate review** (mandatory before Integrity-adjacent architecture decisions)
   covering SQLite-as-authority, the one-way DAG coupling rule, and the four Phase 0 decisions.
   Recorded in `docs/architecture/advanced-memory.md` §3.
4. **Wrote the normative spec**, `spec/xibalba-graph-memory-v1.md`, consolidating every decision
   made up to that point into one authoritative document.
5. **Built the local event hash-chain**: `memory_events` became content-addressed and
   parent-linked (`node_id = sha256(canonical({schema, memory_id, event_type, detail,
   parent_event_id}))`), with `GraphStore.verify_chain()` recomputing and checking it — pure
   local computation, no external dependency. Documented in
   `docs/architecture/event-hash-chain.md`. *(This independently converged on almost the same
   shape as `INTEGRITY-LATEST`'s `memory_dag.py`, discovered later — see §3 below.)*
6. **Built the MCP stdio server** (`src/xibalba_graph/server.py`), one tool per `GraphStore`
   method, registered in `~/.hermes/config.yaml` under `mcp_servers.xibalba_graph_memory`
   (Supermemory left as the active provider, unchanged).
7. **Ran an embedding-model spike**: `BAAI/bge-small-en-v1.5` via `fastembed` was fast (77
   embeds/sec) but too memory-heavy (~270MB resident) to keep always-loaded in this always-on
   server given the machine's chronic ~200-400MB free RAM. Resolution: this store never computes
   embeddings in-process; `memory_embed` accepts a caller-supplied vector. Documented in
   `docs/architecture/embedding-model-spike.md`.
8. **Added `sqlite-vec` retrieval** fused with lexical search via Reciprocal Rank Fusion.
9. **Added online backup/restore** (`GraphStore.backup()`/`restore()`), closing a gap from the
   original 9-task plan. `restore` is deliberately not exposed as an MCP tool — destructive, and
   this server has no approval-gating mechanism yet.
10. **Added resilience tests** for concurrency (two real SQLite connections, not one connection
    shared across threads), simulated crash recovery (genuine subprocess + `os._exit(1)`, not
    `del` — which was tried first and found not to reliably release SQLite's OS-level lock
    in-process), and profile isolation.

By this point: 24/24 tests passing, 5 commits, spec + 5 architecture docs, MCP server live and
registered.

## 2. Where the Integrity Protocol coupling question started

The user asked whether `TrustVault` (the real, on-chain-anchoring evidence store already living
in `INTEGRITY-LATEST/integrity-sdk/integrity_sdk/vault.py`) should be *migrated into*
`xibalba-graph-memory`.

Checked the project's own persistent memory first, rather than reasoning from scratch:
`/home/xibalba/.claude/projects/-home-xibalba-Projects-INTEGRITY-LATEST/memory/two-memory-systems.md`
records a 2026-07-31 decision — evidence (append-only, anchored, never forgets) and recall
(local, mutable, forgets) must be two separate systems, after an earlier design that merged them
was explicitly reversed.

**Answered no to migration**, for three reasons that still hold: TrustVault underpins 7 live
on-chain-registered agents and `integrity-cli` carries an independent wire-compatible copy of it;
migrating wouldn't fix the actual gap (TrustVault's leaf schema is domain-separated over
commit/task/test-result tuples — a memory structurally cannot produce a matching hash); and it
would pull chain-RPC/anchoring concerns into a system whose whole design principle has been "no
key custody, no network calls on the hot path."

**Built `memory_vault_inspect` instead** — a read-only MCP tool that parses the real
`leaves.jsonl`/`anchors.jsonl` format independently (not a dependency on `integrity-sdk`) and
recomputes each leaf's Keccak hash from its stored fields rather than trusting the stored value.
Verified byte-identical against `integrity-sdk`'s own `eth_utils.keccak` before writing any test.
This does not and cannot verify memories — it inspects real commit/test evidence for its own
sake. `docs/operations/resource-readiness.md` and spec §6.3 were updated to state precisely what
TrustVault is and isn't, rather than leaving "the DAG doesn't exist" as the only stated reason
`integrity_links` can't verify anything.

## 3. The confusion, and the mistake made twice

The user then asked what TrustVault actually is and said "I may have made a mistake" about
caring about the two-system split at all — reasonable, since TrustVault turned out to be much
narrower than "the evidence layer" framing implied.

A Devil's Advocate review was run specifically on: should the Memory DAG be built right now, and
does the original split still hold given what TrustVault turned out to be. **The review's central
finding overturned a claim this session had already written down as fact, twice:**
`INTEGRITY-LATEST/integrity-sdk/integrity_sdk/memory_dag.py` is not a stub. It fully implements
all seven steps of `docs/design/memory-dag.md`'s design (node schema, canonicalization reusing
BCC's convention, ref store with supersede-on-edit, ancestry proofs, `root_of_heads`). Written
2026-07-31 with no shell available and never executed; the design doc's own status line said
"not implemented, not tested," and `INTERFACE_CONTRACT.md` §4.4b said `[UNVERIFIED, NOT RUN]`.
Nobody had actually run `tests/test_memory_dag.py` in the five days since.

**This session had, twice, written "the DAG is unimplemented" into `resource-readiness.md` and
the spec** — trusting the design doc's status header instead of checking whether the code
actually worked. Both corrections were independently verified before being trusted:
`tests/test_memory_dag.py` run directly, 21/21 passing including the cross-runtime provenance
acceptance test; `import_memory_dag.py --dry-run` run against the real vault (73 leaves, 52
would-be-added nodes, 21 already present, nothing written — read-only, no chain interaction).
`INTERFACE_CONTRACT.md` §4.4b and `memory-dag.md`'s status line were corrected to
`[VERIFIED 2026-08-05]`. The real (non-dry) import and on-chain anchoring via
`anchor_memory_dag.py` were deliberately **not** run — anchoring is an irreversible signed
transaction against the live agent and stays a separate, explicit decision.

**The lesson, stated for future sessions:** check whether unrun code actually works before
trusting a status header that says it doesn't. A "design — not implemented" label can go stale
the moment someone else finishes the implementation and forgets to flip it.

## 4. The three systems, disambiguated

| | **TrustVault** | **Memory DAG** | **xibalba-graph-memory** |
|---|---|---|---|
| Records | Commit + test-result evidence for the protocol's own development | Any content, with provable version history | Facts, preferences, project context, conversation history |
| Status | Real, live, anchors on-chain for 7 agents | Real, tested (21/21) as of today; **not yet anchoring or wired to anything** | Real, built this session |
| Lives in | `INTEGRITY-LATEST` | `INTEGRITY-LATEST` (different module) | Own repo |
| Node kinds | `commit` only | `memory`, `commit`, `session`, `test_result`, `lineage` — deliberately a superset | N/A (its own event schema) |

`memory_dag.py`'s `NODE_KINDS` including `"memory"` is the concrete reason it — not TrustVault —
is the real eventual target for `xibalba-graph-memory`'s `integrity_links` citation.

## 5. The open question: one coherent system, "implicitly"

After the disambiguation, the user's instinct recurred in a sharper form: not "migrate TrustVault
in," but "could one coherent system function as all three, implicitly, instead of three explicit
codebases?"

This deserved a real second look rather than a repeated "no," because one premise behind the
original split turns out to be weaker than it first appears: **forgetting, as actually
implemented in `xibalba-graph-memory`, is not deletion.** `forget_memory()` sets a status flag
and returns `content_hash_retained: true` — the immutable event-hash-chain row persists,
hash-verifiable, forever. Both this system and the DAG are append-only underneath. The real
distinguishing property isn't mutability at all — it's **who can trigger an irreversible, costed,
on-chain commitment, and which records get selected for it.** That's an authorization/policy
question, not a storage-architecture one. `xibalba-graph-memory` already has the seed of exactly
this: `evidence_class` per record, and an anchoring-selection policy (§6.4 of the spec) that
already says "always anchor `declared_intent`/`policy`, randomly sample the rest" — per-record
policy differentiation within one schema.

**Current recommendation (not yet acted on): unify the data model, keep the anchoring authority
and deployment boundary separate.** One canonical event/node schema — shared canonicalization,
compatible hash-chain shape — is worth converging on regardless of what else happens, since
`xibalba-graph-memory`'s own hash-chain already independently arrived at nearly the DAG's shape.
Concretely, "convergence" means either documenting the schema parallel explicitly or vendoring
`memory_dag.py`'s canonicalization helper into `xibalba-graph-memory` the way `integrity-cli`
vendors BCC logic rather than importing `integrity-sdk` (shared format, separate authority —
the existing pattern in this codebase for exactly this situation).

What still argues against merging the *codebases/repos*: `INTEGRITY-LATEST` runs under a
"no silent mocks, don't ship code you haven't run" discipline because real signed transactions
and 7 live agents' reputations sit downstream of it — a discipline this session's own two
mistakes (§3) demonstrate isn't automatic to maintain even when trying. Unifying repos means
either the protocol's production evidence infrastructure inherits a faster-moving, less-reviewed
side project's bar, or the memory system inherits the protocol's heavier ceremony and loses the
iteration speed this session has had. That's a governance/velocity tradeoff, not a technical
impossibility — worth deciding deliberately, not by default.

**This is not yet decided.** No code has been written toward either unifying the schema or
keeping them independently evolving. The next concrete step, if pursued, is documenting or
vendoring the shared canonicalization convention — nothing structural yet.

## 6. What was NOT done, and why

- **`integrity_links` was not wired to read the DAG.** The DAG's implementation status changed
  today; the citation code (writer + reader in `xibalba-graph-memory`) does not exist yet. This
  is unstarted work, distinct from "the DAG doesn't work."
- **`import_memory_dag.py` was not run for real** (only `--dry-run`). Locally reversible
  (re-derivable from vault leaves) but still a write; left for explicit go-ahead.
- **`anchor_memory_dag.py` was not run at all.** Real signed on-chain transaction against a live
  agent. Deliberately out of scope without a separate, explicit decision — this is the one
  action in this entire session with genuine on-chain irreversibility.
- **The "unify the data model" idea in §5 was not implemented.** Recommendation only.

## 7. OTel telemetry: a local mirror, deliberately not a path into the oracle's scored data

Asked whether telemetry/OTel data currently stored in the Integrity Oracle would make more
sense in the agent's graph memory instead. Read the oracle's actual schema before answering
rather than reasoning from the "telemetry" label alone
(`integrity-oracle/backend/migrations/0001`, `0004`, `0008`).

**Finding: the oracle already keeps two telemetry tiers deliberately separate, for a load-bearing
reason.** `telemetry_events` is Ed25519/secp256k1-signed, nonce-replay-protected, Merkle-anchored,
and feeds AIS scoring directly (`db::aggregate_for_ais`). `otel_spans`/`otel_metrics`/`otel_logs`
arrive over an unauthenticated OTLP port and are explicitly tagged `evidence_tier =
'unsigned_vendor'` — the migration comments state plainly they "must never feed AIS." Mixing an
unauthenticated input into a scored, cross-agent-comparable reputation number would let anyone
inflate their own score.

**Decision:** don't move `telemetry_events` — same shape of argument as the TrustVault-migration
question in §2. It's queried live by a public API for any registered agent on demand, which
needs an always-on, centrally-reachable service; a profile-local store can be offline and
isn't queryable by third parties, so it can't serve that role.

The unauthenticated OTel tier is a genuinely different case: not because it's less important, but
because nothing stops it being **dual-homed**. The oracle keeps its copy for protocol-wide
dashboards (the trace-tree view reconstructs traces across agents from a global `trace_id`,
which also needs central visibility). Separately, `xibalba-graph-memory` gained `otel_events`
(§4.9 of the spec) — same shape as the oracle's unsigned tables, so an existing OTel export can
be piped to both with no translation — as the operator's own private, offline-capable diagnostic
mirror. This isn't a replacement for the oracle; it's the same gap between "protocol-wide
observability" and "my own agent's audit trail" that motivated this whole project, applied to
telemetry specifically.

## 8. "What does the SDK do that the MCP memory server can't?" led to finding a real, live security gap

Asked to compare capabilities, then asked to picture "an MCP server that does what the SDK
currently does" — i.e., wrapping `integrity-sdk`'s signing/chain-writing capabilities as
agent-callable tools, the way `xibalba-graph-memory` wraps recall. Flagged this as a
fundamentally different risk class before designing anything: an MCP tool call is an LLM's own
tool-selection judgment, not a deliberate human action, and that is not an acceptable gate for a
real signature or an irreversible on-chain write. Asked for a Devil's Advocate review before any
design work, per the standing mandate — and asked for it explicitly *before* building, "if i
change my mind it needs to be now instead of after everything has been built and tested."

**The review found the proposal wasn't hypothetical — a version of it already existed and had
already shipped the exact gap under review.** `integrity_sdk/mcp_server.py`
(`INTEGRITY-LATEST`) defined `integrity_register_agent` as a live, callable MCP tool loading a
real Ed25519 identity key and capable of running a full on-chain registration, with zero
coverage from `~/.claude/xibalba/pretool_gate.py` — the one gate anyone was relying on matches
only `{"Bash","Write","Edit","MultiEdit","NotebookEdit"}`, no MCP tool name pattern at all. Every
specific claim in the review (the tool's existence and behavior, the gate's blind spot and
fail-open posture, `bcc_middleware`'s fail-closed posture, MCP elicitation's actual semantics)
was verified independently before being trusted or acted on — same discipline as the Memory DAG
finding in §3, applied a second time. Confirmed separately: not wired into any running MCP
client config on this machine, so a real, reachable gap, not an active incident.

**Consensus reached, then acted on:** read-only SDK capability (status, DID resolution) is fine
as MCP tools; anything that signs or writes on-chain should never route through a tool call an
agent's own judgment triggers, full stop — not "needs better confirmation UI." Elicitation was
considered and rejected as a fix: its own docstring says a client "might" ask a human "or
automatically generate a response," which is not a safety property.

**Remediated, not just documented:**
- `integrity_sdk/mcp_server.py`: the four signing/writing tools
  (`integrity_flush_telemetry`, `integrity_invoke_intent`, `integrity_register_agent`,
  `integrity_commit_memory`) disabled by default at both discovery and dispatch, opt-in only via
  `INTEGRITY_MCP_ALLOW_SIGNING_TOOLS=1` for supervised local experimentation.
- `pretool_gate.py`: added MCP-tool-name coverage (`MCP_SIGNING_TOOL_NAMES`, matched by suffix)
  with a new `fail_closed` mode for this class specifically — the existing, deliberately
  fail-open Bash/Write/Edit posture (a ratified tradeoff for a dev shell, documented at length in
  that module's own docstring) was left completely untouched, not overridden.
- New tests in both repos (7 + 4), full existing suites re-run clean (252 SDK tests, 8 hooks
  tests) to confirm no regressions.
- Full design writeup: `INTEGRITY-LATEST/docs/design/mcp-signing-boundary.md`. Findings-log
  entry: `INTEGRITY-LATEST/PRODUCTION_GAPS.md` §25.

**What this means for `xibalba-graph-memory` going forward:** confirms, from a second and
sharper angle, why "no key custody" was made a hard invariant from this project's very first
architecture doc rather than a preference. This project will not grow a signing tool later by
the same incremental path that produced the gap being fixed here.

## 9. Validating the "collects all LLM text, categorized as OTel telemetry" premise — and closing the gap it found

Asked to validate and verify that the graph MCP server "collects all LLM text content and
successfully categorizes it as appropriate OTel telemetry," plus surrounding context (DID,
time), then to hypothesize whether more data is available. Ran real calls against the actual
MCP tools rather than reasoning from the code — found the premise didn't hold as stated:

- Text capture (`memory_remember`) works but is never automatic — an explicit call per turn,
  nothing intercepts "all" LLM output.
- Text content and OTel telemetry were **completely uncorrelated**: `otel_events` had no column
  referencing a memory, only `session_id` — a stored memory and its own turn's telemetry shared
  nothing queryable.
- "Categorization" (`evidence_class`) is a static default (`observed_event`), never
  content-derived — correct given the store runs no LLM in-process, but not what "categorizes
  it as appropriate" implies.
- DID/timestamp capture works correctly *when supplied*, but defaults to absent
  (`agent_id: None`, `observed_at: None`) if the caller doesn't pass them — and default `status`
  (`candidate`) is invisible to recall unless the caller upgrades it.

**Researched what's actually available before guessing.** Fetched Claude Code's own OTel
documentation (`code.claude.com/docs/en/monitoring-usage`) rather than assuming. Found real,
specific, previously-unknown-to-this-project detail: `claude_code.user_prompt` and
`claude_code.assistant_response` are real OTel log events carrying the actual prompt/response
*text* (redacted by default, opt-in via `OTEL_LOG_USER_PROMPTS=1`/`OTEL_LOG_ASSISTANT_RESPONSES=1`)
— i.e. "LLM text content as OTel telemetry" already exists upstream in the product this system
integrates with; the gap was never collecting it, not that it didn't exist. Also found
`prompt.id`, Claude Code's own UUID correlating `user_prompt`+`api_request`+`tool_result` for
one turn — exactly the missing link, with a name already chosen by the upstream product.

**Fixed:** added `prompt_id` to both `sources` and `otel_events` (weak/automatic correlation,
matching Claude Code's own key) and `otel_events.memory_id` as an explicit foreign key
(strong/asserted link, database-enforced — an unknown `memory_id` rejects the whole batch
atomically). New `memory_otel_events(memory_id)` returns the union, deduplicated. Verified with
a real correlation test before writing it up: a memory and its turn's `user_prompt`/
`token.usage` events, correlated by `prompt_id`, retrievable together; an event from a
different `prompt_id` correctly excluded.

**What's still a hypothesis, not fixed:** whether Claude Code's redaction should be lifted for
this system's own capture is a deployment decision, not something to default on behalf of the
operator — recorded as an open question in spec §4.9, not resolved. Standard Claude Code
attributes (`user.account_uuid`, `session.id`, `organization.id`) are real identity data not
yet wired into `agent_id` capture automatically — still requires the calling agent to pass them
through explicitly, same as before.

## 10. Universal ingestion, part two: a native adapter for the Hermes Agent

Following Path A/B/C (raw body files, OTLP `/v1/logs`+`/v1/traces`, real transcripts) and a
"universal ingestion across vendors" request that landed on the OpenTelemetry GenAI semantic
convention for OpenAI/Gemini/Codex, asked specifically to build a tool for the Hermes Agent —
"consider building on top of otel but if not then research."

**Researched before building, not assumed.** Grepped `~/.hermes/hermes-agent`'s actual runtime
code for OTel and found none — Hermes is not OTel-instrumented. It has its own contract instead:
"Observer Hooks" (`telemetry_schema_version = "hermes.observer.v1"`,
`docs/observability/README.md`), a typed in-process Python callback API with 15+ hooks and real
correlation IDs (`session_id`, `turn_id`, `api_request_id`, `tool_call_id`, parent/child
session/subagent ids). Confirmed the concrete registration pattern by reading the bundled NeMo
Relay plugin's actual `plugin.yaml` and `register(ctx)` call, not guessing the shape.

**Built `HermesObserverAdapter`** (`src/xibalba_graph/hermes_observer.py`) mapping that contract
onto the same `GraphStore` API every other path uses, reusing `turn_id` as `prompt_id` (same
reuse-not-invent pattern as Path B's `trace_id`) so `exchange_builder` works over Hermes-sourced
sessions unmodified. Full mapping and the pre_*/post_* collapse rationale in spec §4.15. Smoke
tested with a realistic hook sequence (`on_session_start` → `post_api_request` →
`post_tool_call` → `post_approval_response` → `post_llm_call` → `subagent_start`/`stop` →
`on_session_end`) before writing 12 formal tests covering the mapping, cross-session dedup, and
graceful no-ops for missing `session_id`/unknown future kwargs. Full suite green (95 tests).

**Deliberately not done this session:** actually installing the adapter as a running Hermes
plugin (`register(ctx)` shim + `plugin.yaml` under
`~/.hermes/hermes-agent/plugins/observability/`) — that writes into a different project's
codebase and is left as an explicit, separate step rather than bundled silently into "build a
tool for hermes."

## Related documents

- `spec/xibalba-graph-memory-v1.md` — the normative spec, §6.3 corrected per §3 above.
- `docs/operations/resource-readiness.md` — the honest-gaps doc, corrected twice per §3 above (the correction history is left visible in that file rather than silently edited away).
- `docs/architecture/advanced-memory.md` — database spike, first Devil's Advocate review, now-verified concurrency claims.
- `docs/architecture/event-hash-chain.md` — the local hash-chain design that converged on the DAG's shape independently.
- `docs/architecture/embedding-model-spike.md` — why embeddings are never computed in-process.
- `INTEGRITY-LATEST/docs/design/memory-dag.md` — the DAG's own design doc, status line corrected.
- `INTEGRITY-LATEST/docs/INTERFACE_CONTRACT.md` §4.4b — corrected to `[VERIFIED 2026-08-05]`.
- `/home/xibalba/.claude/projects/-home-xibalba-Projects-INTEGRITY-LATEST/memory/two-memory-systems.md` — the 2026-07-31 decision this whole thread re-examined.
- `INTEGRITY-LATEST/docs/design/mcp-signing-boundary.md` — the signing-boundary rule and the fix, §8.
- `INTEGRITY-LATEST/PRODUCTION_GAPS.md` §25 — the findings-log entry for the gap §8 found and closed.
